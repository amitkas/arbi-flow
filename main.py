"""Arbi Flow — produce a trending news video.

Usage:
    python3 main.py                    # Run full video pipeline
    python3 main.py --resume <run_id>  # Resume failed run from last step
    python3 main.py --upload <run_id>  # Upload existing video to YouTube
"""

import argparse
import ast
import json
import os
import re
import shutil
import sys

from orchestrator import PipelineError, cleanup_run_artifacts
from config import load_config
from context.video import VideoContext
from logger import setup_logging, get_logger
from agents.voice_actor import generate_troll_sounds
from agents.subtitle_burner import burn_subtitles
from agents.outro_stitcher import stitch_outro
from agents.youtube_uploader import upload_to_youtube


def run_pipeline(event: str | None = None, description: str | None = None):
    """Run the full video pipeline."""
    from pipelines.video import run as run_video
    try:
        run_video(event=event, description=description)
    except PipelineError as e:
        print(f"\n[FAIL] {e}")
        sys.exit(1)


def pick_and_run():
    """Scout 3 trending events, let the user pick one, then run the pipeline."""
    from agents.video_scout import find_trending_options

    config = load_config()

    print("=" * 60)
    print("  ARBI FLOW — Pick Your Event")
    print("=" * 60)
    print("\n  Scouting trending events...\n")

    try:
        options = find_trending_options(config, n=3)
    except Exception as e:
        print(f"[FAIL] Could not fetch trending options: {e}")
        sys.exit(1)

    print("  Pick an event for Arbi to re-enact:\n")
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt['event_title']}")
        print(f"     {opt['event_description']}")
        print(f"     Arbi angle: {opt['chaos_angle']}")
        print()

    while True:
        try:
            raw = input(f"  Your choice (1-{len(options)}): ").strip()
            choice = int(raw)
            if 1 <= choice <= len(options):
                break
            print(f"  Please enter a number between 1 and {len(options)}.")
        except (ValueError, EOFError):
            print(f"  Please enter a number between 1 and {len(options)}.")

    chosen = options[choice - 1]
    print(f"\n  Selected: {chosen['event_title']}\n")

    run_pipeline(event=chosen["event_title"], description=chosen["event_description"])


def _parse_keywords_from_log(log_path: str) -> list[str]:
    """Extract video_keywords from Video Analyzer log line."""
    if not os.path.exists(log_path):
        return []
    with open(log_path) as f:
        for line in f:
            if "Keywords:" in line and "[" in line:
                # Extract the list part: Keywords: ['a', 'b', ...]
                match = re.search(r"Keywords:\s*(\[.+\])", line)
                if match:
                    try:
                        return ast.literal_eval(match.group(1).strip())
                    except (ValueError, SyntaxError):
                        pass
    return []


