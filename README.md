# Dewsletter

*dew* + *newsletter* — An RSS Operating System designed for inbox reading.

**Core question: if you only have 15 minutes today and the only thing you can open is your inbox, how does this email deliver maximum value?**

This repo is mid-redesign from an email-schedule-first architecture to a
source/topic/issue-separated one — see [`DESIGN.md`](DESIGN.md) for the
full plan and rationale, and `config/README.md` for what's landed so far.
The sections below describe the **current, working state**.

---

## Issues

| Issue | Schedule (BJT) | Content |
|-------|---------------|---------|
| **Daily** | Every day 04:00 | GitHub · Digest · HN (score > 350) · Billboard chart — full-text articles attached as `out_daily.zip` |
| **Dewsletter Extra** | Same run as Daily | TLDR · Ruanyf Weekly · HelloGitHub — full-text attached as `out_extra.zip` |
| **Dive Weekly** | Saturday 08:00 | Long-form full text: Noahpinion, Wait But Why, The Marginalian, etc. |
| **Zen Weekly** | Sunday 20:00 | sspai, Innei, Bubbles Town, Today I Found Out |
| **Research Weekly** | Friday 08:00 | AI/CS/science/economics papers + arXiv + RAND/Peterson Institute/Epoch AI/Brookings/AI Index/NBER/IFP/Carnegie thinktank reports — title list + PDFs attached as `research.zip` |
| **YouTube Weekly** | Wednesday 08:00 | All channels — title list + subtitle status + `out_yt.zip` (subtitle text) + inline 720p/audio download links |

Research Weekly replaces the old separate Paper Weekly (Friday) + Report
Monthly (1st of month) — merged into one issue and one schedule (Friday),
since they were always the same "research" topic split across two emails
for historical, not content, reasons. Report ingestion moved from monthly
to weekly as a result — thinktank reports now arrive faster.

Any issue with nothing new to send is skipped automatically — no email goes
out, and no workflow failure either (see "Nothing to send" below).

---

## Databases

All databases are tracked by **Git LFS** (see `.gitattributes`). None of
them are attached to emails anymore — see "Zip attachments" below for why.

```
database/
├── content.db   — Daily/Extra/Dive/Zen/Research's paper-topic half:
│                  GitHub, Digest, Billboard, Ruanyf, HelloGitHub, long-form
│                  articles, lifestyle articles, papers+arXiv PDFs — all one
│                  file, one `items` table, distinguished by `source_key`
├── hn.db        — HackerNews (score > 350, via Firebase API)
├── report.db    — Research Weekly's thinktank-report half: title + PDF blob
└── youtube.db   — YouTube: video metadata + subtitle text
```

`content.db` used to be four separate files (`core.db`/`dive.db`/`zen.db`/
`paper.db`) — merged into one, since they were always the same `items`
shape and splitting them by *email* rather than by *data shape* was exactly
the kind of schedule-driven fragmentation this whole redesign is trying to
undo. `report.db` and `youtube.db` stay separate: report.db's PDF blobs are
large, and youtube.db's schema (video_id/channel_id/mode, multiple tables)
is genuinely different, not just historically organized differently.

`content.db`'s `items` table carries:
- `fetched_full` — every entry attempts a full-text fetch regardless of
  `display_mode` (which only controls *rendering*); this records whether
  that fetch actually succeeded, independent of how the item displays —
  it's what gates zip-attachment eligibility.
- `pdf_url`/`pdf_data` — populated for arXiv entries only.
- `source_key` — which `config/sources/rss.yml` entry this row came from
  (e.g. `"noahpinion"`, `"tldr-tech"`). Not the same thing as `feed_key`,
  which is the older, coarser feed-group string (e.g. `"rss.dive"`) —
  several feed groups split across more than one issue (Ruanyf Weekly and
  TLDR both nest under `rss.daily.tech` but go to Extra, not Daily), so
  `feed_key` alone was never reliable for telling rows apart. `source_key`
  is what lets `issues/builder.py` filter a shared table like `content.db`'s
  `items` per-issue — see `config/README.md` for the full story, including
  the one-time backfill needed for pre-merge data (`migrations/migrate_content_db.py`).

Push history is tracked in the `push_log` table per database — content is
never deleted on send, so nothing is lost if a render/send step needs to be
re-run.

---

## Zip attachments

Every issue that has attachable content bundles it into a single zip
instead of attaching a raw database file or many individual files:

