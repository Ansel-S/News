"""
processors/article.py — Turns a raw feedparser entry into a stored Item
for every source type EXCEPT report.db (processors/report.py) and paper.db
arXiv entries (processors/paper.py). Handles content.db's non-arXiv
sources.

Every entry attempts a full-text fetch unless its extract_mode is "skip"
— extract_mode and email_mode are independent: email_mode only controls
how the item is *rendered* in the email body (full / excerpt / title all
try the same fetch_text() full-text extraction when extract_mode is
"normal"). The `fetched_full` column on each row records whether that
fetch actually succeeded, independent of email_mode, so renderers can
decide zip-attachment eligibility without re-fetching or re-deriving it.

extract_mode="skip" (GitHub-listing sources like GitHub Trending/
HelloGitHub-if-configured-that-way) is an exception: never eligible for
full-text fetch or the zip attachment, since a repo listing has nothing
worth full-text-extracting.
"""
from __future__ import annotations
import os

from processors._http import fetch_text
from ingest.ingest_base import is_recent as _is_recent
from db.db_utils import item_exists, insert_item

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
                  extract_mode: str, email_mode: str, r: str,
                  source_key: str | None = None) -> None:
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

    # extract_mode="skip" (GitHub-listing style sources) isn't an
    # "article" — a repo listing page has nothing worth full-text
    # extracting — so it keeps summary-only content and is never
    # zip-eligible.
    if extract_mode == "skip":
        content, fetched_full = summary or "", False
    else:
        content, fetched_full = extract_content(url, summary)

    insert_item(
        db,
        source_id=url, feed_key=feed_key, source_name=source_name,
        email_mode=email_mode, extract_mode=extract_mode, title=entry.get("title", ""),
        content=content, created_at=entry.get("published", r),
        extra_columns={"fetched_full": 1 if fetched_full else 0},
        source_key=source_key,
    )
