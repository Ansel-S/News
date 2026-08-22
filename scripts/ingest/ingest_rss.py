"""
ingest_rss.py — Thin orchestrator for all non-HN, non-YouTube feeds.
Usage:
  python scripts/ingest_rss.py                # all RSS feeds
  python scripts/ingest_rss.py content         # only feeds writing to content.db
  python scripts/ingest_rss.py content report  # multiple dbs

Reads config.rss_feeds(), and for each source decides which collector to
fetch raw entries with and which processor to hand them to:

  db == "report"                                -> collectors.rss + processors.report
  source has a `pdf` field (e.g. pdf: arxiv)    -> collectors.rss + processors.paper
  everything else                                -> collectors.rss + processors.article

The arXiv-vs-everything-else dispatch is keyed on the source's own `pdf`
field (config/sources/rss.yml), not on any string pattern in feed_key —
feed_key is a display/grouping label only and isn't safe to dispatch
routing logic on (see DESIGN.md's config-unification notes for a
concrete case where this broke).

report.db also pulls from sources with no RSS feed at all (Brookings, AI
Index, etc) via collectors.scraper.ingest_report_scrapers() — runs
automatically whenever report.db is a target, no separate workflow step
needed.

Billboard Hot 100 is NOT handled here — it's a standalone monthly send
(scripts/render/render_billboard.py, via the Parse.bot scraper API),
not part of content.db or the Daily digest. See that file's docstring.
"""
from __future__ import annotations


import sys as _sys
from pathlib import Path as _Path
_SCRIPTS_DIR = _Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_SCRIPTS_DIR))
import os
import sys

from config import rss_feeds
from db.db_utils import run_id, insert_error
from ingest.ingest_base import run_parallel

import collectors.rss as rss_collector
from collectors.scraper import ingest_report_scrapers
from processors.article import process_entry
from processors.paper import process_paper_entry
from processors.report import process_report_entry

MAX_WORKERS = int(os.getenv("RSS_WORKERS", "8"))


def fetch_feed(feed_url: str, *, db: str, feed_key: str, source_name: str,
               extract_mode: str, email_mode: str, r: str,
               source_key: str | None = None, pdf: str | None = None) -> None:
    try:
        entries = rss_collector.fetch_entries(feed_url)

        for entry in entries:
            try:
                if db == "report":
                    process_report_entry(entry, feed_key=feed_key,
                                         source_name=source_name, r=r,
                                         source_key=source_key)
                elif pdf == "arxiv":
                    process_paper_entry(entry, feed_key=feed_key,
                                       source_name=source_name, r=r,
                                       source_key=source_key)
                else:
                    process_entry(entry, db=db, feed_key=feed_key,
                                  source_name=source_name, extract_mode=extract_mode,
                                  email_mode=email_mode, r=r,
                                  source_key=source_key)
            except Exception as ex:
                insert_error(db, run_id=r, source_id=entry.get("link", feed_url),
                             stage="parse", error_type="unknown", message=str(ex))
    except Exception as ex:
        insert_error(db, run_id=r, source_id=feed_url,
                     stage="fetch", error_type="network", message=str(ex))


def main(target_dbs: list[str] | None = None) -> None:
    r     = run_id()
    tasks = []

    for group in rss_feeds():
        db = group.get("db", "content")
        if target_dbs and db not in target_dbs:
            continue

        feed_key = group["key"]

        for src in group.get("sources", []):
            url = src.get("url", "")
            if not url or url == "FILL_ME":
                continue
            if src.get("no_store"):
                # e.g. TLDR: fetched live in render_daily, never persisted (time-sensitive content)
                continue
            extract_mode = src.get("extract_mode", "normal")
            email_mode = src.get("email_mode", "full")
            tasks.append(dict(feed_url=url, db=db, feed_key=feed_key,
                              source_name=src["name"], extract_mode=extract_mode,
                              email_mode=email_mode, r=r,
                              source_key=src.get("source_key"), pdf=src.get("pdf")))

    print(f"ingest_rss: {len(tasks)} feeds, {MAX_WORKERS} workers")
    run_parallel(tasks, fetch_feed, max_workers=MAX_WORKERS, label_key="feed_url")

    # report.db also pulls from sources with no RSS feed at all (Brookings,
    # AI Index, etc) — these run through their own per-source scrapers
    # rather than the feed-parsing path above. Only run when report.db is
    # actually a target, same gating as the RSS-backed report.* sources.
    if target_dbs is None or "report" in target_dbs:
        ingest_report_scrapers(r)


if __name__ == "__main__":
    target = sys.argv[1:] if len(sys.argv) > 1 else None
    main(target)
