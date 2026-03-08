"""Video pipeline: trending event -> animated Arbi video -> saved locally (+ optional YouTube upload).

Agents: Video Scout -> Video Finder -> Video Analyzer -> Character Dresser ->
Animation Director -> Video Producer -> Troll Sound Designer -> Subtitle Burner ->
Outro Stitcher -> YouTube Uploader (optional)
"""

import os
from datetime import datetime

from context.video import VideoContext
from agents.video_scout import find_trending_video
from agents.video_finder import find_and_download_video
from agents.video_analyzer import analyze_video
from agents.cartoonist import dress_character
from agents.script_writer import write_animation_direction
from agents.video_producer import produce_video
from agents.voice_actor import generate_troll_sounds
from agents.subtitle_burner import burn_subtitles
from agents.outro_stitcher import stitch_outro
from agents.youtube_uploader import upload_to_youtube
from logger import get_logger
from orchestrator import run_pipeline, PipelineError

log = get_logger("pipelines.video")


AGENTS = [
    ("Video Scout", find_trending_video),
    ("Video Finder", find_and_download_video),
    ("Video Analyzer", analyze_video),
    ("Character Dresser", dress_character),
    ("Animation Director", write_animation_direction),
    ("Video Producer", produce_video),
    ("Troll Sound Designer", generate_troll_sounds),
    ("Subtitle Burner", burn_subtitles),
    ("Outro Stitcher", stitch_outro),
    ("YouTube Uploader", upload_to_youtube),
]


def make_context(run_id, started_at, config, excluded_events=None, event=None, description=None, **kwargs):
    ctx = VideoContext(
        run_id=run_id,
        started_at=started_at,
        pipeline_name="video",
        arbi_image_path=os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "artifacts", "Character - New.png"
        ),
    )
    if excluded_events:
        ctx.excluded_events = list(excluded_events)
    if event:
        ctx.event_title = event.strip()
    if description:
        ctx.event_description = description.strip()
    return ctx


def build_summary(ctx, agent_timings, total_time):
    return {
        "run_id": ctx.run_id,
        "pipeline": "video",
        "started_at": ctx.started_at,
        "finished_at": datetime.now().isoformat(),
        "total_time_s": round(total_time, 2),
        "event_title": ctx.event_title,
        "event_description": ctx.event_description,
        "video_platform": ctx.video_platform,
        "chaos_angle": ctx.chaos_angle,
        "scout_source": ctx.scout_source,
        "source_video_url": ctx.source_video_url,
        "character_gender": ctx.character_gender,
        "final_video_path": ctx.final_video_path or ctx.subtitled_video_path or ctx.video_local_path,
        "animation_direction_word_count": len(ctx.animation_direction.split()) if ctx.animation_direction else 0,
        "youtube_video_url": ctx.youtube_video_url,
        "youtube_video_id": ctx.youtube_video_id,
        "agents": agent_timings,
        "errors": ctx.errors,
    }


MAX_SUBJECT_SWITCHES = 3  # Max times to switch subject when video is undownloadable


def run(event=None, description=None):
    excluded_events = []
    for attempt in range(MAX_SUBJECT_SWITCHES):
        try:
            return run_pipeline(
                "Video Pipeline",
                AGENTS,
                make_context,
                build_summary,
                excluded_events=excluded_events if attempt > 0 else None,
                event=event,
                description=description,
            )
        except PipelineError as e:
            if e.agent_name != "Video Finder":
                raise
            # Check if it's a download failure (undownloadable video)
            err = str(e.error).lower()
            if "could not download" not in err and "no videos found" not in err:
                raise
            if e.ctx and e.ctx.event_title:
                excluded_events.append(e.ctx.event_title)
            if attempt >= MAX_SUBJECT_SWITCHES - 1:
                raise
            # Retry with new subject (only auto-scout retries; pinned events don't switch)
            failed_title = e.ctx.event_title if e.ctx else "?"
            if event:
                log.info(
                    f"  [Pinned Event] Video undownloadable for '{failed_title}'. "
                    "Pinned events do not switch subjects — aborting."
                )
                raise
            log.info(
                f"  [Subject Switch] Video undownloadable for '{failed_title}', "
                f"switching to different event (attempt {attempt + 2}/{MAX_SUBJECT_SWITCHES})"
            )
