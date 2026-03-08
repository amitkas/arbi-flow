import os
import shutil
import sys

import requests
import yt_dlp

from context import PipelineContext
from logger import get_logger, StepTimer
from utils.ffmpeg_utils import extract_first_frame, trim_video

log = get_logger("video_finder")

MAX_VIDEO_DURATION = 120  # seconds — prefer videos under 2 minutes
TRIM_MAX_DURATION = 600   # seconds — will download and trim videos up to 10 minutes


def _detect_js_runtime() -> dict:
    """Auto-detect an available JS runtime for yt-dlp (required for YouTube)."""
    for runtime in ("deno", "node", "bun"):
        if shutil.which(runtime):
            log.debug(f"JS runtime detected: {runtime}")
            return {runtime: {}}
    log.warning("No JS runtime found (deno/node/bun) — YouTube downloads may fail")
    return {}


def find_and_download_video(ctx: PipelineContext, config: dict) -> PipelineContext:
    """Search for the viral video using Serper video search, download with yt-dlp,
    and extract the first frame."""

    log.debug(f"Search query: {ctx.video_search_query}")

    # Step 1: Search for the video URL using Serper
    with StepTimer(log, "Serper video search"):
        videos = _search_videos(ctx.video_search_query, config)
    log.debug(f"Video search returned {len(videos)} results")

    if not videos:
        log.info("  [Video Finder] No results for primary query, trying event title...")
        with StepTimer(log, "Serper video search (fallback)"):
            videos = _search_videos(ctx.event_title, config)
        log.debug(f"Fallback search returned {len(videos)} results")

    if not videos:
        raise RuntimeError("No videos found for the trending event.")

    for i, vid in enumerate(videos[:10]):
        log.debug(f"  Candidate {i+1}: {vid.get('link', 'N/A')[:100]}")

    # Step 2: Try downloading videos until one works
    artifacts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "artifacts", "videos")
    os.makedirs(artifacts_dir, exist_ok=True)

    youtube_152_blocked = False

    for i, vid in enumerate(videos[:10]):
        url = vid.get("link", "")
        if not url:
            continue

        # Once YouTube returns error 152 (blanket geo/DRM restriction), skip all
        # remaining YouTube candidates and go straight to non-YouTube sources.
        if youtube_152_blocked and _is_youtube_url(url):
            log.debug(f"  [Video Finder] Skipping YouTube candidate (152 blocked): {url[:80]}")
            continue

        try:
            with StepTimer(log, f"Download video {i+1} via yt-dlp"):
                video_path = _download_video(url, ctx.run_id, artifacts_dir, config)

            ctx.source_video_url = url
            ctx.source_video_path = video_path
            log.info(f"  [Video Finder] Downloaded video {i+1}: {url[:80]}")
            log.debug(f"  Saved to: {video_path}")
            break
        except Exception as e:
            err_str = str(e)
            if _is_youtube_url(url) and "152" in err_str and not youtube_152_blocked:
                youtube_152_blocked = True
                log.info("  [Video Finder] YouTube error 152 detected — skipping remaining YouTube candidates, trying other sources first")
            log.info(f"  [Video Finder] Failed to download video {i+1}: {e}")
            continue
    else:
        raise RuntimeError("Could not download any of the found videos.")

    # Step 3: Extract first frame
    images_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "artifacts", "images")
    os.makedirs(images_dir, exist_ok=True)

    first_frame_path = os.path.join(images_dir, f"{ctx.run_id}_first_frame.jpg")

    with StepTimer(log, "Extract first frame via ffmpeg"):
        extract_first_frame(ctx.source_video_path, first_frame_path)

    ctx.first_frame_path = first_frame_path
    file_size_kb = os.path.getsize(first_frame_path) / 1024
    log.info(f"  [Video Finder] First frame saved: {first_frame_path} ({file_size_kb:.1f} KB)")

    return ctx


def _search_videos(query: str, config: dict) -> list[dict]:
    """Search for videos using Serper video search API."""
    log.debug(f"Serper API call — query: {query}")
    resp = requests.post(
        "https://google.serper.dev/videos",
        headers={
            "X-API-KEY": config["SERPER_API_KEY"],
            "Content-Type": "application/json",
        },
        json={"q": query, "num": 10},
        timeout=15,
    )
    log.debug(f"Serper response status: {resp.status_code}")
    resp.raise_for_status()
    results = resp.json().get("videos", [])
    log.debug(f"Serper returned {len(results)} videos")
    return results


def _is_youtube_url(url: str) -> bool:
    """Return True if URL is YouTube or YouTube Shorts."""
    return "youtube.com" in url or "youtu.be" in url


