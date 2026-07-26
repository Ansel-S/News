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


def get_unpushed(db: str, issue_type: str) -> list[sqlite3.Row]:
    """All items not yet sent in this issue type, newest first."""
    with _conn(db) as c:
        return c.execute(
            """SELECT i.* FROM items i
               WHERE NOT EXISTS (
                 SELECT 1 FROM push_log p
                 WHERE p.item_id=i.id AND p.issue_type=?
               )
               ORDER BY created_at DESC""",
            (issue_type,),
        ).fetchall()


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
    with _conn("youtube") as c:
        return c.execute(
            "SELECT 1 FROM yt_items WHERE video_url=? LIMIT 1", (video_url,)
        ).fetchone() is not None


def insert_yt(
    *, video_url: str, video_id: str, channel_id: str, channel_name: str,
    feed_key: str, title: str, subtitle: str | None, published_at: str,
    mode: str = "mixed", media_url: str | None = None,
) -> None:
    with _conn("youtube") as c:
        c.execute(
            """INSERT OR IGNORE INTO yt_items
               (id, video_url, video_id, channel_id, channel_name, feed_key,
                title, subtitle, published_at, ingested_at, has_subtitle, mode, media_url)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (item_hash(video_url), video_url, video_id, channel_id, channel_name,
             feed_key, title, subtitle, published_at, now_iso(),
             1 if subtitle else 0, mode, media_url),
        )


def set_yt_media_url(video_url: str, media_url: str) -> None:
    """Update media_url after a low-res video/audio file has been uploaded
    as a GitHub Release asset (called from the workflow after upload)."""
    with _conn("youtube") as c:
        c.execute(
            "UPDATE yt_items SET media_url=? WHERE id=?",
            (media_url, item_hash(video_url)),
        )


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


def mark_pushed_yt(item_id: str, issue_type: str, issue_id: str) -> None:
    with _conn("youtube") as c:
        c.execute(
            """INSERT OR IGNORE INTO push_log (item_id, issue_type, issue_id, pushed_at)
               VALUES (?,?,?,?)""",
            (item_id, issue_type, issue_id, now_iso()),
        )
