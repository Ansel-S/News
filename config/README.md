# config/

Phases 1–6 (+ scaffolding retirement) of the architecture redesign (see
`/DESIGN.md` at repo root).

## What's here

- `sources/rss.yml`, `sources/hn.yml`, `sources/youtube.yml` — every
  source, flat, with `collector` + fetch-specific fields. No `db`/`issue`
  fields — those don't belong at this layer, see DESIGN.md §2.1.
- `topics.yml` — one `topic` dot-path per source id.
- `issues.yml` — which topics (scoped by `collector`, optionally with an
  `order` hint — see "Daily's display order" below) or explicit source
  ids each issue includes.
- `storage.yml` — which physical db/table a source's items land in.
  Needed because db assignment is a storage/schema-shape concern that
  topic can't safely imply — Bandcamp is `culture.music` but
  lives in `content`, not some hypothetical separate "culture" db. Always
  the ground truth for `db`; never re-derived from topic. (Billboard Hot
  100 is no longer part of this pipeline at all — see "Billboard Hot 100"
  below.)
- `feed_keys.yml` — source id → `feed_key` grouping/display label.
  Started life as `_phase1_legacy_keys.yml`, Phase-1 scaffolding meant to
  be deleted — turned out `render_research.py` has a real, ongoing need
  for a stable feed_key per source (grouping + labels), so it was
  promoted to permanent status and renamed instead.

All Phase 1 scaffolding has since been retired. `_phase1_legacy_group_meta.yml`
(the other former scaffolding file, holding `{db, issue}` per legacy
group) is gone entirely — `db` now comes straight from `storage.yml` and
`issue` is derived via `issues/builder.py`'s own `matched_source_keys()`
(reused, not reimplemented), both computed per-source rather than
per-group. `scripts/config.py`'s `rss_feeds()` / `hn_config()` /
`yt_feeds()` (used by the **ingest** side) no longer read any scaffolding
file at all.

## Daily's display order

`DAILY_ORDER` used to be a dict in `config.py`, keyed by the literal old
`feed_key` string, kept alive specifically because it and any
already-ingested-but-unsent database rows both needed that exact string
preserved. It's gone — display order for Daily's topic groups now lives
directly as an `order` field on `issues.yml`'s `daily` rules (see
`migrate_config.py`'s own `DAILY_ORDER` constant, which only generates
that field — nothing reads a `DAILY_ORDER` dict from `config.py` anymore).
`render_daily.py` groups rows by topic (looked up via `source_key`) and
sorts by this `order` field via `issues/builder.py`'s `topic_order()`.

## `scripts/issues/builder.py` — the real query replacement

`build(issue_name)` replaces the hand-written `get_unpushed(db, issue_type,
...)` call that used to live in `render_base.py`'s `render_simple_digest()`.
It resolves `issues.yml`'s `include` rules against `topics.yml` +
`sources/*.yml` + `storage.yml`, and queries whichever db/table those
sources actually live in — instead of a script hardcoding which db to ask.
Returns `(db_name, row)` pairs, not bare rows — needed since Phase 6,
`research_weekly` genuinely spans two databases (`content.db` + `report.db`)
and `mark_pushed()` needs to know which db each row actually came from.

**Two ways a `(db, table)` target gets resolved**, in order of preference:
1. **Exclusively owned** by the issue (nothing else routes there) — simple
   unfiltered query. No longer common after Phase 5's db merge (only
   `report.db`/`hn.db` still work this way — every `content.db` issue now
   shares that one table with several others).
2. **Shared, filtered by `source_key`** — `content.db`'s `items` table
   holds Daily/Extra/Dive/Zen/Research-topic rows together; each row's
   `source_key` column (added in Phase 6, backfilled for old data by
   `migrate_content_db.py`) is what lets the builder tell them apart. Only
   works for tables that actually have a `source_key` column.

If neither applies, `build()` raises `IssueNotFullyScoped` with a specific,
actionable message rather than silently returning wrong or incomplete data.
Currently only `yt_weekly` hits this — `storage.yml` deliberately excludes
YouTube sources (which table a video lands in is decided per-video by
ingest based on subtitle presence, not by the channel/source config, so a
source-level mapping would be actively wrong there).

**Currently supported**: `daily`, `extra`, `dive_weekly`, `zen_weekly`,
`research_weekly` — all migrated and verified end-to-end (real inserted
rows, correct rendering, correct zip packing where applicable, correct
push-marking against the right db per row, correct "nothing to send" on
re-run). `research_weekly` was the first real test of the builder spanning
two databases in one issue.

## The db merge (Phase 5) and why `source_key` had to follow (Phase 6)

`core.db`/`dive.db`/`zen.db`/`paper.db` merged into one `content.db` —
they were always the same `items` shape, and keeping them split by *email*
rather than by *data shape* was exactly the kind of schedule-driven
fragmentation this whole redesign exists to undo. `report.db` and
`youtube.db` stayed separate (large PDF blobs / genuinely different schema,
not just historical organization).