def _download_video(url: str, run_id: str, output_dir: str, config: dict | None = None) -> str:
    """Download a video using yt-dlp Python library. Returns the path to the downloaded file.
    Videos under MAX_VIDEO_DURATION are downloaded as-is.
    Videos between MAX_VIDEO_DURATION and TRIM_MAX_DURATION are downloaded and trimmed to
    the first MAX_VIDEO_DURATION seconds with ffmpeg."""
    output_template = os.path.join(output_dir, f"{run_id}_source.%(ext)s")
    final_path = os.path.join(output_dir, f"{run_id}_source.mp4")

    config = config or {}
    cookies_from_browser = config.get("YT_DLP_COOKIES_FROM_BROWSER", "").strip()
    cookies_file = config.get("YT_DLP_COOKIES", "").strip()
    is_youtube = _is_youtube_url(url)
    js_runtime = _detect_js_runtime()

    def _base_opts(extractor_args: dict | None = None) -> dict:
        opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
        if js_runtime:
            opts["js_runtimes"] = js_runtime
        if cookies_file and os.path.isfile(cookies_file):
            opts["cookiefile"] = cookies_file
        elif cookies_from_browser:
            opts["cookiesfrombrowser"] = (cookies_from_browser.split(",")[0].strip(),)
        elif is_youtube:
            opts["cookiesfrombrowser"] = ("chrome",)
        if extractor_args:
            opts["extractor_args"] = extractor_args
        return opts

    # Each strategy pairs a player client with a compatible format string.
    # ios/android bypass "Watch on YouTube" (152-18) restrictions.
    # tv_simply and web_embedded don't require PO tokens or cookies.
    youtube_strategies = [
        {
            "name": "ios",
            "extractor_args": {"youtube": {"player_client": ["ios"]}},
            "format": "best[height<=720]/best",
        },
        {
            "name": "android",
            "extractor_args": {"youtube": {"player_client": ["android"]}},
            "format": "best[height<=720]/best",
        },
        {
            "name": "default",
            "extractor_args": None,
            "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        },
        {
            "name": "tv_simply",
            "extractor_args": {"youtube": {"player_client": ["tv_simply"]}},
            "format": "best[height<=720]/best",
        },
        {
            "name": "web_embedded",
            "extractor_args": {"youtube": {"player_client": ["web_embedded"]}},
            "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        },
    ]

    strategies = youtube_strategies if is_youtube else [youtube_strategies[0]]
    needs_trim = False
    last_error = None

    for strategy in strategies:
        name = strategy["name"]
        extractor_args = strategy["extractor_args"]
        fmt = strategy["format"]

        log.debug(f"yt-dlp strategy '{name}' — probing: {url}")
        probe_opts = _base_opts(extractor_args)

        try:
            with yt_dlp.YoutubeDL(probe_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    raise RuntimeError("yt-dlp returned no info")

                duration = info.get("duration") or 0
                needs_trim = duration > MAX_VIDEO_DURATION
                log.debug(f"  Video duration: {duration}s (max: {MAX_VIDEO_DURATION}s, trim_max: {TRIM_MAX_DURATION}s)")

                if duration > TRIM_MAX_DURATION:
                    raise RuntimeError(f"Video too long ({duration}s > {TRIM_MAX_DURATION}s), skipping")
                elif needs_trim:
                    log.info(f"  [Video Finder] Video is {duration}s — will download and trim to {MAX_VIDEO_DURATION}s")
        except Exception as e:
            last_error = e
            log.info(f"  [Video Finder] Probe failed ({name}): {e}")
            continue

        ydl_opts = {
            "outtmpl": output_template,
            "noplaylist": True,
            "max_filesize": 100 * 1024 * 1024,
            "format": fmt,
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "extractor_retries": 3,
            **_base_opts(extractor_args),
        }

        log.debug(f"yt-dlp strategy '{name}' — downloading: {url}")

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info is None:
                    raise RuntimeError("yt-dlp returned no info")

                downloaded = ydl.prepare_filename(info)
                log.debug(f"  yt-dlp prepared filename: {downloaded}")

                if os.path.exists(final_path):
                    actual_path = final_path
                elif os.path.exists(downloaded):
                    actual_path = downloaded
                else:
                    mp4_path = os.path.splitext(downloaded)[0] + ".mp4"
                    if os.path.exists(mp4_path):
                        actual_path = mp4_path
                    else:
                        raise RuntimeError(f"yt-dlp did not produce output file. Expected: {final_path}")

            if needs_trim:
                actual_path = _trim_video(actual_path, MAX_VIDEO_DURATION, run_id, output_dir)

            file_size_mb = os.path.getsize(actual_path) / (1024 * 1024)
            log.info(f"  [Video Finder] Downloaded via '{name}': {actual_path} ({file_size_mb:.1f} MB)")
            return actual_path

        except Exception as e:
            last_error = e
            log.warning(f"  [Video Finder] Download failed ({name}): {e}")
            continue

    raise RuntimeError(f"All download strategies failed: {last_error}") from last_error


def _trim_video(video_path: str, max_seconds: int, run_id: str, output_dir: str) -> str:
    """Trim video to the first max_seconds using ffmpeg. Returns the trimmed file path."""
    trimmed_path = os.path.join(output_dir, f"{run_id}_source.mp4")

    # If source and target are the same path, use a temp file
    if os.path.abspath(video_path) == os.path.abspath(trimmed_path):
        temp_path = os.path.join(output_dir, f"{run_id}_source_untrimmed.mp4")
        os.rename(video_path, temp_path)
        video_path = temp_path

    try:
        with StepTimer(log, f"Trim video to {max_seconds}s via ffmpeg"):
            trim_video(video_path, trimmed_path, max_seconds, codec_copy=True)
    finally:
        # Clean up untrimmed file
        if os.path.exists(video_path) and video_path != trimmed_path:
            os.remove(video_path)

    log.info(f"  [Video Finder] Trimmed to {max_seconds}s: {trimmed_path}")
    return trimmed_path
