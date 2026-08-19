-- schema.sql
-- Dewsletter — all database schemas
-- Run via db_init.py which selects the relevant tables per db
--
-- DESIGN: every db's main table is called `items` (or `report_items` /
-- `hn_items` / `yt_items` — same shape, different name) with the SAME core
-- columns (id, source_id, feed_key, source_name, display_mode, title,
-- content, created_at, ingested_at). This is what lets db_utils.py expose
-- ONE set of functions -- get_unpushed(db, issue_type), mark_pushed(db, id,
-- ...) -- for every db, instead of a _yt/_reports/_hn variant per db. Each
-- db then adds a few of its own extra columns for whatever it uniquely
-- needs (video_id, pdf_data, score, etc). `push_log` and `errors` are
-- identical everywhere.

-- -- content.db -----------------------------------------------------------
-- Merged core.db + dive.db + zen.db + paper.db (architecture redesign
-- Phase 5, see /DESIGN.md §5) — these four were always the same `items`
-- shape; splitting them by *email* rather than *data shape* was exactly
-- the kind of schedule-driven fragmentation the redesign exists to undo.

CREATE TABLE IF NOT EXISTS items (
    id           TEXT PRIMARY KEY,   -- sha256(source_id)
    source_id    TEXT NOT NULL,      -- original URL (dedup key)
    feed_key     TEXT NOT NULL,      -- grouping/display label, e.g. "rss.daily.tech"
                                      -- (config/feed_keys.yml) -- NOT the join
                                      -- key issues/builder.py filters on
    source_name  TEXT NOT NULL,      -- e.g. "TLDR Tech"
    display_mode TEXT NOT NULL,      -- full | title_excerpt | title_only | repo_card | chart_only
    title        TEXT,
    content      TEXT,               -- full text if fetched_full, else RSS summary/abstract
    created_at   TEXT,               -- original publish time ISO8601
    ingested_at  TEXT NOT NULL,      -- ingest time ISO8601
    word_count   INTEGER DEFAULT 0,
    read_minutes INTEGER DEFAULT 0,
    fetched_full INTEGER NOT NULL DEFAULT 0,  -- 1 if content is a successful full-text
                                               -- fetch (independent of display_mode);
                                               -- gates zip-attachment eligibility.
                                               -- Always 0 for chart_only/repo_card.
    pdf_url      TEXT,               -- arXiv only (rss.paper.arxiv entries) -- the
                                      -- arxiv.org/pdf/{id} URL, set only on success
    pdf_data     BLOB,               -- arXiv only -- raw PDF bytes, NULL if download failed
    source_key   TEXT                -- config/sources/rss.yml's `id` field for this
                                      -- row's source (e.g. "noahpinion", "tldr-tech").
                                      -- THE join key issues/builder.py filters
                                      -- shared-table queries on -- feed_key alone
                                      -- can't tell Daily/Extra/Dive/Zen/Research
                                      -- rows apart, several old feed_key groups
                                      -- split across more than one issue. Indexed
                                      -- (idx_items_source_key). NULL for rows
                                      -- written before this column existed --
                                      -- see migrate_content_db.py's backfill step.
);

CREATE INDEX IF NOT EXISTS idx_items_source_key ON items(source_key);

