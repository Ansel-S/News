"""
ingest_base.py — Shared helpers for the ingest scripts (ingest_rss.py,
ingest_youtube.py, ingest_hn.py): the "submit a pile of tasks, run them
concurrently, print+swallow per-task exceptions" skeleton, and the
lookback-window recency check, were duplicated near-verbatim across scripts.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, UTC
from typing import Any, Callable


def is_recent(entry: dict, *, lookback_days: int) -> bool:
    """True if a feedparser entry's published_parsed date is within the
    lookback window (or has no date at all, in which case we don't want to
    silently drop it — better to over-include than lose something)."""
    pub = entry.get("published_parsed")
    if pub is None:
        return True
    try:
        return datetime(*pub[:6], tzinfo=UTC) >= datetime.now(UTC) - timedelta(days=lookback_days)
    except Exception:
        return True


def run_parallel(
    tasks: list[dict[str, Any]],
    fn: Callable[..., None],
    *,
    max_workers: int,
    label_key: str | None = None,
) -> None:
    """Submit `fn(**task)` for every task dict, draining with as_completed.
    Exceptions from individual tasks are caught, printed, and don't stop the
    rest of the batch. `label_key`: which key in each task dict to use when
    printing an error (falls back to the whole task dict if not given)."""
    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futures = {exe.submit(fn, **t): t for t in tasks}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as ex:
                task = futures[future]
                label = task.get(label_key, task) if label_key else task
                print(f"[unhandled] {label}: {ex}")
