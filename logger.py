import json
import logging
import os
import time
from datetime import datetime


LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")


class RunFormatter(logging.Formatter):
    """Console formatter — clean, prefixed output matching the original style."""

    def format(self, record):
        # For console: just the message (agents add their own prefix)
        return record.getMessage()


class FileFormatter(logging.Formatter):
    """File formatter — timestamp + level + logger name + message."""

    def format(self, record):
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        return f"[{ts}] [{record.levelname:<7}] [{record.name}] {record.getMessage()}"


def setup_logging(run_id: str) -> logging.Logger:
    """Configure logging for a pipeline run.

    Returns the root pipeline logger. Agents should use
    logging.getLogger('pipeline.<agent_name>').

    - Console: INFO level (same as the old print output)
    - File:    DEBUG level (detailed logs for post-run analysis)
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    log_path = os.path.join(LOG_DIR, f"{run_id}.log")

    root = logging.getLogger("pipeline")
    root.setLevel(logging.DEBUG)

    # Prevent duplicate handlers on re-runs in the same process
    root.handlers.clear()

    # Console handler — INFO
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(RunFormatter())
    root.addHandler(ch)

    # File handler — DEBUG
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(FileFormatter())
    root.addHandler(fh)

    root.info(f"Log file: {log_path}")
    return root


def get_logger(agent_name: str) -> logging.Logger:
    """Get a child logger for a specific agent."""
    return logging.getLogger(f"pipeline.{agent_name}")


class StepTimer:
    """Context manager that logs elapsed time for a step."""

    def __init__(self, logger: logging.Logger, step_name: str):
        self.logger = logger
        self.step_name = step_name
        self.start = None
        self.elapsed = 0.0

    def __enter__(self):
        self.start = time.time()
        self.logger.debug(f"Started: {self.step_name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.elapsed = time.time() - self.start
        if exc_type:
            self.logger.error(f"Failed: {self.step_name} after {self.elapsed:.2f}s — {exc_val}")
        else:
            self.logger.debug(f"Finished: {self.step_name} in {self.elapsed:.2f}s")
        return False


def write_run_summary(run_id: str, summary: dict):
    """Write a JSON summary of the entire run to logs/{run_id}_summary.json."""
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"{run_id}_summary.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    return path
