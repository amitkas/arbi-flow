import json
import os
import time
import requests
from datetime import datetime, timedelta

from google import genai
from google.genai import types

from context import PipelineContext
from dedup import get_all_processed, is_already_processed, is_fuzzy_match
from logger import get_logger, StepTimer
from agents.arbi_persona import OFF_LIMITS_TOPICS, OFF_LIMITS_PROMPT
from utils.json_utils import parse_llm_json

MAX_RETRIES = 3
RETRY_DELAY = 15  # seconds
TREND_CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "trend_cache.json")
TREND_CACHE_TTL_MINUTES = 60

log = get_logger("video_scout")


def _load_trend_cache() -> dict | None:
    """Load cached trend if fresh (within TTL). Returns None if stale or missing."""
    if not os.path.exists(TREND_CACHE_FILE):
        return None
    try:
        with open(TREND_CACHE_FILE, "r") as f:
            cache = json.load(f)
        cached_at = datetime.fromisoformat(cache["cached_at"])
        if datetime.now() - cached_at < timedelta(minutes=TREND_CACHE_TTL_MINUTES):
            return cache["result"]
    except Exception:
        pass
    return None


def _save_trend_cache(result: dict) -> None:
    """Cache a trend result with current timestamp."""
    os.makedirs(os.path.dirname(TREND_CACHE_FILE), exist_ok=True)
    with open(TREND_CACHE_FILE, "w") as f:
        json.dump({"cached_at": datetime.now().isoformat(), "result": result}, f, indent=2)


