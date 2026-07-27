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
        """CREATE TABLE IF NOT EXISTS yt_seen (
            id          TEXT PRIMARY KEY,
            video_url   TEXT NOT NULL,
            video_id    TEXT NOT NULL,
            ingested_at TEXT NOT NULL DEFAULT ''
        )""",
        """CREATE TABLE IF NOT EXISTS yt_items (
            id           TEXT PRIMARY KEY,
            video_url    TEXT NOT NULL,
            video_id     TEXT NOT NULL,
            channel_id   TEXT NOT NULL,
            channel_name TEXT NOT NULL,
            feed_key     TEXT NOT NULL,
            title        TEXT,
            subtitle     TEXT NOT NULL,
            published_at TEXT,
            ingested_at  TEXT NOT NULL DEFAULT '',
            mode         TEXT DEFAULT 'mixed'
        )""",
        """CREATE TABLE IF NOT EXISTS yt_media_items (
            id           TEXT PRIMARY KEY,
            video_url    TEXT NOT NULL,
            video_id     TEXT NOT NULL,
            channel_id   TEXT NOT NULL,
            channel_name TEXT NOT NULL,
            feed_key     TEXT NOT NULL,
            title        TEXT,
            published_at TEXT,
            ingested_at  TEXT NOT NULL DEFAULT '',
            mode         TEXT DEFAULT 'video'
        )""",
        """CREATE TABLE IF NOT EXISTS yt_media (
            video_id    TEXT NOT NULL,
            kind        TEXT NOT NULL,
            media_url   TEXT NOT NULL,
            ingested_at TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (video_id, kind)
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
        is_old_schema = "has_subtitle" in existing or "media_url" in existing
        if is_old_schema:
            print("db_init: migrating youtube.db from old single-table schema...")
            old_rows = conn.execute("SELECT * FROM yt_items").fetchall()
            col_names = [d[0] for d in conn.execute("SELECT * FROM yt_items LIMIT 1").description] \
                if old_rows else []

            conn.execute("ALTER TABLE yt_items RENAME TO yt_items_old")
            conn.execute("""CREATE TABLE yt_items (
                id TEXT PRIMARY KEY, video_url TEXT NOT NULL, video_id TEXT NOT NULL,
                channel_id TEXT NOT NULL, channel_name TEXT NOT NULL, feed_key TEXT NOT NULL,
                title TEXT, subtitle TEXT NOT NULL, published_at TEXT,
                ingested_at TEXT NOT NULL DEFAULT '', mode TEXT DEFAULT 'mixed'
            )""")

            import json as _json
            for row in old_rows:
                r = dict(zip(col_names, row))
                # Every previously-seen video goes into yt_seen regardless of subtitle
                conn.execute(
                    "INSERT OR IGNORE INTO yt_seen (id, video_url, video_id, ingested_at) VALUES (?,?,?,?)",
                    (r["id"], r["video_url"], r["video_id"], r.get("ingested_at", "")),
                )
                # Only rows that actually had subtitle text move to the new yt_items
                if r.get("subtitle"):
                    conn.execute(
                        """INSERT OR IGNORE INTO yt_items
                           (id, video_url, video_id, channel_id, channel_name, feed_key,
                            title, subtitle, published_at, ingested_at, mode)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (r["id"], r["video_url"], r["video_id"], r["channel_id"], r["channel_name"],
                         r["feed_key"], r["title"], r["subtitle"], r["published_at"],
                         r.get("ingested_at", ""), r.get("mode", "mixed")),
                    )
                # media_url used to be a JSON blob like {"video": url, "audio": url}
                raw_media = r.get("media_url")
                if raw_media:
                    try:
                        media_dict = _json.loads(raw_media)
                    except (ValueError, TypeError):
                        media_dict = {}
                    for kind, url in media_dict.items():
                        conn.execute(
                            """INSERT OR IGNORE INTO yt_media (video_id, kind, media_url, ingested_at)
                               VALUES (?,?,?,?)""",
                            (r["video_id"], kind, url, r.get("ingested_at", "")),
                        )

            conn.execute("DROP TABLE yt_items_old")
            conn.commit()
            print(f"db_init: migrated {len(old_rows)} youtube.db rows to the new 3-table schema")


def main() -> None:
    targets = sys.argv[1:] if len(sys.argv) > 1 else list(SCHEMAS)
    for name in targets:
        if name not in SCHEMAS:
            print(f"db_init: unknown db '{name}', skipping")
            continue
        init_db(name)


if __name__ == "__main__":
    main()