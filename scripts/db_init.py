"""
db_init.py — Initialize / migrate all databases
Usage:
  python scripts/db_init.py              # all databases
  python scripts/db_init.py core hn      # specific databases
"""
from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

ROOT   = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "database"

# Each db gets its own explicit CREATE statements — no schema file parsing.
SCHEMAS: dict[str, list[str]] = {
    "core": [
        """CREATE TABLE IF NOT EXISTS items (
            id           TEXT PRIMARY KEY,
            source_id    TEXT NOT NULL,
            feed_key     TEXT NOT NULL,
            source_name  TEXT NOT NULL,
            display_mode TEXT NOT NULL,
            title        TEXT,
            content      TEXT,
            created_at   TEXT,
            ingested_at  TEXT NOT NULL DEFAULT '',
            word_count   INTEGER DEFAULT 0,
            read_minutes INTEGER DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS push_log (
            item_id    TEXT NOT NULL,
            issue_type TEXT NOT NULL,
            issue_id   TEXT NOT NULL,
            pushed_at  TEXT NOT NULL,
            PRIMARY KEY (item_id, issue_type)
        )""",
        """CREATE TABLE IF NOT EXISTS errors (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id     TEXT NOT NULL,
            source_id  TEXT NOT NULL,
            stage      TEXT NOT NULL,
            error_type TEXT NOT NULL,
            message    TEXT,
            created_at TEXT NOT NULL
        )""",
    ],
    "dive": [],   # same as core — filled below
    "zen":  [],
    "paper": [],
    "report": [
        """CREATE TABLE IF NOT EXISTS reports (
            id          TEXT PRIMARY KEY,
            source_id   TEXT NOT NULL,
            feed_key    TEXT NOT NULL,
            source_name TEXT NOT NULL,
            title       TEXT,
            pdf_url     TEXT,
            pdf_data    BLOB,
            created_at  TEXT,
            ingested_at TEXT NOT NULL DEFAULT ''
        )""",
        """CREATE TABLE IF NOT EXISTS push_log (
            item_id    TEXT NOT NULL,
            issue_type TEXT NOT NULL,
            issue_id   TEXT NOT NULL,
            pushed_at  TEXT NOT NULL,
            PRIMARY KEY (item_id, issue_type)
        )""",
        """CREATE TABLE IF NOT EXISTS errors (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id     TEXT NOT NULL,
            source_id  TEXT NOT NULL,
            stage      TEXT NOT NULL,
            error_type TEXT NOT NULL,
            message    TEXT,
            created_at TEXT NOT NULL
        )""",
    ],
    "hn": [
        """CREATE TABLE IF NOT EXISTS hn_items (
            id          TEXT PRIMARY KEY,
            source_id   TEXT NOT NULL,
            title       TEXT NOT NULL,
            url         TEXT,
            score       INTEGER NOT NULL,
            by          TEXT,
            descendants INTEGER DEFAULT 0,
            created_at  TEXT NOT NULL,
            ingested_at TEXT NOT NULL DEFAULT ''
        )""",
        """CREATE TABLE IF NOT EXISTS push_log (
            item_id    TEXT NOT NULL,
            issue_type TEXT NOT NULL,
            issue_id   TEXT NOT NULL,
            pushed_at  TEXT NOT NULL,
            PRIMARY KEY (item_id, issue_type)
        )""",
    ],
    "youtube": [
        """CREATE TABLE IF NOT EXISTS yt_items (
            id           TEXT PRIMARY KEY,
            video_url    TEXT NOT NULL,
            video_id     TEXT NOT NULL,
            channel_id   TEXT NOT NULL,
            channel_name TEXT NOT NULL,
            feed_key     TEXT NOT NULL,
            title        TEXT,
            subtitle     TEXT,
            published_at TEXT,
            ingested_at  TEXT NOT NULL DEFAULT '',
            has_subtitle INTEGER DEFAULT 0,
            mode         TEXT DEFAULT 'mixed',
            media_url    TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS push_log (
            item_id    TEXT NOT NULL,
            issue_type TEXT NOT NULL,
            issue_id   TEXT NOT NULL,
            pushed_at  TEXT NOT NULL,
            PRIMARY KEY (item_id, issue_type)
        )""",
        """CREATE TABLE IF NOT EXISTS errors (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id     TEXT NOT NULL,
            source_id  TEXT NOT NULL,
            stage      TEXT NOT NULL,
            error_type TEXT NOT NULL,
            message    TEXT,
            created_at TEXT NOT NULL
        )""",
    ],
}

# dive / zen / paper share identical schema with core
for _db in ("dive", "zen", "paper"):
    SCHEMAS[_db] = SCHEMAS["core"]


def init_db(name: str) -> None:
    DB_DIR.mkdir(exist_ok=True)
    path = DB_DIR / f"{name}.db"
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    for stmt in SCHEMAS[name]:
        conn.execute(stmt)
    conn.commit()
    _migrate(conn, name)
    conn.close()
    print(f"db_init: {name}.db OK")


def _migrate(conn: sqlite3.Connection, name: str) -> None:
    """Safely add columns introduced after initial schema."""
    if name in ("core", "dive", "zen", "paper"):
        existing = {r[1] for r in conn.execute("PRAGMA table_info(items)")}
        for col, defn in [
            ("feed_key",     "TEXT NOT NULL DEFAULT ''"),
            ("source_name",  "TEXT NOT NULL DEFAULT ''"),
            ("display_mode", "TEXT NOT NULL DEFAULT 'title_excerpt'"),
            ("word_count",   "INTEGER DEFAULT 0"),
            ("read_minutes", "INTEGER DEFAULT 0"),
            ("ingested_at",  "TEXT NOT NULL DEFAULT ''"),
        ]:
            if col not in existing:
                conn.execute(f"ALTER TABLE items ADD COLUMN {col} {defn}")
        conn.commit()

    if name == "report":
        existing = {r[1] for r in conn.execute("PRAGMA table_info(reports)")}
        for col, defn in [("pdf_url", "TEXT"), ("pdf_data", "BLOB")]:
            if col not in existing:
                conn.execute(f"ALTER TABLE reports ADD COLUMN {col} {defn}")
        conn.commit()

    if name == "youtube":
        existing = {r[1] for r in conn.execute("PRAGMA table_info(yt_items)")}
        if "has_subtitle" not in existing:
            conn.execute("ALTER TABLE yt_items ADD COLUMN has_subtitle INTEGER DEFAULT 0")
        if "mode" not in existing:
            conn.execute("ALTER TABLE yt_items ADD COLUMN mode TEXT DEFAULT 'mixed'")
        if "media_url" not in existing:
            conn.execute("ALTER TABLE yt_items ADD COLUMN media_url TEXT")
        conn.commit()


def main() -> None:
    targets = sys.argv[1:] if len(sys.argv) > 1 else list(SCHEMAS)
    for name in targets:
        if name not in SCHEMAS:
            print(f"db_init: unknown db '{name}', skipping")
            continue
        init_db(name)


if __name__ == "__main__":
    main()