def find_trending_video(ctx: PipelineContext, config: dict) -> PipelineContext:
    """Find the most notable real-world event covered by mainstream media.
    Primary: Gemini with Google Search grounding. Fallback: Gemini plain, then Perplexity.
    Results are cached for 60 minutes to avoid redundant API calls across pipelines.
    Respects ctx.scout_hours_back (default 24, burst mode uses 3 for freshness).

    If ctx.event_title is already set (pinned mode via --event), skip trend-searching
    entirely and use Gemini to generate only the missing fields (search query + chaos angle)."""

    hours_back = getattr(ctx, "scout_hours_back", 24) or 24

    # --- Pinned event mode: user chose the event, skip trend-searching ---
    if ctx.event_title:
        log.info(f"  [Video Scout] Pinned event: {ctx.event_title!r}")
        _fill_pinned_event_fields(ctx, config)
        ctx.scout_source = "pinned"
        log.info(f"  Event: {ctx.event_title}")
        log.info(f"  Description: {ctx.event_description}")
        log.info(f"  Platform: {ctx.video_platform}")
        log.info(f"  Chaos angle: {ctx.chaos_angle}")
        log.debug(f"  Search query: {ctx.video_search_query}")
        return ctx

    # Skip cache in burst mode (short time window = need fresh results)
    cached = _load_trend_cache() if hours_back >= 24 else None
    excluded_events = getattr(ctx, "excluded_events", []) or []
    if cached:
        # Don't reuse cached event if we already made a video for it
        if is_already_processed(cached.get("event_title", "")):
            log.info("  [Video Scout] Cached event already processed, fetching fresh trend")
            cached = None
        # Don't reuse cached event if we already tried and failed to download it
        elif excluded_events and any(
            is_fuzzy_match(cached.get("event_title", ""), ex) for ex in excluded_events
        ):
            log.info("  [Video Scout] Cached event was undownloadable, fetching fresh trend")
            cached = None
        else:
            log.info("  [Video Scout] Using cached trend (< 1hr old)")
            ctx.event_title = cached["event_title"]
            ctx.event_description = cached["event_description"]
            ctx.video_platform = cached["video_platform"]
            ctx.video_search_query = cached["video_search_query"]
            ctx.chaos_angle = cached["chaos_angle"]
            ctx.scout_source = "cache"
            log.info(f"  Event: {ctx.event_title}")
            log.info(f"  Description: {ctx.event_description}")
            log.info(f"  Platform: {ctx.video_platform}")
            log.info(f"  Chaos angle: {ctx.chaos_angle}")
            return ctx

    excluded = list(get_all_processed())
    excluded.extend(getattr(ctx, "excluded_events", []) or [])
    excluded = [e for e in excluded if e]
    exclude_str = ", ".join(excluded) if excluded else "none"
    log.debug(f"Excluded events: {exclude_str}")

    prompt = (
        f"Search for the single most notable real-world event from the last {hours_back} hours that is being "
        "heavily covered by mainstream/traditional media and has strong visual content. "
        "CRITICAL: The event itself (the thing that happened — the press conference, game, launch, incident) "
        f"must have OCCURRED within the last {hours_back} hours. Do NOT pick stories where the only recent "
        "angle is that an old video, clip, or past event is being discussed or 'resurfacing'; prefer events "
        f"where something actually happened in the last {hours_back} hours (e.g. a live moment, a new announcement, "
        "a game that just finished, a speech that just happened). "
        "Consider events across ALL major categories:\n"
        "- POLITICS & GOVERNMENT: press conferences, congressional hearings, diplomatic events, "
        "election moments, policy announcements, political gaffes caught on camera\n"
        "- ENTERTAINMENT: award shows, live TV moments, red carpet appearances, music performances, "
        "celebrity incidents, movie premieres, festival highlights\n"
        "- SPORTS: championship games, record-breaking moments, dramatic plays, press conferences, "
        "athlete reactions, rivalry matchups\n"
        "- TECH & SCIENCE: product launches, space missions, scientific breakthroughs, tech demos, "
        "AI announcements, robotics showcases\n"
        "- BUSINESS & ECONOMY: CEO statements, market events, company announcements, "
        "corporate drama, product recalls\n"
        "- CULTURE & VIRAL: art exhibitions, fashion shows, food trends, internet culture events, "
        "museum openings, public stunts\n"
        "- WEATHER & NATURE: extreme weather caught on camera, wildlife events, natural phenomena\n\n"
        "Pick the event that is MOST video-worthy — dramatic, visual, funny, or spectacular. "
        "The event MUST have video footage available (news clips, broadcast highlights, official uploads). "
        "Do NOT pick events that originated as social media content (TikTok trends, Instagram influencer "
        "drama, YouTube creator beef, Reddit threads). The event should have happened in the physical "
        "world and been reported by news outlets or covered in broadcast media. "
        f"{OFF_LIMITS_PROMPT} "
        f"Exclude these already-covered events: [{exclude_str}]. "
        "Return a JSON object with exactly these fields:\n"
        '- "event_title": a short catchy title for the event (5-8 words)\n'
        '- "event_description": 2-3 sentence summary of what happened at the event\n'
        '- "video_platform": where the best video clip can be found (youtube, news_site, broadcast)\n'
        '- "video_search_query": a specific YouTube/Google search query to find a video clip of this '
        "event (include the event name, key people involved, and the date or venue for precision)\n"
        '- "chaos_angle": a funny, absurd, or dramatic spin on the event for comedic narration (1 sentence, max 20 words — punchy and visual, not a paragraph)\n\n'
        "Return ONLY valid JSON. No markdown, no explanation."
    )
    log.debug(f"Prompt length: {len(prompt)} chars")

    # Cascade: Gemini grounded → Gemini plain → Perplexity
    sources = [
        ("gemini-grounded", _call_gemini_grounded),
        ("gemini", _call_gemini_plain),
    ]
    if config.get("PERPLEXITY_API_KEY"):
        sources.append(("perplexity", _call_perplexity))

    log.debug(f"Source cascade: {[s[0] for s in sources]}")

    result = None
    for source_name, source_fn in sources:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with StepTimer(log, f"API call: {source_name} (attempt {attempt})") as t:
                    result = source_fn(prompt, config)

                # Reject tragedies / off-limits topics
                if _is_off_limits(result):
                    log.info(f"  [Video Scout] Rejected off-limits topic from {source_name}: {result.get('event_title', '?')}")
                    result = None
                    break  # try next source

                # Reject duplicate events (fuzzy match catches rephrased titles)
                if is_already_processed(result.get("event_title", "")):
                    log.info(f"  [Video Scout] Rejected duplicate event from {source_name}: {result.get('event_title', '?')}")
                    result = None
                    break  # try next source

                # Reject events we already tried and failed to download
                excluded = getattr(ctx, "excluded_events", []) or []
                if any(
                    is_fuzzy_match(result.get("event_title", ""), ex)
                    for ex in excluded
                ):
                    log.info(f"  [Video Scout] Rejected previously undownloadable event from {source_name}: {result.get('event_title', '?')}")
                    result = None
                    break  # try next source

                ctx.scout_source = source_name
                log.info(f"  [Video Scout] Source: {source_name}")
                log.debug(f"  API response parsed successfully in {t.elapsed:.2f}s")
                log.debug(f"  Raw result: {json.dumps(result, ensure_ascii=False)}")
                break
            except Exception as e:
                err_str = str(e)
                is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                if is_rate_limit and attempt < MAX_RETRIES:
                    wait = RETRY_DELAY * attempt
                    log.info(f"  [Video Scout] {source_name} rate limited, retrying in {wait}s (attempt {attempt}/{MAX_RETRIES})...")
                    log.debug(f"  Rate limit error detail: {err_str}")
                    time.sleep(wait)
                else:
                    log.info(f"  [Video Scout] {source_name} failed: {e}")
                    log.debug(f"  Full error: {err_str}")
                    break
        if result is not None:
            break

    if result is None:
        log.error("All trend sources exhausted")
        raise RuntimeError("All trend sources failed.")

    ctx.event_title = result["event_title"]
    ctx.event_description = result["event_description"]
    ctx.video_platform = result["video_platform"]
    ctx.video_search_query = result["video_search_query"]
    ctx.chaos_angle = result["chaos_angle"]

    # Cache for other pipelines to reuse (skip in burst mode)
    if hours_back >= 24:
        _save_trend_cache(result)
        log.debug("  Trend cached for 60 minutes")


    log.info(f"  Event: {ctx.event_title}")
    log.info(f"  Description: {ctx.event_description}")
    log.info(f"  Platform: {ctx.video_platform}")
    log.info(f"  Chaos angle: {ctx.chaos_angle}")
    log.debug(f"  Search query: {ctx.video_search_query}")

    return ctx