| Issue | Zip | Contents |
|-------|-----|----------|
| Daily | `out_daily.zip` | One `.md` per successfully-fetched full-text article |
| Extra | `out_extra.zip` | Same, for TLDR + Ruanyf Weekly |
| Research Weekly | `research.zip` | One `.pdf` per successfully-downloaded arXiv paper or thinktank report |
| YouTube Weekly | `out_yt.zip` | One `.md` per video with subtitle text |

An entry whose fetch/download failed is still listed in the email body —
it's just excluded from the zip rather than causing the whole thing to
fail. `research.zip` also caps total size (`export_pdf_zip`'s
`max_total_bytes`, default 18MB of raw PDF bytes) and omits the overflow
rather than risk exceeding the recipient's mail provider size limit — this
is a direct fix for a real failure where 19 individually-attached PDFs plus
a raw database file blew past Gmail's 25MB limit in one send.

---

## Nothing to send

Every weekly/monthly render script exits early and writes nothing when
there's no new content (`render_X: nothing to send`). Each workflow reads
the subject file with a guard and skips the "Send email" step entirely if
it's missing, rather than sending mail with a blank subject — the
`dawidd6/action-send-mail` action requires a subject, so calling it with an
empty one is a hard workflow failure, not a graceful no-op.

---

## Report scrapers

