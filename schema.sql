-- schema.sql
-- Dewsletter — all database schemas
-- Run via db_init.py which selects the relevant tables per db

-- ── core.db / dive.db / zen.db / paper.db ───────────────────────────────────
-- paper.db stores title + abstract (content column) + original link
-- full text is NOT stored for papers; abstract only

CREATE TABLE IF NOT EXISTS items (
    id           TEXT PRIMARY KEY,   -- sha256(source_id)
    source_id    TEXT NOT NULL,      -- original URL (dedup key)
    feed_key     TEXT NOT NULL,      -- e.g. "rss.daily.tech"
    source_name  TEXT NOT NULL,      -- e.g. "TLDR Tech"
    display_mode TEXT NOT NULL,      -- full | title_excerpt | title_only | repo_card | chart_only
    title        TEXT,
    content      TEXT,               -- full text (core/dive/zen) or abstract (paper)
    created_at   TEXT,               -- original publish time ISO8601
    ingested_at  TEXT NOT NULL,      -- ingest time ISO8601
    word_count   INTEGER DEFAULT 0,
    read_minutes INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS push_log (
    item_id    TEXT NOT NULL,
    issue_type TEXT NOT NULL,        -- daily | dive_weekly | zen_weekly | paper_weekly | report_monthly | yt_weekly
    issue_id   TEXT NOT NULL,        -- run_id of the sending workflow
    pushed_at  TEXT NOT NULL,
    PRIMARY KEY (item_id, issue_type)
);

CREATE TABLE IF NOT EXISTS errors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    source_id  TEXT NOT NULL,
    stage      TEXT NOT NULL,        -- fetch | parse | store
    error_type TEXT NOT NULL,        -- timeout | network | format | unknown
    message    TEXT,
    created_at TEXT NOT NULL
);

-- ── report.db ────────────────────────────────────────────────────────────────
-- Stores the PDF binary as a blob alongside metadata.
-- title_only shown in email; PDF attached to report_monthly issue.

CREATE TABLE IF NOT EXISTS reports (
    id          TEXT PRIMARY KEY,    -- sha256(source_id)
    source_id   TEXT NOT NULL,       -- original URL
    feed_key    TEXT NOT NULL,
    source_name TEXT NOT NULL,
    title       TEXT,
    pdf_url     TEXT,                -- direct PDF link if found
    pdf_data    BLOB,                -- raw PDF bytes
    created_at  TEXT,
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS push_log (
    item_id    TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    issue_id   TEXT NOT NULL,
    pushed_at  TEXT NOT NULL,
    PRIMARY KEY (item_id, issue_type)
);

CREATE TABLE IF NOT EXISTS errors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    source_id  TEXT NOT NULL,
    stage      TEXT NOT NULL,
    error_type TEXT NOT NULL,
    message    TEXT,
    created_at TEXT NOT NULL
);

-- ── hn.db ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS hn_items (
    id          TEXT PRIMARY KEY,    -- HN item id as text
    source_id   TEXT NOT NULL,       -- https://news.ycombinator.com/item?id=<id>
    title       TEXT NOT NULL,
    url         TEXT,                -- external link (null for Ask HN etc.)
    score       INTEGER NOT NULL,
    by          TEXT,
    descendants INTEGER DEFAULT 0,   -- comment count
    created_at  TEXT NOT NULL,       -- ISO8601
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS push_log (
    item_id    TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    issue_id   TEXT NOT NULL,
    pushed_at  TEXT NOT NULL,
    PRIMARY KEY (item_id, issue_type)
);

-- ── youtube.db ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS yt_items (
    id           TEXT PRIMARY KEY,   -- sha256(video_url)
    video_url    TEXT NOT NULL,
    video_id     TEXT NOT NULL,
    channel_id   TEXT NOT NULL,
    channel_name TEXT NOT NULL,
    feed_key     TEXT NOT NULL,      -- e.g. "yt.daily.tech"
    title        TEXT,
    subtitle     TEXT,               -- cleaned subtitle text
    published_at TEXT,
    ingested_at  TEXT NOT NULL,
    has_subtitle INTEGER DEFAULT 0,  -- 0 | 1
    mode         TEXT DEFAULT 'mixed',  -- subtitle | video | mixed | audio
    media_url    TEXT              -- GitHub Release asset URL, if a low-res
                                    -- video/audio file was uploaded for this video
);

CREATE TABLE IF NOT EXISTS push_log (
    item_id    TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    issue_id   TEXT NOT NULL,
    pushed_at  TEXT NOT NULL,
    PRIMARY KEY (item_id, issue_type)
);

CREATE TABLE IF NOT EXISTS errors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    source_id  TEXT NOT NULL,
    stage      TEXT NOT NULL,
    error_type TEXT NOT NULL,
    message    TEXT,
    created_at TEXT NOT NULL
);