def find_trending_options(config: dict, n: int = 3, excluded_events: list | None = None) -> list[dict]:
    """Return N trending event candidates for the user to choose from.

    Uses Gemini with Google Search grounding (falls back to plain).
    Each item in the returned list has the same fields as a normal scout result:
    event_title, event_description, video_platform, video_search_query, chaos_angle.
    """
    excluded = list(get_all_processed())
    excluded.extend(excluded_events or [])
    excluded = [e for e in excluded if e]
    exclude_str = ", ".join(excluded) if excluded else "none"

    prompt = (
        f"Search for the {n} most notable real-world events from the last 24 hours that are being "
        "heavily covered by mainstream/traditional media and have strong visual content. "
        "Each event must have ACTUALLY OCCURRED in the last 24 hours — not a resurfacing story. "
        "Pick events from diverse categories (entertainment, sports, politics, tech, etc.) so the "
        "options feel varied. "
        "The events MUST have video footage available (news clips, broadcast highlights, official uploads). "
        "Do NOT pick events that originated as social media content. "
        f"{OFF_LIMITS_PROMPT} "
        f"Exclude these already-covered events: [{exclude_str}]. "
        f"Return a JSON array of exactly {n} objects. Each object must have these fields:\n"
        '- "event_title": short catchy title (5-8 words)\n'
        '- "event_description": 2-3 sentence summary\n'
        '- "video_platform": youtube, news_site, or broadcast\n'
        '- "video_search_query": precise YouTube/Google search query\n'
        '- "chaos_angle": a funny/absurd comedic spin for a troll character (1 sentence, max 20 words)\n\n'
        "Return ONLY a valid JSON array. No markdown, no explanation."
    )

    client = genai.Client(api_key=config["GEMINI_API_KEY"])

    # Try grounded first, fall back to plain
    for use_grounding in (True, False):
        try:
            cfg = types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())] if use_grounding else [],
                temperature=0.4,
            )
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=cfg,
            )
            raw = response.text
            # parse_llm_json expects a dict; handle array manually
            import json as _json
            # Strip markdown fences if present
            text = raw.strip()
            if text.startswith("```"):
                text = "\n".join(text.split("\n")[1:])
                text = text.rsplit("```", 1)[0].strip()
            options = _json.loads(text)
            if isinstance(options, list) and len(options) >= 1:
                return options[:n]
        except Exception as e:
            log.debug(f"  find_trending_options ({'grounded' if use_grounding else 'plain'}) failed: {e}")
            if not use_grounding:
                raise RuntimeError(f"Could not fetch trending options: {e}") from e

    raise RuntimeError("Could not fetch trending options.")


