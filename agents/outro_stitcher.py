import os

from context import PipelineContext
from logger import get_logger, StepTimer
from utils.ffmpeg_utils import run_ffmpeg, get_video_metadata

log = get_logger("outro_stitcher")

OUTRO_FILENAME = "outro.mp4"


# Note: _get_video_dimensions removed - now using utils.ffmpeg_utils.get_video_metadata


def stitch_outro(ctx: PipelineContext, config: dict) -> PipelineContext:
    """Append the pre-rendered Arbi outro clip to the end of the final video."""

    video_path = ctx.subtitled_video_path or ctx.video_local_path
    if not video_path or not os.path.exists(video_path):
        log.error("  [Outro Stitcher] No video file found, skipping outro")
        ctx.final_video_path = video_path
        return ctx

    artifacts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "artifacts")
    outro_path = os.path.join(artifacts_dir, OUTRO_FILENAME)

    if not os.path.exists(outro_path):
        log.warning(f"  [Outro Stitcher] Outro not found at {outro_path}, skipping")
        ctx.final_video_path = video_path
        return ctx

    output_path = os.path.join(
        artifacts_dir, "videos", f"{ctx.run_id}_final_with_outro.mp4"
    )

    log.info("  [Outro Stitcher] Appending outro to video...")

    with StepTimer(log, "Stitch outro") as t:
        # Re-encode both inputs to a consistent format before concatenating.
        # The main video has audio; the outro is silent. We add a silent audio
        # track to the outro so the concat filter can merge them cleanly.
        try:
            # Probe the main video to match its dimensions
            metadata = get_video_metadata(video_path)
            w, h = metadata["width"], metadata["height"]
            log.info(f"  [Outro Stitcher] Main video is {w}x{h}, scaling outro to match")

            run_ffmpeg(
                [
                    "ffmpeg", "-y",
                    "-i", video_path,
                    "-i", outro_path,
                    "-filter_complex",
                    (
                        # Normalize main video
                        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v0];"
                        # Normalize outro + add silent audio track
                        f"[1:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v1];"
                        "anullsrc=channel_layout=stereo:sample_rate=44100[silence];"
                        "[silence]atrim=duration=3[a1];"
                        # Concatenate video+audio streams
                        "[v0][0:a][v1][a1]concat=n=2:v=1:a=1[vout][aout]"
                    ),
                    "-map", "[vout]",
                    "-map", "[aout]",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-crf", "10",
                    "-preset", "medium",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-movflags", "+faststart",
                    output_path,
                ],
                timeout=120,
                description="Stitch outro to video"
            )

        except RuntimeError as e:
            log.error(f"  [Outro Stitcher] Failed to stitch outro: {e}")
            ctx.final_video_path = video_path
            return ctx

    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    log.info(f"  [Outro Stitcher] Video with outro: {output_path} ({file_size_mb:.1f} MB)")
    log.debug(f"  Stitch took {t.elapsed:.2f}s")

    ctx.final_video_path = output_path
    return ctx
