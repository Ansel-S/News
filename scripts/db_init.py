"""
db_init.py — Initialize / migrate all databases
Usage:
  python scripts/db_init.py              # all databases
  python scripts/db_init.py core hn      # specific databases
"""
from __future__ import annotations
import json as _json
import sqlite3
import sys
from pathlib import Path

ROOT   = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "database"

# Each db gets its own explicit CREATE statements — no schema file parsing.
# All main tables share the `items` shape (id, source_id, feed_key,
# source_name, display_mode, title, content, created_at, ingested_at,
# word_count, read_minutes) plus a few table-specific extra columns — see
# schema.sql for the full rationale.
_ITEMS_CORE_COLS = """
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
"""

SCHEMAS: dict[str, list[str]] = {
    "core": [
        f"CREATE TABLE IF NOT EXISTS items ({_ITEMS_CORE_COLS})",
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
        f"""CREATE TABLE IF NOT EXISTS report_items ({_ITEMS_CORE_COLS},
            pdf_url  TEXT,
            pdf_data BLOB
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
        f"""CREATE TABLE IF NOT EXISTS hn_items ({_ITEMS_CORE_COLS},
            external_url TEXT,
            score        INTEGER NOT NULL,
            by           TEXT,
            descendants  INTEGER DEFAULT 0
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
        f"""CREATE TABLE IF NOT EXISTS yt_items ({_ITEMS_CORE_COLS},
            video_id   TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            mode       TEXT DEFAULT 'mixed'
        )""",
        f"""CREATE TABLE IF NOT EXISTS yt_media_items ({_ITEMS_CORE_COLS},
            video_id   TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            mode       TEXT DEFAULT 'video'
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
    _migrate_before_create(conn, name)
    for stmt in SCHEMAS[name]:
        conn.execute(stmt)
    conn.commit()
    _migrate_after_create(conn, name)
    conn.close()
    print(f"db_init: {name}.db OK")


def _table_cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _migrate_before_create(conn: sqlite3.Connection, name: str) -> None:
    """Migrations that need to run on an OLD table shape before the new
    CREATE TABLE IF NOT EXISTS statements would otherwise leave it alone
    (since the table already exists, the CREATE is a no-op)."""

    if name == "report" and _table_exists(conn, "reports") and not _table_exists(conn, "report_items"):
        print("db_init: migrating report.db 'reports' -> 'report_items'...")
        conn.execute(f"CREATE TABLE report_items ({_ITEMS_CORE_COLS}, pdf_url TEXT, pdf_data BLOB)")
        old_cols = _table_cols(conn, "reports")
        old_rows = conn.execute("SELECT * FROM reports").fetchall()
        col_names = [d[0] for d in conn.execute("SELECT * FROM reports LIMIT 1").description] \
            if old_rows else list(old_cols)
        for row in old_rows:
            r = dict(zip(col_names, row))
            conn.execute(
                """INSERT OR IGNORE INTO report_items
                   (id, source_id, feed_key, source_name, display_mode, title,
                    content, created_at, ingested_at, word_count, read_minutes,
                    pdf_url, pdf_data)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["id"], r["source_id"], r["feed_key"], r["source_name"], "title_only",
                 r.get("title"), None, r.get("created_at"), r.get("ingested_at", ""), 0, 0,
                 r.get("pdf_url"), r.get("pdf_data")),
            )
        conn.execute("DROP TABLE reports")
        conn.commit()
        print(f"db_init: migrated {len(old_rows)} report.db rows")

    if name == "hn" and _table_exists(conn, "hn_items"):
        cols = _table_cols(conn, "hn_items")
        if "url" in cols and "external_url" not in cols:
            print("db_init: migrating hn.db 'hn_items' to items-shape column names...")
            conn.execute("ALTER TABLE hn_items RENAME TO hn_items_old")
            conn.execute(f"""CREATE TABLE hn_items ({_ITEMS_CORE_COLS},
                external_url TEXT, score INTEGER NOT NULL, by TEXT, descendants INTEGER DEFAULT 0
            )""")
            old_rows = conn.execute("SELECT * FROM hn_items_old").fetchall()
            col_names = [d[0] for d in conn.execute("SELECT * FROM hn_items_old LIMIT 1").description] \
                if old_rows else []
            for row in old_rows:
                r = dict(zip(col_names, row))
                source_id = f"https://news.ycombinator.com/item?id={r['id']}"
                conn.execute(
                    """INSERT OR IGNORE INTO hn_items
                       (id, source_id, feed_key, source_name, display_mode, title, content,
                        created_at, ingested_at, word_count, read_minutes,
                        external_url, score, by, descendants)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r["id"], source_id, "hn", "Hacker News", "title_only", r["title"], None,
                     r["created_at"], r.get("ingested_at", ""), 0, 0,
                     r.get("url"), r["score"], r.get("by"), r.get("descendants", 0)),
                )
            conn.execute("DROP TABLE hn_items_old")
            conn.commit()
            print(f"db_init: migrated {len(old_rows)} hn.db rows")

    if name == "youtube" and _table_exists(conn, "yt_items"):
        cols = _table_cols(conn, "yt_items")
        needs_migration = "video_url" in cols or "has_subtitle" in cols or "media_url" in cols
        if needs_migration:
            print("db_init: migrating youtube.db 'yt_items' to items-shape column names...")
            conn.execute("ALTER TABLE yt_items RENAME TO yt_items_old")
            conn.execute(f"""CREATE TABLE yt_items ({_ITEMS_CORE_COLS},
                video_id TEXT NOT NULL, channel_id TEXT NOT NULL, mode TEXT DEFAULT 'mixed'
            )""")
            if not _table_exists(conn, "yt_seen"):
                conn.execute("""CREATE TABLE yt_seen (
                    id TEXT PRIMARY KEY, video_url TEXT NOT NULL,
                    video_id TEXT NOT NULL, ingested_at TEXT NOT NULL
                )""")
            if not _table_exists(conn, "yt_media_items"):
                conn.execute(f"""CREATE TABLE yt_media_items ({_ITEMS_CORE_COLS},
                    video_id TEXT NOT NULL, channel_id TEXT NOT NULL, mode TEXT DEFAULT 'video'
                )""")
            if not _table_exists(conn, "yt_media"):
                conn.execute("""CREATE TABLE yt_media (
                    video_id TEXT NOT NULL, kind TEXT NOT NULL, media_url TEXT NOT NULL,
                    ingested_at TEXT NOT NULL, PRIMARY KEY (video_id, kind)
                )""")

            old_rows = conn.execute("SELECT * FROM yt_items_old").fetchall()
            col_names = [d[0] for d in conn.execute("SELECT * FROM yt_items_old LIMIT 1").description] \
                if old_rows else []
            for row in old_rows:
                r = dict(zip(col_names, row))
                video_url = r.get("video_url") or r.get("source_id")
                channel_name = r.get("channel_name") or r.get("source_name")
                subtitle = r.get("subtitle") or r.get("content")
                published_at = r.get("published_at") or r.get("created_at")

                conn.execute(
                    "INSERT OR IGNORE INTO yt_seen (id, video_url, video_id, ingested_at) VALUES (?,?,?,?)",
                    (r["id"], video_url, r["video_id"], r.get("ingested_at", "")),
                )
                if subtitle:
                    conn.execute(
                        """INSERT OR IGNORE INTO yt_items
                           (id, source_id, feed_key, source_name, display_mode, title,
                            content, created_at, ingested_at, word_count, read_minutes,
                            video_id, channel_id, mode)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (r["id"], video_url, r["feed_key"], channel_name, "title_excerpt",
                         r.get("title"), subtitle, published_at, r.get("ingested_at", ""), 0, 0,
                         r["video_id"], r["channel_id"], r.get("mode", "mixed")),
                    )
                else:
                    # No subtitle in the old row — goes to yt_media_items instead
                    # of being silently dropped, so the title + eventual
                    # download link still show up in the weekly email.
                    conn.execute(
                        """INSERT OR IGNORE INTO yt_media_items
                           (id, source_id, feed_key, source_name, display_mode, title,
                            content, created_at, ingested_at, word_count, read_minutes,
                            video_id, channel_id, mode)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (r["id"], video_url, r["feed_key"], channel_name, "title_only",
                         r.get("title"), None, published_at, r.get("ingested_at", ""), 0, 0,
                         r["video_id"], r["channel_id"], r.get("mode", "video")),
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
            print(f"db_init: migrated {len(old_rows)} youtube.db rows to the items-shaped schema")


def _migrate_after_create(conn: sqlite3.Connection, name: str) -> None:
    """Additive column migrations — safe to run every time, no-op if the
    column already exists. Runs after CREATE TABLE IF NOT EXISTS so brand-new
    databases already have every column and these are all no-ops for them."""
    if name in ("core", "dive", "zen", "paper"):
        existing = _table_cols(conn, "items")
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


def main() -> None:
    targets = sys.argv[1:] if len(sys.argv) > 1 else list(SCHEMAS)
    for name in targets:
        if name not in SCHEMAS:
            print(f"db_init: unknown db '{name}', skipping")
            continue
        init_db(name)


if __name__ == "__main__":
    main()
