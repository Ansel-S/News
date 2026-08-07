# Dewsletter

*dew* + *newsletter* — An RSS Operating System designed for inbox reading.

**Core question: if you only have 15 minutes today and the only thing you can open is your inbox, how does this email deliver maximum value?**

This repo also hosts [`geoip/`](geoip/) — a small, unrelated CN IP routing
list generator that happens to live here for convenience. See
`geoip/README.md`; it shares no code, schedule, or dependencies with the
newsletter system documented below.

---

## Issues

| Issue | Schedule (BJT) | Content |
|-------|---------------|---------|
| **Daily** | Every day 04:00 | GitHub · Digest · HN (score > 350) · Billboard chart — full-text articles attached as `out_daily.zip` |
| **Dewsletter Extra** | Same run as Daily | TLDR · Ruanyf Weekly · HelloGitHub — full-text attached as `out_extra.zip` |
| **Dive Weekly** | Saturday 08:00 | Long-form full text: Noahpinion, Wait But Why, The Marginalian, etc. |
| **Zen Weekly** | Sunday 20:00 | sspai, Innei, Bubbles Town, Today I Found Out |
| **Paper Weekly** | Friday 08:00 | Title list: AI research, CS, science, economics papers — arXiv PDFs attached as `papers.zip` |
| **Report Monthly** | 1st of month 08:00 | RAND, Peterson Institute, Epoch AI (RSS) + Brookings, AI Index, NBER, Institute for Progress, Carnegie (scraped) — title list + PDFs attached as `reports.zip` |
| **YouTube Weekly** | Wednesday 08:00 | All channels — title list + subtitle status + `out_yt.zip` (subtitle text) + inline 720p/audio download links |

Any issue with nothing new to send is skipped automatically — no email goes
out, and no workflow failure either (see "Nothing to send" below).

---

## Databases

All databases are tracked by **Git LFS** (see `.gitattributes`). None of
them are attached to emails anymore — see "Zip attachments" below for why.

```
database/
├── core.db      — Daily/Extra: GitHub, Digest, Billboard, Ruanyf, HelloGitHub
├── hn.db        — HackerNews (score > 350, via Firebase API)
├── dive.db      — Long-form articles (full text)
├── zen.db       — Lifestyle articles (full text)
├── paper.db     — Papers: title + abstract, plus PDF blob for arXiv entries
├── report.db    — Think tank reports: title + PDF blob
└── youtube.db   — YouTube: video metadata + subtitle text
```

`core.db` / `dive.db` / `zen.db` / `paper.db` share one `items` table shape
(see `schema.sql`), including a `fetched_full` column: every entry attempts
a full-text fetch regardless of its `display_mode` (which only controls
*rendering*), and `fetched_full` records whether that fetch actually
succeeded — this is what gates zip-attachment eligibility, independent of
how the item displays in the email body. `paper.db` and `report.db` also
carry `pdf_url`/`pdf_data` columns for their respective PDF downloads.

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
| Paper Weekly | `papers.zip` | One `.pdf` per successfully-downloaded arXiv paper |
| Report Monthly | `reports.zip` | One `.pdf` per successfully-downloaded report |
| YouTube Weekly | `out_yt.zip` | One `.md` per video with subtitle text |

