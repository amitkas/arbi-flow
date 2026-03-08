from google import genai
from google.genai import types

from context import PipelineContext
from logger import get_logger, StepTimer

SYSTEM_PROMPT = """You are an animation director for a 15-second video of a character named Arbi — a red furry monster with a gold crown.

YOUR JOB: Write a single, focused animation direction. The video model can only handle ONE clear action smoothly.

PRIORITY ORDER:
- PRIMARY: The gag MUST embody the chaos angle. The chaos angle is the comedic spin — your direction must bring it to life physically.
- SECONDARY: Use scene context only for setting or action ideas (where is Arbi, what prop/situation). Do NOT let scene context override the chaos angle.

RULES:
- Describe ONE physical gag in 1-2 short sentences (15-25 words max)
- The gag must connect to the real event through the chaos angle
- Think: what is the ONE funniest thing Arbi does that embodies the chaos angle?
- Describe simple, readable motion — one main action the camera can follow
- Do NOT list multiple actions or a sequence of beats
- Do NOT describe facial expressions, eye movements, or tiny details — the model can't animate those
- Do NOT re-describe Arbi's appearance (the image already shows him)
- Do NOT write dialogue
- Return ONLY the direction, nothing else

GOOD EXAMPLES (notice: one action, clear motion):
- "Arbi slides across the finish line on his belly, arms out like a plane, then pops up holding a trophy above his head"
- "Arbi yanks the microphone away and screams into it while the crowd behind him freezes in shock"
- "Arbi belly-flops onto the red carpet and rolls toward the camera, arms flailing like a starfish"

BAD EXAMPLES (too many actions, model can't follow):
- "Arbi bursts in, eyes spinning, dodges a car, leaps onto the hood, does a dance, then strikes a pose" (6 actions = incoherent)
- "Arbi's googly eyes widen as his jaw drops, then he flails his arms" (micro-expressions don't animate well)"""

log = get_logger("animation_director")


def write_animation_direction(ctx: PipelineContext, config: dict) -> PipelineContext:
    """Write animation direction for Arbi's troll behavior based on the trending event."""

    client = genai.Client(api_key=config["GEMINI_API_KEY"])

    user_prompt = (
        f"Write ONE animation gag for Arbi at this event.\n\n"
        f"EVENT: {ctx.event_title}\n\n"
        f"CHAOS ANGLE (PRIMARY — the gag MUST embody this): {ctx.chaos_angle}\n\n"
        f"SCENE CONTEXT (SECONDARY — use for setting/action ideas only, do not let it override the chaos angle): {ctx.scene_prompt}\n\n"
        "What is the single funniest physical action Arbi does that brings the chaos angle to life? "
        "1-2 sentences, 15-25 words. One clear motion the camera can follow."
    )

    log.debug(f"User prompt ({len(user_prompt)} chars):\n{user_prompt}")
    log.debug(f"System prompt ({len(SYSTEM_PROMPT)} chars)")

    max_attempts = 3
    direction = ""
    word_count = 0

    for attempt in range(1, max_attempts + 1):
        log.info(f"  [Animation Director] Generating direction (attempt {attempt})...")

        with StepTimer(log, f"Gemini animation direction (attempt {attempt})") as t:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Content(role="user", parts=[
                        types.Part(text=SYSTEM_PROMPT + "\n\n" + user_prompt)
                    ]),
                ],
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    max_output_tokens=500,
                ),
            )

        direction = response.text.strip()
        word_count = len(direction.split())

        log.info(f"  [Animation Director] Words: {word_count}")
        log.debug(f"  Generation took {t.elapsed:.2f}s")
        log.debug(f"  Raw direction:\n{direction}")

        if 10 <= word_count <= 30:
            ctx.animation_direction = direction
            ctx.video_script = direction  # backward compat with summary
            log.info(f"  [Animation Director] Direction accepted ({word_count} words)")
            log.info(f"  --- DIRECTION ---\n{direction}\n  --- END ---")
            return ctx

        if word_count < 10:
            log.debug(f"  Direction too short ({word_count} < 10), requesting longer version")
            user_prompt += "\n\nToo short. Write 15-25 words describing one physical gag."
        else:
            log.debug(f"  Direction too long ({word_count} > 30), requesting shorter version")
            user_prompt += "\n\nToo long. Cut it to ONE action in 15-25 words. No sequences."

    # Accept whatever we got on the last attempt
    ctx.animation_direction = direction
    ctx.video_script = direction  # backward compat
    log.info(f"  [Animation Director] Accepted after {max_attempts} attempts ({word_count} words)")
    log.debug("  Accepted despite not meeting word count target")
    log.info(f"  --- DIRECTION ---\n{direction}\n  --- END ---")
    return ctx
