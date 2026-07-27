"""
db_utils.py — Shared database read/write utilities for all databases
"""
from __future__ import annotations
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


def estimate_read(text: str | None) -> tuple[int, int]:
    """Return (word_count, read_minutes). Chinese: 350 chars/min, English: 250 words/min."""
    if not text:
        return 0, 0
    zh    = len(re.findall(r"[\u4e00-\u9fff]", text))
    en    = len(re.findall(r"[a-zA-Z]+", text))
    mins  = max(1, round((zh / 350) + (en / 250)))
    return zh + en, mins


def _conn(db: str) -> sqlite3.Connection:
    c = sqlite3.connect(db_path(db), timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    return c


# ── Generic items table (core / dive / zen / paper) ──────────────────────────

def item_exists(db: str, url: str) -> bool:
    with _conn(db) as c:
        return c.execute(
            "SELECT 1 FROM items WHERE source_id=? LIMIT 1", (url,)
        ).fetchone() is not None


def insert_item(
    db: str, *,
    source_id: str,
    feed_key: str,
    source_name: str,
    display_mode: str,
    title: str,
    content: str,
    created_at: str,
) -> None:
    wc, rm = estimate_read(content)
    with _conn(db) as c:
        c.execute(
            """INSERT OR IGNORE INTO items
               (id, source_id, feed_key, source_name, display_mode,
                title, content, created_at, ingested_at, word_count, read_minutes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (item_hash(source_id), source_id, feed_key, source_name,
             display_mode, title, content, created_at, now_iso(), wc, rm),
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


def get_unpushed(db: str, issue_type: str, *, exclude_feed_prefix: str | None = None) -> list[sqlite3.Row]:
    """All items not yet sent in this issue type, newest first.

    `exclude_feed_prefix`: skip rows whose feed_key starts with this prefix.
    Needed because get_unpushed filters by (db, issue_type) — rows sharing
    the same db but tagged with a different issue_type (e.g. "extra_daily"
    rows living in core.db alongside "daily" rows) would otherwise still be
    picked up here as long as they've never been pushed under THIS issue_type.
    """
    query = """SELECT i.* FROM items i
               WHERE NOT EXISTS (
                 SELECT 1 FROM push_log p
                 WHERE p.item_id=i.id AND p.issue_type=?
               )"""
    params: list = [issue_type]
    if exclude_feed_prefix:
        query += " AND i.feed_key NOT LIKE ?"
        params.append(f"{exclude_feed_prefix}%")
    query += " ORDER BY created_at DESC"
    with _conn(db) as c:
        return c.execute(query, params).fetchall()


# ── report.db ────────────────────────────────────────────────────────────────

def report_exists(url: str) -> bool:
    with _conn("report") as c:
        return c.execute(
            "SELECT 1 FROM reports WHERE source_id=? LIMIT 1", (url,)
        ).fetchone() is not None


def insert_report(
    *, source_id: str, feed_key: str, source_name: str,
    title: str, pdf_url: str | None, pdf_data: bytes | None, created_at: str,
) -> None:
    with _conn("report") as c:
        c.execute(
            """INSERT OR IGNORE INTO reports
               (id, source_id, feed_key, source_name, title, pdf_url, pdf_data,
                created_at, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (item_hash(source_id), source_id, feed_key, source_name,
             title, pdf_url, pdf_data, created_at, now_iso()),
        )


def get_unpushed_reports(issue_type: str) -> list[sqlite3.Row]:
    with _conn("report") as c:
        return c.execute(
            """SELECT r.* FROM reports r
               WHERE NOT EXISTS (
                 SELECT 1 FROM push_log p
                 WHERE p.item_id=r.id AND p.issue_type=?
               )
               ORDER BY created_at DESC""",
            (issue_type,),
        ).fetchall()


def mark_pushed_report(item_id: str, issue_type: str, issue_id: str) -> None:
    with _conn("report") as c:
        c.execute(
            """INSERT OR IGNORE INTO push_log (item_id, issue_type, issue_id, pushed_at)
               VALUES (?,?,?,?)""",
            (item_id, issue_type, issue_id, now_iso()),
        )


# ── hn.db ────────────────────────────────────────────────────────────────────

def hn_exists(hn_id: str) -> bool:
    with _conn("hn") as c:
        return c.execute(
            "SELECT 1 FROM hn_items WHERE id=? LIMIT 1", (str(hn_id),)
        ).fetchone() is not None


def insert_hn(*, hn_id: str, title: str, url: str | None,
              score: int, by: str, descendants: int, created_at: str) -> None:
    source_id = f"https://news.ycombinator.com/item?id={hn_id}"
    with _conn("hn") as c:
        c.execute(
            """INSERT OR IGNORE INTO hn_items
               (id, source_id, title, url, score, by, descendants, created_at, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (str(hn_id), source_id, title, url, score, by, descendants, created_at, now_iso()),
        )


def get_unpushed_hn(issue_type: str) -> list[sqlite3.Row]:
    with _conn("hn") as c:
        return c.execute(
            """SELECT h.* FROM hn_items h
               WHERE NOT EXISTS (
                 SELECT 1 FROM push_log p
                 WHERE p.item_id=h.id AND p.issue_type=?
               )
               ORDER BY score DESC""",
            (issue_type,),
        ).fetchall()


def mark_pushed_hn(item_id: str, issue_type: str, issue_id: str) -> None:
    with _conn("hn") as c:
        c.execute(
            """INSERT OR IGNORE INTO push_log (item_id, issue_type, issue_id, pushed_at)
               VALUES (?,?,?,?)""",
            (item_id, issue_type, issue_id, now_iso()),
        )


# ── youtube.db ───────────────────────────────────────────────────────────────

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
    mode: str = "mixed",
) -> None:
    """Only writes to yt_items when subtitle text was actually found — this
    is the table render_yt.py reads for the weekly email + subtitle zip.
    Videos with no subtitle (pure video/audio-mode channels) are NOT written
    here, keeping youtube.db limited to content that's actually readable.
    Dedup for those videos is still handled separately via mark_yt_seen()."""
    if not subtitle:
        return
    with _conn("youtube") as c:
        c.execute(
            """INSERT OR IGNORE INTO yt_items
               (id, video_url, video_id, channel_id, channel_name, feed_key,
                title, subtitle, published_at, ingested_at, mode)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (item_hash(video_url), video_url, video_id, channel_id, channel_name,
             feed_key, title, subtitle, published_at, now_iso(), mode),
        )


def insert_yt_media_item(
    *, video_url: str, video_id: str, channel_id: str, channel_name: str,
    feed_key: str, title: str, published_at: str, mode: str = "video",
) -> None:
    """Videos from video/audio-only channels with no subtitle text still need
    a title + download-link row in the weekly email. Written here instead of
    yt_items, which keeps yt_items limited to rows with actual subtitle
    content. A video is in exactly one of yt_items / yt_media_items, never
    both — insert_yt() already returns early when subtitle is empty."""
    with _conn("youtube") as c:
        c.execute(
            """INSERT OR IGNORE INTO yt_media_items
               (id, video_url, video_id, channel_id, channel_name, feed_key,
                title, published_at, ingested_at, mode)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (item_hash(video_url), video_url, video_id, channel_id, channel_name,
             feed_key, title, published_at, now_iso(), mode),
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


def get_unpushed_yt(issue_type: str) -> list[sqlite3.Row]:
    with _conn("youtube") as c:
        return c.execute(
            """SELECT y.* FROM yt_items y
               WHERE NOT EXISTS (
                 SELECT 1 FROM push_log p
                 WHERE p.item_id=y.id AND p.issue_type=?
               )
               ORDER BY feed_key, published_at DESC""",
            (issue_type,),
        ).fetchall()


def get_unpushed_yt_media(issue_type: str) -> list[sqlite3.Row]:
    """Videos with no subtitle (video/audio-only channels) — title + download
    link only, no full content. Uses the same push_log item_id namespace as
    yt_items (both hash from video_url), so a video never double-counts."""
    with _conn("youtube") as c:
        return c.execute(
            """SELECT y.* FROM yt_media_items y
               WHERE NOT EXISTS (
                 SELECT 1 FROM push_log p
                 WHERE p.item_id=y.id AND p.issue_type=?
               )
               ORDER BY feed_key, published_at DESC""",
            (issue_type,),
        ).fetchall()


def mark_pushed_yt(item_id: str, issue_type: str, issue_id: str) -> None:
    with _conn("youtube") as c:
        c.execute(
            """INSERT OR IGNORE INTO push_log (item_id, issue_type, issue_id, pushed_at)
               VALUES (?,?,?,?)""",
            (item_id, issue_type, issue_id, now_iso()),
        )