An entry whose fetch/download failed is still listed in the email body —
it's just excluded from the zip rather than causing the whole thing to
fail. `reports.zip`/`papers.zip` also cap total size (`export_pdf_zip`'s
`max_total_bytes`, default 18MB of raw PDF bytes) and omit the overflow
rather than risk exceeding the recipient's mail provider size limit — this
is a direct fix for a real failure where 19 individually-attached PDFs plus
the raw `report.db` blew past Gmail's 25MB limit in one send.

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
ingest_scrapers.py` scrapes each of these directly instead, then feeds the
result through the same PDF-download/dedup/error-handling path as an
RSS-derived entry. This runs automatically whenever `report.db` is a
target of `ingest_rss.py` — no separate workflow step needed.

AI Index and Institute for Progress are implemented. Brookings, NBER, and
Carnegie are explicit stubs (raise `NotImplementedError`, logged to
`report.db`'s `errors` table) — their listing pages need more
site-structure verification than could be done with confidence yet.

arXiv is handled differently again: it has RSS (`rss.arxiv.org`), but its
PDFs are downloaded directly via a predictable `arxiv.org/abs/{id}` ->
`arxiv.org/pdf/{id}` URL pattern (`ingest_rss.py::process_paper_entry`)
rather than report.db's generic "scrape the landing page for a PDF link"
approach — see `feeds/rss.yaml`'s `rss.paper.arxiv` group.

---

## Feed Configuration

Feeds are split by content type:

| File | Content |
|------|---------|
| `feeds/rss.yaml` | All RSS/Atom sources |
| `feeds/hn.yaml` | HackerNews API config |
| `feeds/yt.yaml` | YouTube channel IDs |

Some sources are still `url: FILL_ME` pending a real feed URL (e.g. AQR
Research, Anthropic Research, NIST AI) — `ingest_rss.py` silently skips
these. This is different from `report.db`'s Brookings/AI Index/NBER/
Institute for Progress/Carnegie, which were removed from `rss.yaml`
entirely rather than left as permanent FILL_ME placeholders, since those
sources have no RSS to eventually fill in — see "Report scrapers" above.

---

## Display Protocols

| Mode | Used by | Renders | Full-text fetch attempted? |
|------|---------|---------|------------------------------|
| `full` | Dive, Zen, Ruanyf, some Daily sources | Title + full text | Yes |
| `title_excerpt` | Digest, Bandcamp, sspai | Title + first ~180 chars + link | Yes |
| `title_only` | Papers, Reports | Title + source + link | Yes (paper.db abstracts still just store the RSS summary since most sources have no full-article page to fetch) |
| `repo_card` | GitHub Trending, HelloGitHub | Repo name + one-line description | No — never fetched, never zip-eligible |
| `chart_only` | Billboard | Rank table (scraped from billboard.com) | No — not an article |

Full-text fetch success/failure is independent of `display_mode` (see
`fetched_full` above) — `display_mode` only controls how an item renders in
the email body.

---

## Setup

1. Fill remaining `FILL_ME` values in `feeds/rss.yaml`, `feeds/yt.yaml` with real URLs / channel IDs
2. Set GitHub repository secrets:
   - `SMTP_USER` — Gmail address
   - `SMTP_PASS` — Gmail App Password
   - `TO_EMAIL` — recipient address
   - `IMAP_HOST` — only needed for the Email Download workflow (defaults to `imap.gmail.com`)
3. Enable Git LFS on your repo: `git lfs install`

---

## Local Testing

```bash
pip install feedparser requests trafilatura pyyaml yt-dlp

# Initialize all databases
python scripts/db_init.py

# Test daily ingest + render
python scripts/ingest_rss.py core
python scripts/ingest_hn.py
python scripts/render_daily.py
open out_daily.html
```

`test_local.sh` runs a fuller local pass across every ingest + render
script, seeding a dummy row into any database that comes back empty so the
render step has something to work with instead of hitting "nothing to
send".

---

## Project Structure

```
dewsletter/
├── feeds/
│   ├── rss.yaml
│   ├── hn.yaml
│   └── yt.yaml
├── scripts/
│   ├── config.py             — loads feeds/*.yaml
│   ├── db_init.py            — create/migrate all databases
│   ├── db_utils.py           — shared read/write helpers for every db
│   ├── ingest_base.py        — shared dedup + concurrency skeleton
│   ├── ingest_rss.py         — RSS ingest (core/dive/zen/paper/report)
│   ├── ingest_scrapers.py    — non-RSS report.db sources (AI Index, IFP, ...)
│   ├── ingest_hn.py          — HackerNews via Firebase API
│   ├── ingest_youtube.py     — YouTube subtitle/video/audio ingest
│   ├── tldr_fetch.py         — live TLDR fetch (never persisted)
│   ├── render_base.py        — shared email-shell + zip-export helpers
│   ├── render_daily.py
│   ├── render_extra.py       — TLDR / Ruanyf / HelloGitHub
│   ├── render_dive.py
│   ├── render_zen.py
│   ├── render_paper.py
│   ├── render_report.py
│   ├── render_yt.py
│   ├── gen_opml.py           — export feed.opml from all sources
│   ├── release_utils.py      — shared GitHub Release upload helpers
│   ├── upload_daily_release.py
│   ├── upload_yt_release.py
│   └── email_download.py     — mailbox-triggered download-to-Release
├── database/                 — all .db files (Git LFS)
├── schema.sql                — schema reference (kept in sync by hand with db_init.py)
├── test_local.sh             — local smoke test across every script
├── .gitattributes            — database/*.db → LFS
├── geoip/                    — unrelated: CN IP routing list generator, see geoip/README.md
│   ├── generate.sh
│   ├── README.md
│   └── dist/                 — generated, gitignored; only ever pushed to the `release` branch
└── .github/workflows/
    ├── daily.yml              — Daily + Extra
    ├── dive_weekly.yml
    ├── zen_weekly.yml
    ├── paper_weekly.yml
    ├── report_monthly.yml
    ├── yt_weekly.yml
    ├── email_download.yml     — runs every 3 days, not on the issue schedule above
    └── geoip-update.yml       — hourly; entirely independent of the workflows above
```
