import fcntl
import json
import os
from datetime import datetime

DEDUP_FILE = os.path.join(os.path.dirname(__file__), "data", "processed_events.json")

# Also check old file for backward compatibility
OLD_DEDUP_FILE = os.path.join(os.path.dirname(__file__), "data", "processed_persons.json")


def _load_store() -> dict:
    """Load dedup store with file locking to prevent race conditions."""
    if os.path.exists(DEDUP_FILE):
        with open(DEDUP_FILE, "r") as f:
            # Acquire shared lock for reading
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    # Migrate from old format if it exists
    if os.path.exists(OLD_DEDUP_FILE):
        with open(OLD_DEDUP_FILE, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                old_data = json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        # Convert person_name entries to event_title entries
        new_processed = []
        for entry in old_data.get("processed", []):
            new_processed.append({
                "event_title": entry.get("person_name", entry.get("event_title", "")),
                "processed_at": entry.get("processed_at", ""),
                "run_id": entry.get("run_id", ""),
            })
        return {"processed": new_processed}

    return {"processed": []}


def _save_store(store: dict) -> None:
    """Save dedup store with file locking to prevent corruption."""
    os.makedirs(os.path.dirname(DEDUP_FILE), exist_ok=True)

    # Write to temp file first, then atomic rename
    temp_file = DEDUP_FILE + ".tmp"

    with open(temp_file, "w") as f:
        # Acquire exclusive lock for writing
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(store, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    # Atomic rename
    os.rename(temp_file, DEDUP_FILE)


def _significant_words(title: str) -> set[str]:
    """Extract significant words (3+ chars, lowercased) from a title."""
    return {w.strip("'\".,!?()-").lower() for w in title.split() if len(w.strip("'\".,!?()-")) >= 3}


def is_fuzzy_match(title_a: str, title_b: str, threshold: float = 0.5) -> bool:
    """Check if two titles share enough significant words to be the same event.
    Returns True if the overlap ratio (vs the smaller set) >= threshold."""
    words_a = _significant_words(title_a)
    words_b = _significant_words(title_b)
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b)
    smaller = min(len(words_a), len(words_b))
    return (overlap / smaller) >= threshold


def is_already_processed(event_title: str) -> bool:
    store = _load_store()
    title_lower = event_title.strip().lower()
    for p in store["processed"]:
        existing = p["event_title"].strip().lower()
        # Exact match
        if existing == title_lower:
            return True
        # Fuzzy match — same event, different phrasing
        if is_fuzzy_match(event_title, p["event_title"]):
            return True
    return False


def mark_processed(event_title: str, run_id: str) -> None:
    store = _load_store()
    store["processed"].append({
        "event_title": event_title,
        "processed_at": datetime.now().isoformat(),
        "run_id": run_id,
    })
    _save_store(store)


def get_all_processed() -> list[str]:
    store = _load_store()
    return [p["event_title"] for p in store["processed"]]