The merge had a real, non-obvious consequence: before it, `dive_weekly`/
`zen_weekly` were the *only* issues the builder could support, precisely
because each had an exclusive db file. Merging into `content.db` broke that
— suddenly *nothing* exclusively owned `content.items` anymore, the exact
same problem `daily`/`extra` already had. The fix (and the reason this
phase touched the ingest path, not just config): every row written to
`content.db` now carries a `source_key` column, threaded through from
`config/sources/rss.yml`'s `id` field all the way through `ingest_rss.py`
→ `processors/article.py` / `processors/paper.py` → `db_utils.insert_item()`.
`get_unpushed()` gained an optional `source_keys` filter to use it.

Existing (pre-merge) data doesn't have `source_key` — `migrate_content_db.py`
backfills it by matching each row's `source_name` against
`config/sources/rss.yml` (source_name survives verbatim from the original
feed config, see Phase 1's slug-reconstruction fix, so it's a reliable join
key). Rows whose `source_name` doesn't match anything current (a renamed
or removed source) are left with `source_key IS NULL` and reported by name
— they simply won't appear in any issue built via the builder until that's
resolved, rather than being silently dropped or guessed at.

## Research Weekly (Phase 6)

Paper Weekly (Friday) and Report Monthly (1st of month) merged into one
`research_weekly` issue, Friday schedule — this was the explicitly-flagged
open product decision from DESIGN.md §4.4, resolved here. `render_paper.py`
and `render_report.py` were deleted; `render_research.py` replaces both,
pulling `topic: research.papers`-ish content from `content.db` and
`topic: research.think-tanks` from `report.db` in one issue, combining
both into a single `research.zip`.

Report ingestion moved from `report_monthly.yml`'s monthly cadence to
`research_weekly.yml`'s weekly one — a deliberate side effect (thinktank
reports now arrive faster), not an accident of the merge.

## Billboard Hot 100

Not part of this config layer at all. `config/sources/rss.yml` used to
carry a `billboard-hot-100` entry with `url: FILL_ME` (billboard.com has
no chart RSS feed) — `ingest_rss.py` silently skipped it forever, and a
regex-based HTML scraper in `collectors/scraper.py` was the standing,
never-actually-wired attempt to work around that.

Both are gone. Billboard Hot 100 is now a standalone monthly send —
`scripts/render/render_billboard.py` + `.github/workflows/
billboard_monthly.yml` — using the Parse.bot billboard.com scraper API
(`PARSE_API_KEY` secret). It fetches live and sends rank/title/artist
only; nothing is persisted to any database, so it needed no `db`/`topic`/
`storage` entry here in the first place.

## Why db/issue are copied instead of derived from topic

An earlier draft tried deriving `db` and `issue` from each source's
`topic` at read time. Two ways that went wrong, both fixed by copying the
ground truth at migration time instead:

- **Topic doesn't imply db.** Billboard/Bandcamp are `topic:
  culture.music` but their db is `content`, not some hypothetical separate
  culture db. Topic answers "what is this," db answers "which sqlite
  file" — there was never a rule linking the two, so no rule can be safely
  invented after the fact.
- **Sources sharing an old group can route to different issues.**
  GitHub Trending Weekly and HelloGitHub both lived under the old
  `rss.daily.github` group, but only HelloGitHub goes to Extra (matched
  by `source_name`, not by group). Grouping by topic-derived issue instead
  of by the original group silently collapsed both sources onto whichever
  one was computed last.

## How this was generated

`/migrate_config.py` (repo root) reads `feeds/*.yaml` and writes
everything in this directory. `feeds/*.yaml` itself is untouched — kept on
disk as a rollback reference, not read by any code anymore. Re-run the
script any time `feeds/*.yaml` changes upstream of this migration landing;
it's idempotent and mechanical except for `TOPIC_MAP` / `YT_TOPIC_MAP` /
`SOURCE_TOPIC_OVERRIDE` / `DB_MERGE` / `ISSUE_PASSTHROUGH` (the topic,
db-merge, and issue-merge assignments), which are the hand-authored
judgment calls in the pipeline.

`/migrate_content_db.py` (repo root) is the separate, ONE-TIME data
migration that actually moves real accumulated rows from the four old db
files into `content.db` and backfills `source_key` — see its own
docstring for the full idempotency/safety story.

## Next steps (Phase 4 partial, see DESIGN.md §6/§10)

`daily.yml` and `yt_weekly.yml` remain their own dedicated workflow files
— genuinely different shape (daily's second Extra send-cycle + Release
uploads; yt_weekly's ffmpeg/yt-dlp deps + different ingest signature).
`research_weekly.yml` is also its own file, not run through
`_send-issue.yml`, since it spans two databases with different ingest
needs for each.

`yt_weekly` remains genuinely unsupported by `issues/builder.py` — YouTube
sources aren't in `storage.yml` at all (per-video table assignment, not
per-source, see storage.yml's own header). Nothing currently blocks this
from changing if a real need arises; it just hasn't been necessary yet
since `yt_weekly.yml` renders directly from `youtube.db` without going
through the builder.