CREATE TABLE IF NOT EXISTS push_log (
    item_id    TEXT NOT NULL,
    issue_type TEXT NOT NULL,        -- daily | extra_daily | dive_weekly | zen_weekly | research_weekly | yt_weekly
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

-- -- report.db ---------------------------------------------------------------
-- Deliberately NOT merged into content.db (Phase 5) -- PDF blobs here are
-- large, and mixing them into content.db's everyday query path would slow
-- it down for no benefit. No source_key column: report.db is exclusively
-- used by research_weekly (nothing else routes here), so issues/builder.py
-- never needs to filter it by source -- see config/storage.yml.
--
-- Populated two ways: RAND/Peterson Institute/Epoch AI have real RSS feeds
-- (scripts/collectors/rss.py); Brookings/AI Index/NBER/Institute for
-- Progress/Carnegie don't, and are scraped directly instead
-- (scripts/collectors/scraper.py) -- both paths converge on
-- scripts/processors/report.py, which fetches each entry's landing page
-- and scrapes it for a PDF link. display_mode is always 'title_only';
-- content holds a short description if available (may be empty -- the PDF
-- itself is the payload).

CREATE TABLE IF NOT EXISTS report_items (
    id           TEXT PRIMARY KEY,
    source_id    TEXT NOT NULL,
    feed_key     TEXT NOT NULL,
    source_name  TEXT NOT NULL,
    display_mode TEXT NOT NULL DEFAULT 'title_only',
    title        TEXT,
    content      TEXT,
    created_at   TEXT,
    ingested_at  TEXT NOT NULL,
    word_count   INTEGER DEFAULT 0,
    read_minutes INTEGER DEFAULT 0,
    pdf_url      TEXT,
    pdf_data     BLOB
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

-- -- hn.db ---------------------------------------------------------------
-- Same `items` shape, plus three HN-specific columns: score, by, descendants.
-- content is left empty (HN items are title_only); source_id doubles as the
-- HN discussion-page URL, with the external link (if any) in a dedicated
-- `external_url` column instead of overloading source_id/content. No
-- source_key needed -- single source ("hackernews"), exclusively daily.

CREATE TABLE IF NOT EXISTS hn_items (
    id           TEXT PRIMARY KEY,   -- HN item id as text
    source_id    TEXT NOT NULL,      -- https://news.ycombinator.com/item?id=<id>
    feed_key     TEXT NOT NULL DEFAULT 'hn',
    source_name  TEXT NOT NULL DEFAULT 'Hacker News',
    display_mode TEXT NOT NULL DEFAULT 'title_only',
    title        TEXT NOT NULL,
    content      TEXT,
    created_at   TEXT NOT NULL,      -- ISO8601
    ingested_at  TEXT NOT NULL,
    word_count   INTEGER DEFAULT 0,
    read_minutes INTEGER DEFAULT 0,
    external_url TEXT,               -- external link (null for Ask HN etc.)
    score        INTEGER NOT NULL,
    by           TEXT,
    descendants  INTEGER DEFAULT 0   -- comment count
);

CREATE TABLE IF NOT EXISTS push_log (
    item_id    TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    issue_id   TEXT NOT NULL,
    pushed_at  TEXT NOT NULL,
    PRIMARY KEY (item_id, issue_type)
);

-- -- youtube.db ---------------------------------------------------------------
-- Split into tables to keep the db small and each reader query targeted.
-- Not part of the Phase 5 merge, and not routed through issues/builder.py
-- (config/storage.yml deliberately excludes YouTube -- which table a video
-- lands in is decided per-VIDEO at ingest time by whether a subtitle was
-- found, not by the channel/source config, so a source-level mapping would
-- be actively wrong).
--   yt_seen  -- dedup only, every processed video regardless of mode/content.
--              Tiny rows (a hash + id + timestamp), safe to grow unbounded.
--              NOT shaped like `items` -- it's a pure internal dedup index,
--              never rendered, so there's nothing to gain from matching the
--              items shape here.
--   yt_items -- videos that produced subtitle text (content = subtitle text).
--              Same `items` shape as content.db, plus video_id and
--              channel_id. Read by render_yt.py for the weekly email + zip.
--   yt_media_items -- videos from video/audio-only channels with NO subtitle
--              (content is NULL/empty here) -- still need a title +
--              download-link row in the weekly email. Same `items` shape +
--              video_id/channel_id, disjoint from yt_items.
--   yt_media -- one row per (video, kind) low-res video/audio Release
--              upload; joined by video_id from either table above.

CREATE TABLE IF NOT EXISTS yt_seen (
    id          TEXT PRIMARY KEY,   -- sha256(video_url)
    video_url   TEXT NOT NULL,
    video_id    TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS yt_items (
    id           TEXT PRIMARY KEY,   -- sha256(source_id)
    source_id    TEXT NOT NULL,      -- video_url (dedup key, matches items convention)
    feed_key     TEXT NOT NULL,      -- e.g. "yt.daily.tech"
    source_name  TEXT NOT NULL,      -- channel_name
    display_mode TEXT NOT NULL DEFAULT 'title_excerpt',
    title        TEXT,
    content      TEXT NOT NULL,      -- cleaned subtitle text (always non-empty here)
    created_at   TEXT,               -- published_at
    ingested_at  TEXT NOT NULL,
    word_count   INTEGER DEFAULT 0,
    read_minutes INTEGER DEFAULT 0,
    fetched_full INTEGER NOT NULL DEFAULT 1,  -- always 1: a yt_items row only
                                               -- exists when a subtitle was
                                               -- found -- see db_utils.insert_yt()
    video_id     TEXT NOT NULL,
    channel_id   TEXT NOT NULL,
    mode         TEXT DEFAULT 'mixed'  -- subtitle | video | mixed | audio | comma-joined combo
);

CREATE TABLE IF NOT EXISTS yt_media_items (
    id           TEXT PRIMARY KEY,   -- sha256(source_id), same hash scheme as yt_items
    source_id    TEXT NOT NULL,      -- video_url
    feed_key     TEXT NOT NULL,
    source_name  TEXT NOT NULL,      -- channel_name
    display_mode TEXT NOT NULL DEFAULT 'title_only',
    title        TEXT,
    content      TEXT,               -- always NULL/empty here -- no subtitle text
    created_at   TEXT,               -- published_at
    ingested_at  TEXT NOT NULL,
    word_count   INTEGER DEFAULT 0,
    read_minutes INTEGER DEFAULT 0,
    fetched_full INTEGER NOT NULL DEFAULT 0,  -- always 0: no subtitle text captured
    video_id     TEXT NOT NULL,
    channel_id   TEXT NOT NULL,
    mode         TEXT DEFAULT 'video'
);

CREATE TABLE IF NOT EXISTS yt_media (
    video_id    TEXT NOT NULL,
    kind        TEXT NOT NULL,        -- 'video' | 'audio'
    media_url   TEXT NOT NULL,        -- GitHub Release asset URL
    ingested_at TEXT NOT NULL,
    PRIMARY KEY (video_id, kind)
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

-- -- handled.db ---------------------------------------------------------------
-- Backs scripts/email_download.py. Not items-shaped: a "request" is a
-- one-off download task keyed by UUID, not a feed item.

CREATE TABLE IF NOT EXISTS requests (
    uuid         TEXT PRIMARY KEY,
    url          TEXT NOT NULL,
    first_seen   TEXT NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_attempt TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',
    error        TEXT,
    filename     TEXT,
    asset_url    TEXT
);