def resume_run(run_id: str):
    """Resume a failed run from the last successful step.

    Runs: Troll Sound Designer → Subtitle Burner → Outro Stitcher
    """
    project_root = os.path.dirname(os.path.abspath(__file__))
    summary_path = os.path.join(project_root, "logs", f"{run_id}_summary.json")
    log_path = os.path.join(project_root, "logs", f"{run_id}.log")
    video_path = os.path.join(project_root, "artifacts", "videos", f"{run_id}_final.mp4")

    if not os.path.exists(summary_path):
        print(f"[FAIL] No summary found for run {run_id}")
        print(f"       Expected: {summary_path}")
        sys.exit(1)

    if not os.path.exists(video_path):
        print(f"[FAIL] No video found at {video_path}")
        print("       The raw Arbi video (before troll audio) is required.")
        sys.exit(1)

    with open(summary_path) as f:
        summary = json.load(f)

    keywords = _parse_keywords_from_log(log_path)
    if not keywords:
        print("  [Note] Could not parse keywords from log, using empty list")

    config = load_config()
    setup_logging(run_id)

    ctx = VideoContext(
        run_id=run_id,
        started_at=summary.get("started_at", ""),
        pipeline_name="video",
        event_title=summary.get("event_title", ""),
        event_description=summary.get("event_description", ""),
        video_local_path=video_path,
        video_keywords=keywords,
        arbi_image_path=os.path.join(project_root, "artifacts", "Character - New.png"),
    )

    log = get_logger("finalize")

    print("=" * 60)
    print(f"  FINALIZE RUN — {run_id}")
    print("=" * 60)
    print(f"  Event: {ctx.event_title}")
    print(f"  Video: {video_path}")
    print("=" * 60)

    agents = [
        ("Troll Sound Designer", generate_troll_sounds),
        ("Subtitle Burner", burn_subtitles),
        ("Outro Stitcher", stitch_outro),
    ]

    for name, agent_fn in agents:
        print(f"\n>> {name}")
        try:
            ctx = agent_fn(ctx, config)
            print(f"[OK] {name} completed")
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
            sys.exit(1)

    # Copy to output/
    output_dir = os.path.join(project_root, "output")
    os.makedirs(output_dir, exist_ok=True)
    final_path = ctx.final_video_path or ctx.subtitled_video_path or ctx.video_local_path
    if final_path and os.path.exists(final_path):
        ext = os.path.splitext(final_path)[1]
        title = ctx.event_title or run_id
        clean_title = re.sub(r"[^\w\s-]", "", title).strip()
        clean_title = re.sub(r"[\s-]+", "_", clean_title)
        dest = os.path.join(output_dir, f"{clean_title}_{run_id}{ext}")
        shutil.copy2(final_path, dest)
        cleanup_run_artifacts(run_id)
        print(f"\n{'=' * 60}")
        print("  FINALIZED")
        print(f"{'=' * 60}")
        print(f"  Output: {dest}")
        print(f"  Cleanup: artifacts for {run_id} removed")
        print(f"{'=' * 60}")
    else:
        print("[FAIL] No final video produced")
        sys.exit(1)


def _find_latest_summary(logs_dir: str) -> str | None:
    """Return path to most recent *_summary.json in logs/, or None."""
    if not os.path.isdir(logs_dir):
        return None

    candidates = [
        os.path.join(logs_dir, f)
        for f in os.listdir(logs_dir)
        if f.endswith("_summary.json")
    ]
    if not candidates:
        return None

    return max(candidates, key=os.path.getmtime)


def _find_output_video_for_run(output_dir: str, run_id: str) -> str | None:
    """Find the output MP4 for a given run_id.

    Orchestrator names output files as: {Clean_Event_Title}_{run_id}.mp4
    """
    if not os.path.isdir(output_dir):
        return None

    for name in os.listdir(output_dir):
        if not name.lower().endswith(".mp4"):
            continue

        # Match final "_{run_id}.mp4" segment
        stem = name.rsplit(".", 1)[0]
        if stem.rsplit("_", 1)[-1] == run_id:
            return os.path.join(output_dir, name)

    return None