def _fill_pinned_event_fields(ctx: PipelineContext, config: dict) -> None:
    """Use Gemini (plain) to generate missing scout fields for a pinned event.

    Populates: video_search_query, chaos_angle, video_platform.
    Also fills event_description if the user did not provide one.
    Mutates ctx in-place."""
    has_description = bool(ctx.event_description)

    prompt = (
        f"You are preparing a video production brief for a comedic animated character.\n\n"
        f"Event title: {ctx.event_title!r}\n"
        + (f"Event description: {ctx.event_description!r}\n\n" if has_description else "\n")
        + "Generate the following fields as a JSON object:\n"
        + '- "event_description": 2-3 sentence factual summary of what this event is / what happened '
        + "(skip this if you already have a description — see above)\n"
        + '- "video_platform": where the best video clip can be found — one of: youtube, news_site, broadcast\n'
        + '- "video_search_query": a precise YouTube/Google search query to find a video clip of this event '
        + "(include event name, key people, approximate date or venue for precision)\n"
        + '- "chaos_angle": a funny, absurd, or dramatic comedic spin on this event for a troll character '
        + "(1 sentence, max 20 words — punchy and visual, keep it light and non-mean-spirited)\n\n"
        + f"{OFF_LIMITS_PROMPT}\n\n"
        + "Return ONLY valid JSON. No markdown, no explanation."
    )

    client = genai.Client(api_key=config["GEMINI_API_KEY"])
    log.debug("Calling Gemini plain to fill pinned event fields")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.4),
    )

    required = ["video_platform", "video_search_query", "chaos_angle"]
    if not has_description:
        required.append("event_description")

    result = parse_llm_json(response.text, required)

    if not has_description:
        ctx.event_description = result.get("event_description", "")
    ctx.video_platform = result.get("video_platform", "youtube")
    ctx.video_search_query = result.get("video_search_query", ctx.event_title)
    ctx.chaos_angle = result.get("chaos_angle", "")


def _call_gemini_grounded(prompt: str, config: dict) -> dict:
    """Use Gemini 2.0 Flash with Google Search grounding for real-time trend data."""
    client = genai.Client(api_key=config["GEMINI_API_KEY"])

    log.debug("Calling Gemini 2.0 Flash with Google Search grounding")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.3,
        ),
    )

    text = response.text
    log.debug(f"Gemini grounded raw response ({len(text)} chars): {text[:500]}")
    return parse_llm_json(text, REQUIRED_FIELDS)


def _call_gemini_plain(prompt: str, config: dict) -> dict:
    """Use Gemini 2.0 Flash without grounding — relies on training data."""
    client = genai.Client(api_key=config["GEMINI_API_KEY"])

    log.debug("Calling Gemini 2.0 Flash (plain, no grounding)")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.3,
        ),
    )

    text = response.text
    log.debug(f"Gemini plain raw response ({len(text)} chars): {text[:500]}")
    return parse_llm_json(text, REQUIRED_FIELDS)


def _call_perplexity(prompt: str, config: dict) -> dict:
    log.debug("Calling Perplexity (sonar)")
    resp = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers={
            "Authorization": f"Bearer {config['PERPLEXITY_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={
            "model": "sonar",
            "messages": [
                {"role": "user", "content": prompt},
            ],
        },
        timeout=30,
    )
    log.debug(f"Perplexity response status: {resp.status_code}")
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    log.debug(f"Perplexity raw response ({len(text)} chars): {text[:500]}")
    return parse_llm_json(text, REQUIRED_FIELDS)


def _is_off_limits(result: dict) -> bool:
    """Check if a trend result touches an off-limits topic (tragedies, violence, etc.)."""
    text_to_check = (
        f"{result.get('event_title', '')} {result.get('event_description', '')} "
        f"{result.get('chaos_angle', '')}"
    ).lower()
    for topic in OFF_LIMITS_TOPICS:
        if topic in text_to_check:
            return True
    return False


# Note: _parse_json removed - now using shared utils.json_utils.parse_llm_json

REQUIRED_FIELDS = ["event_title", "event_description", "video_platform",
                   "video_search_query", "chaos_angle"]
