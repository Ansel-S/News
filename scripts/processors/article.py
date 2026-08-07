"""
processors/article.py — Turns a raw feedparser entry into a stored Item
for every source type EXCEPT report.db (processors/report.py) and paper.db
arXiv entries (processors/paper.py). Handles core/dive/zen/paper's
non-arXiv sources, and Billboard's chart_only special case.

Every entry attempts a full-text fetch regardless of its display_mode —
display_mode only controls how the item is *rendered* in the email body
(full / title_excerpt / title_only all try the same fetch_text() full-text
extraction). The `fetched_full` column on each row records whether that
fetch actually succeeded, independent of display_mode, so renderers can
decide zip-attachment eligibility without re-fetching or re-deriving it.

chart_only (Billboard) and repo_card (GitHub Trending/HelloGitHub) are
exceptions: they're scraped/handled specially and are never eligible for
full-text fetch or the zip attachment, since they aren't "articles" — a
chart snapshot or a repo listing has nothing worth full-text-extracting.

Moved out of ingest_rss.py verbatim (Phase 2 of the architecture redesign,
see /DESIGN.md) — behavior is unchanged, only the file changed.
"""
from __future__ import annotations
import os

from processors._http import fetch_text
from ingest_base import is_recent as _is_recent
from db_utils import item_exists, insert_item

LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "8"))
RETRY_SOURCE  = os.getenv("RETRY_ONLY_SOURCE")


def is_recent(entry) -> bool:
    return _is_recent(entry, lookback_days=LOOKBACK_DAYS)


def extract_content(url: str, summary: str) -> tuple[str, bool]:
    """Always attempts a full-text fetch. Returns (content, fetched_full)
    so callers can tell "fetch succeeded" apart from "fetch failed, fell
    back to the RSS summary" — only the former is zip-eligible."""
    text = fetch_text(url)
    if text:
        return text, True
    # Wayback fallback
    try:
        wb = f"https://web.archive.org/web/{url}"
        text = fetch_text(wb)
        if text:
            return text, True
    except Exception:
        pass
    return summary or "", False


def process_entry(entry, *, db: str, feed_key: str, source_name: str,
                  display_mode: str, r: str) -> None:
    url = entry.get("link", "")
    if not url:
        return
    if RETRY_SOURCE and feed_key != RETRY_SOURCE:
        return
    if not is_recent(entry):
        return
    if item_exists(db, url):
        return

    summary = entry.get("summary", "")

    # repo_card (GitHub Trending / HelloGitHub) isn't an "article" — a repo
    # listing page has nothing worth full-text extracting — so it keeps the
    # old summary-only behavior and is never zip-eligible.
    if display_mode == "repo_card":
        content, fetched_full = summary or "", False
    else:
        content, fetched_full = extract_content(url, summary)

    insert_item(
        db,
        source_id=url, feed_key=feed_key, source_name=source_name,
        display_mode=display_mode, title=entry.get("title", ""),
        content=content, created_at=entry.get("published", r),
        extra_columns={"fetched_full": 1 if fetched_full else 0},
    )