def upload_video(run_id: str | None = None):
    """Upload a video to YouTube.

    Args:
        run_id: Optional specific run ID. If None, uploads the latest run.
    """
    project_root = os.path.dirname(os.path.abspath(__file__))
    logs_dir = os.path.join(project_root, "logs")
    output_dir = os.path.join(project_root, "output")

    # Find the run to upload
    if run_id:
        summary_path = os.path.join(logs_dir, f"{run_id}_summary.json")
        if not os.path.exists(summary_path):
            print(f"❌ No summary found for run {run_id}")
            sys.exit(1)
    else:
        summary_path = _find_latest_summary(logs_dir)
        if not summary_path:
            print("❌ No run summaries found in logs/. Have you run the pipeline yet?")
            sys.exit(1)

    with open(summary_path, "r") as f:
        summary = json.load(f)

    run_id = summary.get("run_id", "")
    event_title = summary.get("event_title", "")
    event_description = summary.get("event_description", "")
    youtube_url = summary.get("youtube_video_url", "") or ""

    print(f"Using run: {run_id or '(unknown run id)'}")
    if event_title:
        print(f"  Event: {event_title}")

    if youtube_url:
        print("⚠️  This run already has a YouTube URL recorded:")
        print(f"    {youtube_url}")
        print("   (Not uploading again. Delete the URL from the summary if you really want to re-upload.)")
        sys.exit(0)

    # Find the actual video file to upload (from output/)
    video_path = _find_output_video_for_run(output_dir, run_id)
    if not video_path or not os.path.exists(video_path):
        # Fallback to stored final_video_path if it still exists
        fallback = summary.get("final_video_path") or ""
        if fallback and os.path.exists(fallback):
            video_path = fallback
        else:
            print("❌ Could not find the final video file for this run.")
            print("   - Expected an MP4 in output/ named *_<run_id>.mp4")
            print(f"   - Run ID: {run_id}")
            sys.exit(1)

    print(f"  Video file: {video_path}")

    # Load config and force-enable YouTube upload for this helper script
    try:
        config = load_config()
    except ValueError as e:
        print(f"❌ Failed to load config: {e}")
        sys.exit(1)

    config["YOUTUBE_UPLOAD_ENABLED"] = "true"

    # Build a minimal VideoContext for the uploader
    ctx = VideoContext(
        run_id=run_id,
        started_at=summary.get("started_at", ""),
    )
    ctx.event_title = event_title
    ctx.event_description = event_description
    ctx.final_video_path = video_path

    print("\nStarting YouTube upload...")
    ctx = upload_to_youtube(ctx, config)

    if getattr(ctx, "youtube_video_url", ""):
        print("\n✅ Upload complete!")
        print(f"  YouTube URL: {ctx.youtube_video_url}")
        cleanup_run_artifacts(run_id)
        print("  Cleanup: artifacts removed")
    else:
        print("\n⚠️ Upload did not complete successfully.")
        if ctx.errors:
            print("Errors:")
            for err in ctx.errors:
                print(f"  - {err}")
            if any("credentials" in str(e).lower() for e in ctx.errors):
                print("\n💡 Try re-running OAuth setup to refresh the token:")
                print("   python3 scripts/setup_youtube_auth.py")


def main():
    parser = argparse.ArgumentParser(
        description="Arbi Flow — Automated video generation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 main.py                              # Scout auto-picks a trending event
  python3 main.py --pick                       # Scout finds 3 options, you choose
  python3 main.py --event "Oscars 2026"        # You provide the event directly
  python3 main.py --event "..." --description "..."  # With optional description hint
  python3 main.py --resume 7a7d12c4            # Resume failed run from last step
  python3 main.py --upload                     # Upload latest video to YouTube
  python3 main.py --upload 7a7d12c4            # Upload specific run to YouTube
        """
    )

    parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        help="Resume a failed run from the last successful step"
    )
    parser.add_argument(
        "--upload",
        nargs="?",
        const=True,
        metavar="RUN_ID",
        help="Upload video to YouTube (latest run if no ID provided)"
    )
    parser.add_argument(
        "--event",
        metavar="TITLE",
        help="Pin a specific event/topic instead of auto-scouting (e.g. 'Oscars 2026 Best Picture announcement')"
    )
    parser.add_argument(
        "--description",
        metavar="DESC",
        help="Optional short description for the pinned event (used with --event)"
    )
    parser.add_argument(
        "--pick",
        action="store_true",
        help="Scout 3 trending events and let you pick one before running"
    )

    args = parser.parse_args()

    if args.resume:
        resume_run(args.resume)
    elif args.upload:
        run_id = args.upload if isinstance(args.upload, str) else None
        upload_video(run_id)
    elif args.pick:
        pick_and_run()
    else:
        run_pipeline(event=args.event, description=args.description)


if __name__ == "__main__":
    main()
