"""
db_utils.py — Shared database read/write utilities for all databases

DESIGN: every db's main table shares the `items` shape (id, source_id,
feed_key, source_name, source_key, extract_mode, email_mode, title,
content, created_at, ingested_at, read_minutes) — see schema.sql. That
means one generic set of functions (item_exists / insert_item /
get_unpushed / mark_pushed) covers content.db, report.db, hn.db, and
youtube.db's yt_items / yt_media_items, just by passing a different `db`/
`table` name. Each db then gets a small number of extra functions only for
what's genuinely unique to it: report.db's and content.db's PDF blob
columns, hn.db's score/by/descendants, youtube.db's dedup table +
media-download-link table.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_SCRIPTS_DIR = _Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_SCRIPTS_DIR))
import hashlib
import re
import sqlite3
from datetime import datetime, UTC

from config import db_path


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def item_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def estimate_read(text: str | None) -> int:
    """Return read_minutes. Chinese: 350 chars/min, English: 250 words/min.
    (Used to also return word_count — dropped, it was stored on every row
    but never read anywhere; see db_init.py.)"""
    if not text:
        return 0
    zh = len(re.findall(r"[\u4e00-\u9fff]", text))
    en = len(re.findall(r"[a-zA-Z]+", text))
    return max(1, round((zh / 350) + (en / 250)))


def _conn(db: str) -> sqlite3.Connection:
    c = sqlite3.connect(db_path(db), timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    return c


# ── Generic items table (content / report / hn / youtube) ──
# `table` defaults to "items"; pass e.g. "hn_items", "report_items",
# "yt_items", "yt_media_items" for the others.

def item_exists(db: str, source_id: str, *, table: str = "items") -> bool:
    with _conn(db) as c:
        return c.execute(
            f"SELECT 1 FROM {table} WHERE source_id=? LIMIT 1", (source_id,)
        ).fetchone() is not None


def insert_item(
    db: str, *,
    source_id: str,
    feed_key: str,
    source_name: str,
    title: str,
    content: str | None,
    created_at: str,
    email_mode: str = "full",
    extract_mode: str | None = None,
    table: str = "items",
    id_override: str | None = None,
    extra_columns: dict | None = None,
    source_key: str | None = None,
) -> None:
    """Insert one row into any items-shaped table. `id_override` lets callers
    use a different primary key than sha256(source_id) (e.g. hn.db uses the
    raw HN item id). `extra_columns` adds db-specific columns beyond the
    common items shape (e.g. {"score": 5, "by": "alice"} for hn_items, or
    {"video_id": "...", "channel_id": "..."} for yt_items).

    `email_mode` (full|excerpt|title) controls how much shows in the email
    body. `extract_mode` (normal|skip) controls whether full-text
    extraction was attempted at all — genuinely independent of email_mode
    (e.g. a title-only-displayed source can still be fully fetched and
    zip-eligible). Only written when the table has the column (report_items
    has email_mode but not extract_mode — see db_init.py).

    `source_key`: the config/sources/*.yml source id (e.g. "tldr-tech"),
    NOT the same thing as `feed_key` (the section/grouping label — several
    sources can share one feed_key). This is what lets issues/builder.py
    filter a shared table per-issue when more than one issue's sources
    coexist in the same (db, table)."""
    rm = estimate_read(content)
    row_id = id_override or item_hash(source_id)
    extra_columns = extra_columns or {}

    cols   = ["id", "source_id", "feed_key", "source_name", "email_mode",
              "title", "content", "created_at", "ingested_at", "read_minutes"]
    values = [row_id, source_id, feed_key, source_name, email_mode,
              title, content, created_at, now_iso(), rm]
    if extract_mode is not None:
        cols.append("extract_mode")
        values.append(extract_mode)
    if source_key is not None:
        cols.append("source_key")
        values.append(source_key)
    for k, v in extra_columns.items():
        cols.append(k)
        values.append(v)

    placeholders = ",".join("?" * len(cols))
    col_list = ",".join(cols)
    with _conn(db) as c:
        c.execute(
            f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
            values,
        )


def insert_error(db: str, *, run_id: str, source_id: str,
                 stage: str, error_type: str, message: str) -> None:
    with _conn(db) as c:
        c.execute(
            """INSERT INTO errors (run_id, source_id, stage, error_type, message, created_at)
               VALUES (?,?,?,?,?,?)""",
            (run_id, source_id, stage, error_type, message, now_iso()),
        )


def mark_pushed(db: str, item_id: str, issue_type: str, issue_id: str) -> None:
    with _conn(db) as c:
        c.execute(
            """INSERT OR IGNORE INTO push_log (item_id, issue_type, issue_id, pushed_at)
               VALUES (?,?,?,?)""",
            (item_id, issue_type, issue_id, now_iso()),
        )


def get_unpushed(
    db: str, issue_type: str, *,
    table: str = "items",
    exclude_feed_prefix: str | None = None,
    order_by: str = "created_at DESC",
    source_keys: set[str] | None = None,
) -> list[sqlite3.Row]:
    """All items not yet sent in this issue type.

    `table`: which items-shaped table to read (default "items").
    `exclude_feed_prefix`: skip rows whose feed_key starts with this prefix.
    `order_by`: override sort order (e.g. "score DESC" for hn_items).
    `source_keys`: restrict to rows whose source_key column is in this set.
    Used by issues/builder.py when a (db, table) is shared by more than one
    issue's sources (content.db's items table). Rows written before
    source_key existed have NULL there and are excluded whenever this
    filter is used — see migrate_content_db.py's backfill step.
    """
    query = f"""SELECT i.* FROM {table} i
               WHERE NOT EXISTS (
                 SELECT 1 FROM push_log p
                 WHERE p.item_id=i.id AND p.issue_type=?
               )"""
    params: list = [issue_type]
    if exclude_feed_prefix:
        query += " AND i.feed_key NOT LIKE ?"
        params.append(f"{exclude_feed_prefix}%")
    if source_keys is not None:
        placeholders = ",".join("?" * len(source_keys))
        query += f" AND i.source_key IN ({placeholders})"
        params.extend(sorted(source_keys))
    query += f" ORDER BY {order_by}"
    with _conn(db) as c:
        return c.execute(query, params).fetchall()


# ── report.db — adds PDF-specific fields on top of the generic items shape ──

def report_exists(url: str) -> bool:
    return item_exists("report", url, table="report_items")


def insert_report(
    *, source_id: str, feed_key: str, source_name: str,
    title: str, pdf_url: str | None, pdf_data: bytes | None, created_at: str,
    source_key: str | None = None,
) -> None:
    insert_item(
        "report", source_id=source_id, feed_key=feed_key, source_name=source_name,
        title=title, content=None, created_at=created_at, table="report_items",
        email_mode="title",
        extra_columns={"pdf_url": pdf_url, "pdf_data": pdf_data},
        source_key=source_key,
    )


# ── content.db's arXiv rows — direct PDF download, own path from report.db's
# generic-thinktank PDF-scraping logic (find_pdf_link etc). arXiv URLs are
# predictable (abs/{id} -> pdf/{id}), so no HTML scraping is needed to find
# the link. Non-arXiv paper-topic sources (ACM Queue, Quanta, etc) still go
# through insert_item()/item_exists() directly with table="items" and no
# PDF — same title+abstract-only shape as before.

def paper_exists(url: str) -> bool:
    return item_exists("content", url, table="items")


def insert_paper(
    *, source_id: str, feed_key: str, source_name: str,
    title: str, content: str | None, pdf_url: str | None, pdf_data: bytes | None,
    created_at: str, source_key: str | None = None,
) -> None:
    insert_item(
        "content", source_id=source_id, feed_key=feed_key, source_name=source_name,
        title=title, content=content, created_at=created_at, table="items",
        email_mode="title", extract_mode="normal",
        extra_columns={"pdf_url": pdf_url, "pdf_data": pdf_data},
        source_key=source_key,
    )


# ── hn.db — adds score/by/descendants on top of the generic items shape ─────

def hn_exists(hn_id: str) -> bool:
    with _conn("hn") as c:
        return c.execute(
            "SELECT 1 FROM hn_items WHERE id=? LIMIT 1", (str(hn_id),)
        ).fetchone() is not None


def insert_hn(*, hn_id: str, title: str, url: str | None,
              score: int, by: str, descendants: int, created_at: str) -> None:
    source_id = f"https://news.ycombinator.com/item?id={hn_id}"
    insert_item(
        "hn", source_id=source_id, feed_key="hn", source_name="Hacker News",
        title=title, content=None, created_at=created_at, table="hn_items",
        id_override=str(hn_id), email_mode="title", extract_mode="normal",
        source_key="hackernews",
        extra_columns={"external_url": url, "score": score, "by": by, "descendants": descendants},
    )


# ── youtube.db — dedup table + media-download-link table are genuinely
# unique to this db (no other db has an equivalent), so they stay as
# dedicated functions. yt_items / yt_media_items themselves use the generic
# item_exists/insert_item/get_unpushed above with table="yt_items" etc.

def yt_exists(video_url: str) -> bool:
    """Dedup check — looks at yt_seen, which every processed video is
    recorded in regardless of whether it had subtitles or not."""
    with _conn("youtube") as c:
        return c.execute(
            "SELECT 1 FROM yt_seen WHERE id=? LIMIT 1", (item_hash(video_url),)
        ).fetchone() is not None


def mark_yt_seen(video_url: str, video_id: str) -> None:
    """Record that this video has been processed, for dedup purposes only.
    Called for every video regardless of mode or whether subtitles/media
    were successfully retrieved — this is what keeps re-runs from
    re-downloading video/audio-only channels that never touch yt_items."""
    with _conn("youtube") as c:
        c.execute(
            """INSERT OR IGNORE INTO yt_seen (id, video_url, video_id, ingested_at)
               VALUES (?,?,?,?)""",
            (item_hash(video_url), video_url, video_id, now_iso()),
        )


def insert_yt(
    *, video_url: str, video_id: str, channel_id: str, channel_name: str,
    feed_key: str, title: str, subtitle: str | None, published_at: str,
    mode: str = "mixed", source_key: str | None = None,
) -> None:
    """Only writes to yt_items when subtitle text was actually found — this
    is the table render_yt.py reads for the weekly email + subtitle zip.
    Videos with no subtitle (pure video/audio-mode channels) are NOT written
    here, keeping youtube.db limited to content that's actually readable.
    Dedup for those videos is still handled separately via mark_yt_seen().
    fetched_full is always 1 here (not left at its column default of 0) —
    a yt_items row existing at all already means the subtitle fetch
    succeeded, by the early-return above."""
    if not subtitle:
        return
    insert_item(
        "youtube", source_id=video_url, feed_key=feed_key, source_name=channel_name,
        title=title, content=subtitle, created_at=published_at, table="yt_items",
        email_mode="excerpt", extract_mode="normal",
        source_key=source_key or channel_id,
        extra_columns={"video_id": video_id, "channel_id": channel_id, "mode": mode,
                       "fetched_full": 1},
    )


def insert_yt_media_item(
    *, video_url: str, video_id: str, channel_id: str, channel_name: str,
    feed_key: str, title: str, published_at: str, mode: str = "video",
    source_key: str | None = None,
) -> None:
    """Videos from video/audio-only channels with no subtitle text still need
    a title + download-link row in the weekly email. Written here instead of
    yt_items, which keeps yt_items limited to rows with actual subtitle
    content. A video is in exactly one of yt_items / yt_media_items, never
    both — insert_yt() already returns early when subtitle is empty."""
    insert_item(
        "youtube", source_id=video_url, feed_key=feed_key, source_name=channel_name,
        title=title, content=None, created_at=published_at, table="yt_media_items",
        email_mode="title", extract_mode="skip",
        source_key=source_key or channel_id,
        extra_columns={"video_id": video_id, "channel_id": channel_id, "mode": mode},
    )


def set_yt_media_url(video_id: str, kind: str, media_url: str) -> None:
    """Record a download URL for one kind of media ('video' or 'audio') after
    it's been uploaded as a GitHub Release asset. Stored in yt_media, keyed
    by (video_id, kind) — independent of whether this video also has a
    yt_items row, since most video/audio-mode channels won't."""
    with _conn("youtube") as c:
        c.execute(
            """INSERT INTO yt_media (video_id, kind, media_url, ingested_at)
               VALUES (?,?,?,?)
               ON CONFLICT(video_id, kind) DO UPDATE SET media_url=excluded.media_url""",
            (video_id, kind, media_url, now_iso()),
        )


def get_yt_media(video_id: str) -> dict[str, str]:
    """Return {"video": url, "audio": url} for whichever kinds were uploaded."""
    with _conn("youtube") as c:
        rows = c.execute(
            "SELECT kind, media_url FROM yt_media WHERE video_id=?", (video_id,)
        ).fetchall()
        return {r["kind"]: r["media_url"] for r in rows}
