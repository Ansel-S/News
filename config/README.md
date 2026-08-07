# config/

Phase 1 of the architecture redesign (see `/DESIGN.md` at repo root).

## What's real vs. scaffolding

**Real, forward-looking (part of the target design):**
- `sources/rss.yml`, `sources/hn.yml`, `sources/youtube.yml` — every
  source, flat, with `collector` + fetch-specific fields. No `db`/`issue`
  fields — those don't belong at this layer, see DESIGN.md §2.1.
- `topics.yml` — one `topic` dot-path per source id.
- `issues.yml` — which topics (scoped by `collector`) or explicit source
  ids each issue includes.

**Phase-1-only scaffolding (delete in Phase 3):**
- `_phase1_legacy_keys.yml` — source id → the original `feeds/*.yaml`
  group `key` string.
- `_phase1_legacy_group_meta.yml` — original group key → `{db, issue}`.

`scripts/config.py`'s `rss_feeds()` / `hn_config()` / `yt_feeds()` read
these two scaffolding files to reconstruct the *exact* old-shaped output
(same `key`, `db`, `issue` strings as before), so every other script in
this repo — `ingest_rss.py`, `ingest_hn.py`, `ingest_youtube.py`, every
`render_*.py` — needed zero changes for this migration. They still don't
know `config/` exists.

## Why db/issue are copied instead of derived from topic

An earlier draft tried deriving `db` and `issue` from each source's
`topic` at read time. Two ways that went wrong, both now fixed by copying
the ground truth at migration time instead:

- **Topic doesn't imply db.** Billboard/Bandcamp are `topic:
  culture.music` but their db is `core`, not `zen`. Topic answers "what
  is this," db answered "which sqlite file" — the old system had no rule
  linking the two, so no rule can be safely invented after the fact.
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
`SOURCE_TOPIC_OVERRIDE` (the topic assignments), which are the one hand-
authored judgment call in the whole pipeline.

Verified byte-for-byte equivalent to the old `feeds/*.yaml` output before
being committed: all 39 RSS sources, HN's config, and all 69 YouTube
channels compared field-by-field (`url`, `display_mode`, `no_store`, `db`,
`issue`) between the old direct-yaml-read path and the new adapter path —
zero mismatches.

## Next steps (Phase 2+, see DESIGN.md §10)

Phase 2 splits `ingest_rss.py` into `collectors/` + `processors/`, still
behavior-preserving. Phase 3 replaces this adapter with a real
topic-matching issue builder and deletes the two `_phase1_*` files.
