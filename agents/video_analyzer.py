import time

from google import genai
from google.genai import types

from context import PipelineContext
from logger import get_logger, StepTimer
from utils.json_utils import parse_llm_json

log = get_logger("video_analyzer")

ANALYSIS_PROMPT_BASE = """Analyze this video in detail and return a JSON object with exactly these fields:

1. "video_analysis": A detailed 3-5 sentence play-by-play of what happens in the video.
   Describe the actions, reactions, and key moments chronologically.

2. "scene_prompt": A single sentence describing the main action for animation purposes,
   written as if a wacky red furry monster character named Arbi is performing it.
   Write it as a camera direction, e.g. "Arbi slips on wet floor, arms flailing wildly,
   arms flailing wildly as bystanders gasp".
   {scene_prompt_instruction}
   Keep it under 50 words. Always refer to the character as "Arbi".

3. "character_outfit": A detailed description of what the main person in the video is wearing.
   Include: type of clothing (dress, suit, jersey, t-shirt, uniform, etc.), colors, patterns,
   accessories (hat, sunglasses, jewelry, scarf), and any distinctive features. Be specific
   enough that an artist could recreate the outfit on a different character.
   Example: "Navy blue slim-fit suit with white dress shirt, red striped tie, silver watch"
   or "Bright red sequined gown with thin spaghetti straps, diamond drop earrings".

4. "character_gender": The gender of the main person — either "male" or "female".
   If unclear, default to "male".

5. "num_people": The number of people visible in the video (integer).

6. "video_keywords": Listen to the audio. Pick up to 5 standout spoken words or short phrases
   that would be funny if a troll character randomly yelled them out of context.
   Prefer punchy, emotional, or absurd-sounding words (e.g. "happy", "silver", "incredible",
   "oh no", "let's go"). Return as a JSON array of strings. If there is no clear speech,
   return an empty array [].

Return ONLY valid JSON. No markdown, no explanation. Do not put real newlines inside JSON string values — use \\n for line breaks. Keep each field value as a single line."""


def _build_analysis_prompt(chaos_angle: str) -> str:
    """Build analysis prompt with chaos_angle when available."""
    if chaos_angle:
        scene_instruction = (
            f"CRITICAL: Reflect this comedic angle in the scene: \"{chaos_angle}\". "
            "Describe the main action as Arbi would perform it with this spin. "
            "The scene_prompt MUST embody this comedic angle, not just the literal video content."
        )
    else:
        scene_instruction = "Focus on the most dramatic/funny moment."
    return ANALYSIS_PROMPT_BASE.format(scene_prompt_instruction=scene_instruction)


def analyze_video(ctx: PipelineContext, config: dict) -> PipelineContext:
    """Analyze the source video using Gemini's multimodal capabilities
    to understand what happened."""

    client = genai.Client(api_key=config["GEMINI_API_KEY"])

    log.info("  [Video Analyzer] Uploading video to Gemini File API...")
    log.debug(f"  Video path: {ctx.source_video_path}")

    # Upload video to Gemini File API
    with StepTimer(log, "Gemini File API upload") as t:
        video_file = client.files.upload(file=ctx.source_video_path)
    log.debug(f"  Upload took {t.elapsed:.2f}s, file name: {video_file.name}")

    # Wait for file to be processed
    log.info("  [Video Analyzer] Waiting for video processing...")
    while video_file.state.name == "PROCESSING":
        time.sleep(2)
        video_file = client.files.get(name=video_file.name)
        log.debug(f"  File state: {video_file.state.name}")

    if video_file.state.name == "FAILED":
        raise RuntimeError(f"Gemini video processing failed: {video_file.state.name}")

    log.info(f"  [Video Analyzer] Video ready, analyzing with Gemini...")
    analysis_prompt = _build_analysis_prompt(ctx.chaos_angle or "")
    if ctx.chaos_angle:
        log.info(f"  [Video Analyzer] Using chaos angle for scene_prompt alignment")

    # Send video + analysis prompt to Gemini (retry once on JSON parse failure)
    max_attempts = 2
    result = None
    last_error = None
    for attempt in range(max_attempts):
        with StepTimer(log, "Gemini video analysis") as t:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_uri(
                                file_uri=video_file.uri,
                                mime_type=video_file.mime_type,
                            ),
                            types.Part.from_text(text=analysis_prompt),
                        ],
                    ),
                ],
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=2048,
                ),
            )

        text = response.text.strip()
        log.debug(f"  Analysis response attempt {attempt + 1} ({len(text)} chars): {text[:500]}")
        log.debug(f"  Analysis took {t.elapsed:.2f}s")

        try:
            required_fields = ["video_analysis", "scene_prompt", "character_outfit", "character_gender", "num_people"]
            result = parse_llm_json(text, required_fields)
            break
        except ValueError as e:
            last_error = e
            if attempt < max_attempts - 1:
                log.warning(f"  [Video Analyzer] JSON parse failed, retrying once: {e}")
            else:
                log.debug(f"  Raw response (first 1200 chars): {text[:1200]}")
                raise

    ctx.video_analysis = result["video_analysis"]
    ctx.scene_prompt = result["scene_prompt"]
    ctx.character_outfit = result.get("character_outfit", "casual clothing")
    ctx.character_gender = result.get("character_gender", "male").lower()
    ctx.num_people = int(result.get("num_people", 1))
    ctx.video_keywords = result.get("video_keywords", [])[:5]

    # Normalize gender to male/female
    if ctx.character_gender not in ("male", "female"):
        ctx.character_gender = "male"

    log.info(f"  [Video Analyzer] Analysis: {ctx.video_analysis[:150]}...")
    log.info(f"  [Video Analyzer] Scene prompt: {ctx.scene_prompt}")
    log.info(f"  [Video Analyzer] Outfit: {ctx.character_outfit}")
    log.info(f"  [Video Analyzer] Gender: {ctx.character_gender}, People: {ctx.num_people}")
    log.info(f"  [Video Analyzer] Keywords: {ctx.video_keywords}")

    # Clean up uploaded file
    try:
        client.files.delete(name=video_file.name)
        log.debug("  Cleaned up uploaded video file")
    except Exception as e:
        log.debug(f"  Failed to clean up video file: {e}")

    return ctx


# Note: _parse_json removed - now using shared utils.json_utils.parse_llm_json
