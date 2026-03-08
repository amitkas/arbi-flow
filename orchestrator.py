"""Generic pipeline runner for Arbi Flow.

Each pipeline defines its own agent sequence, context factory, and optional
summary builder, then calls run_pipeline() to execute."""

import glob
import os
import re
import shutil
import sys
import time
import uuid
from datetime import datetime

from config import load_config
from dedup import mark_processed
from logger import setup_logging, get_logger, StepTimer, write_run_summary


class PipelineError(Exception):
    """Raised when a pipeline agent fails. Callers decide how to handle it."""

    def __init__(self, agent_name: str, error: str, ctx=None):
        self.agent_name = agent_name
        self.error = error
        self.ctx = ctx
        super().__init__(f"{agent_name} failed: {error}")


def run_pipeline(pipeline_name, agents, context_factory, summary_builder=None, excluded_events=None, event=None, description=None):
    """Run a named pipeline: load config, create context, execute agents in sequence.

    Args:
        pipeline_name: Human-readable name (e.g., "Video Pipeline")
        agents: List of (step_name, agent_function) tuples
        context_factory: Callable(run_id, started_at, config, **kwargs) -> context instance
        summary_builder: Optional callable(ctx, agent_timings, total_time) -> dict
        excluded_events: Optional list of event titles to exclude (e.g. undownloadable subjects)
        event: Optional pinned event title — skips auto-scouting when provided
        description: Optional description for the pinned event
    Returns:
        The final context object after all agents have run.
    """
    log = get_logger("orchestrator")

    print("=" * 60)
    print(f"  ARBI FLOW \u2014 {pipeline_name}")
    print("=" * 60)

    # Load config
    try:
        config = load_config()
        print("[OK] Config loaded\n")
    except ValueError as e:
        print(f"[FAIL] {e}")
        sys.exit(1)

    # Create context
    run_id = uuid.uuid4().hex[:8]
    started_at = datetime.now().isoformat()
    factory_kwargs = {
        "excluded_events": excluded_events or [],
        "event": event,
        "description": description,
    }
    ctx = context_factory(run_id, started_at, config, **factory_kwargs)

    # Set up logging
    setup_logging(run_id)
    log.info(f"Pipeline: {pipeline_name}")
    log.info(f"Run ID: {run_id}")
    log.info(f"Started: {started_at}")

    # Clean up any partial downloads from previous failed runs
    _cleanup_partial_downloads(log)

    # Run agents in sequence
    pipeline_start = time.time()
    agent_timings = {}

    for name, agent_fn in agents:
        log.info(f"\n{'─' * 50}")
        log.info(f">> {name}")
        log.info(f"{'─' * 50}")

        with StepTimer(get_logger(name.lower().replace(" ", "_")), name) as timer:
            try:
                ctx = agent_fn(ctx, config)
                log.info(f"[OK] {name} completed ({timer.elapsed:.1f}s)")
            except Exception as e:
                log.error(f"\n[FAIL] {name} failed after {timer.elapsed:.1f}s: {e}")
                ctx.errors.append({"agent": name, "error": str(e)})
                agent_timings[name] = {
                    "status": "failed",
                    "elapsed_s": round(timer.elapsed, 2),
                    "error": str(e),
                }
                _write_summary(ctx, agent_timings, pipeline_start, pipeline_name, summary_builder)
                log.info("\nPipeline aborted.")
                raise PipelineError(name, str(e), ctx=ctx)

        agent_timings[name] = {"status": "ok", "elapsed_s": round(timer.elapsed, 2)}

    # Mark event as processed (dedup)
    if ctx.event_title:
        mark_processed(ctx.event_title, ctx.run_id)

    # Summary
    total_time = time.time() - pipeline_start
    log.info(f"\n{'=' * 60}")
    log.info(f"  {pipeline_name.upper()} COMPLETE")
    log.info(f"{'=' * 60}")
    log.info(f"  Event:      {ctx.event_title}")
    log.info(f"  Description:{ctx.event_description}")
    log.info(f"  Video:      {ctx.final_video_path or 'no video produced'}")
    log.info(f"  Run ID:     {ctx.run_id}")
    log.info(f"  Total time: {total_time:.1f}s")
    log.info(f"{'=' * 60}")

    # Write JSON summary
    summary_path = _write_summary(ctx, agent_timings, pipeline_start, pipeline_name, summary_builder)
    log.info(f"  Summary:    {summary_path}")

    # Move final output to output/ and clean up artifacts
    _finalize_output(ctx, log)

    return ctx