Only RAND, Peterson Institute, and Epoch AI actually publish RSS feeds
among `report.db`'s sources. Brookings, AI Index (Stanford HAI), NBER,
Institute for Progress, and Carnegie Endowment don't — `scripts/
collectors/scraper.py` scrapes each of these directly instead, then feeds
the result through the same PDF-download/dedup/error-handling path as an
RSS-derived entry (`scripts/processors/report.py`). This runs
automatically whenever `report.db` is a target of `ingest_rss.py` — no
separate workflow step needed.

AI Index and Institute for Progress are implemented. Brookings, NBER, and
Carnegie are explicit stubs (raise `NotImplementedError`, logged to
`report.db`'s `errors` table) — their listing pages need more
site-structure verification than could be done with confidence yet.

arXiv is handled differently again: it has RSS (`rss.arxiv.org`), but its
PDFs are downloaded directly via a predictable `arxiv.org/abs/{id}` ->
`arxiv.org/pdf/{id}` URL pattern (`scripts/processors/paper.py`) rather
than report.db's generic "scrape the landing page for a PDF link"
approach — see `config/sources/rss.yml`'s `arxiv-cs-ai` entry (`pdf: arxiv`).

---

## Configuration

Source config lives in `config/`, not `feeds/*.yaml` anymore (that's kept
on disk as an untouched rollback reference — nothing reads it):

| File | Content |
|------|---------|
| `config/sources/rss.yml` | Every RSS source: how to fetch, not what it's about or who it's for |
| `config/sources/hn.yml` | HackerNews API config |
| `config/sources/youtube.yml` | YouTube channels |
| `config/topics.yml` | What each source is about (`research.papers`, `culture.music`, ...) |
| `config/issues.yml` | What each issue includes, by topic or by explicit source |
| `config/storage.yml` | Which db/table each source's items land in |

See `config/README.md` for the full design, what's real vs. one-time
migration scaffolding, and which issues `issues/builder.py` can and can't
build yet.

Some sources are still `url: FILL_ME` pending a real feed URL (e.g. AQR
Research, Anthropic Research, NIST AI) — `ingest_rss.py` silently skips
these. This is different from `report.db`'s Brookings/AI Index/NBER/
Institute for Progress/Carnegie, which have no RSS to eventually fill in at
all — see "Report scrapers" above.

---

## Display Protocols

| Mode | Used by | Renders | Full-text fetch attempted? |
|------|---------|---------|------------------------------|
| `full` | Dive, Zen, Ruanyf, some Daily sources | Title + full text | Yes |
| `title_excerpt` | Digest, Bandcamp, sspai | Title + first ~180 chars + link | Yes |
| `title_only` | Papers, Reports | Title + source + link | Yes (most abstracts still just store the RSS summary since most sources have no full-article page to fetch) |
| `repo_card` | GitHub Trending, HelloGitHub | Repo name + one-line description | No — never fetched, never zip-eligible |
| `chart_only` | Billboard | Rank table (scraped from billboard.com) | No — not an article |

Full-text fetch success/failure is independent of `display_mode` (see
`fetched_full` above) — `display_mode` only controls how an item renders in
the email body.

---

## Setup

1. Fill remaining `FILL_ME` values in `config/sources/rss.yml`, `config/sources/youtube.yml` with real URLs / channel IDs
2. Set GitHub repository secrets:
   - `SMTP_USER` — Gmail address
   - `SMTP_PASS` — Gmail App Password
   - `TO_EMAIL` — recipient address
   - `IMAP_HOST` — only needed for the Email Download workflow (defaults to `imap.gmail.com`)
3. Enable Git LFS on your repo: `git lfs install`
4. If migrating an existing repo through the db merge: run
   `python migrations/migrate_content_db.py` once (see its own docstring) before the
   first deploy — it merges old `core.db`/`dive.db`/`zen.db`/`paper.db`
   into `content.db` and backfills `source_key`. Safe to re-run.

---

## Local Testing

```bash
pip install feedparser requests trafilatura pyyaml yt-dlp

# Initialize all databases
python scripts/db_init.py

# Test daily ingest + render
python scripts/ingest_rss.py content
python scripts/ingest_hn.py
python scripts/render_daily.py
open out_daily.html
```

`test_local.sh` runs a fuller local pass across every ingest + render
script, seeding a dummy row (with a real `source_key`, so `issues/
builder.py` actually picks it up) into any database that comes back empty
so the render step has something to work with instead of hitting "nothing
to send".

---

## Project Structure

```
dewsletter/
├── config/
│   ├── sources/{rss,hn,youtube}.yml
│   ├── topics.yml
│   ├── issues.yml
│   ├── storage.yml
│   └── README.md              — design notes, what's scaffolding vs permanent
├── feeds/                      — OLD config, untouched rollback reference; not read by any code
├── scripts/
│   ├── config.py               — adapter: reconstructs the old feeds/*.yaml
│   │                              shape from config/, so ingest scripts
│   │                              didn't need to change
│   ├── db_init.py              — create/migrate all databases
│   ├── db_utils.py             — shared read/write helpers for every db
│   ├── ingest_base.py          — shared dedup + concurrency skeleton
│   ├── ingest_rss.py           — thin per-source dispatch (collectors -> processors)
│   ├── collectors/
│   │   ├── rss.py               — raw feedparser fetch
│   │   └── scraper.py           — Billboard + non-RSS thinktank scrapers
│   ├── processors/
│   │   ├── _http.py             — shared fetch_text/fetch_pdf/find_pdf_link
│   │   ├── article.py           — full-text extraction, generic entry storage
│   │   ├── paper.py             — arXiv direct PDF download
│   │   └── report.py            — thinktank landing-page PDF scraping
│   ├── issues/
│   │   └── builder.py           — resolves issues.yml against topics/storage,
│   │                              replaces hand-written get_unpushed() calls
│   ├── ingest_hn.py             — HackerNews via Firebase API
│   ├── ingest_youtube.py        — YouTube subtitle/video/audio ingest
│   ├── tldr_fetch.py            — live TLDR fetch (never persisted)
│   ├── render_base.py           — shared email-shell + zip-export + issue-builder glue
│   ├── render_daily.py
│   ├── render_extra.py          — TLDR / Ruanyf / HelloGitHub
│   ├── render_dive.py
│   ├── render_zen.py
│   ├── render_research.py       — Paper Weekly + Report Monthly, merged
│   ├── render_yt.py
│   ├── release_utils.py         — shared GitHub Release upload helpers
│   ├── upload_yt_release.py     — uploads video/audio to Release; the ONLY thing that ever writes there
│   └── email_download.py        — mailbox-triggered download-to-Release
├── migrations/                   — ONE-TIME scripts, already run against the live repo; kept for reference/rollback
│   ├── migrate_config.py         — feeds/*.yaml -> config/
│   ├── migrate_content_db.py     — old 4 dbs -> content.db + source_key backfill
│   └── migrate_unify_sources.py  — topics.yml+feed_keys.yml+storage.yml -> config/sources/*.yml
├── database/                    — all .db files (Git LFS)
├── schema.sql                   — schema reference (kept in sync by hand with db_init.py)
├── test_local.sh                — local smoke test across every script
├── .gitattributes                — database/*.db → LFS
└── .github/workflows/
    ├── _send-issue.yml           — reusable: dive_weekly + zen_weekly's shared shape
    ├── daily.yml                 — Daily + Extra; also ingests all of content.db
    ├── dive_weekly.yml           — render-only, content.db already fresh via daily.yml
    ├── zen_weekly.yml            — render-only, same reasoning
    ├── research_weekly.yml       — spans content.db + report.db; its own ingest for report.db
    ├── yt_weekly.yml
    └── email_download.yml        — runs every 3 days, not on the issue schedule above
```