def cleanup_run_artifacts(run_id: str):
    """Remove run-specific artifacts from videos/, images/, audio/. Call after output is copied."""
    project_root = os.path.dirname(os.path.abspath(__file__))
    artifacts_dir = os.path.join(project_root, "artifacts")
    for subdir in ("videos", "images", "audio"):
        dirpath = os.path.join(artifacts_dir, subdir)
        if not os.path.isdir(dirpath):
            continue
        for f in glob.glob(os.path.join(dirpath, f"{run_id}_*")):
            try:
                os.remove(f)
            except Exception:
                pass
    for d in glob.glob(os.path.join(artifacts_dir, f"{run_id}_frames*")):
        shutil.rmtree(d, ignore_errors=True)


def _cleanup_partial_downloads(log):
    """Remove incomplete downloads (.part, .webm) from previous failed runs."""
    project_root = os.path.dirname(os.path.abspath(__file__))
    artifacts_dir = os.path.join(project_root, "artifacts", "videos")

    if not os.path.isdir(artifacts_dir):
        return

    partial_files = (
        glob.glob(os.path.join(artifacts_dir, "*.part")) +
        glob.glob(os.path.join(artifacts_dir, "*.webm"))
    )

    if partial_files:
        for f in partial_files:
            try:
                os.remove(f)
                log.debug(f"Removed partial download: {os.path.basename(f)}")
            except Exception as e:
                log.warning(f"Failed to remove {f}: {e}")
        log.info(f"  Cleaned {len(partial_files)} partial download(s) from previous runs")


def _write_summary(ctx, agent_timings, pipeline_start, pipeline_name, summary_builder=None):
    total_time = time.time() - pipeline_start

    if summary_builder:
        summary = summary_builder(ctx, agent_timings, total_time)
    else:
        summary = {
            "run_id": ctx.run_id,
            "pipeline": pipeline_name,
            "started_at": ctx.started_at,
            "finished_at": datetime.now().isoformat(),
            "total_time_s": round(total_time, 2),
            "event_title": ctx.event_title,
            "event_description": ctx.event_description,
            "final_video_path": ctx.final_video_path or "",
            "agents": agent_timings,
            "errors": ctx.errors,
        }

    return write_run_summary(ctx.run_id, summary)


def _finalize_output(ctx, log):
    """Move final output to output/ with a clean name, then delete run artifacts."""

    project_root = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(project_root, "output")
    artifacts_dir = os.path.join(project_root, "artifacts")
    os.makedirs(output_dir, exist_ok=True)

    # Determine the final video file
    final_path = (
        ctx.final_video_path
        or ctx.subtitled_video_path
        or ctx.video_local_path
    )

    if final_path and os.path.exists(final_path):
        # Build clean filename: Event_Title_runid.ext
        ext = os.path.splitext(final_path)[1]
        title = ctx.event_title or ctx.run_id
        clean_title = re.sub(r"[^\w\s-]", "", title).strip()
        clean_title = re.sub(r"[\s-]+", "_", clean_title)
        clean_name = f"{clean_title}_{ctx.run_id}{ext}"

        dest = os.path.join(output_dir, clean_name)
        shutil.copy2(final_path, dest)
        log.info(f"  Output:     {dest}")
    else:
        log.info("  Output:     no media file to export")

    cleanup_run_artifacts(ctx.run_id)
    log.info(f"  Cleanup:    artifacts for {ctx.run_id} removed")
