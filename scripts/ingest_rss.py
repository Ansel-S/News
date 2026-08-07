"""
ingest_rss.py — Thin orchestrator for all non-HN, non-YouTube feeds.
Usage:
  python scripts/ingest_rss.py              # all RSS feeds
  python scripts/ingest_rss.py core         # only feeds writing to core.db
  python scripts/ingest_rss.py core dive    # multiple dbs

This file used to hold every collector/processor function inline; as of
Phase 2 of the architecture redesign (see /DESIGN.md) it's just the
per-source dispatch loop — reads config.rss_feeds(), and for each source
decides which collector to fetch raw entries with and which processor to
hand them to:

  chart_only (Billboard)               -> collectors.scraper.scrape_billboard()
  db == "report"                       -> collectors.rss + processors.report
  feed_key starts with rss.paper.arxiv -> collectors.rss + processors.paper
  everything else                      -> collectors.rss + processors.article

report.db also pulls from sources with no RSS feed at all (Brookings, AI
Index, etc) via collectors.scraper.ingest_report_scrapers() — runs
automatically whenever report.db is a target, no separate workflow step
needed.

Behavior is unchanged from before this split — see collectors/ and
processors/ for the actual fetch/parse/store logic, moved out verbatim.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, UTC

from config import rss_feeds
from db_utils import run_id, now_iso, item_exists, insert_item, insert_error
from ingest_base import run_parallel

import collectors.rss as rss_collector
from collectors.scraper import scrape_billboard, ingest_report_scrapers
from processors.article import process_entry
from processors.paper import process_paper_entry
from processors.report import process_report_entry

MAX_WORKERS = int(os.getenv("RSS_WORKERS", "8"))


def fetch_feed(feed_url: str, *, db: str, feed_key: str, source_name: str,
               display_mode: str, r: str) -> None:

    # Billboard special case
    if display_mode == "chart_only":
        chart_id = feed_url + "#chart"
        if not item_exists(db, chart_id):
            content = scrape_billboard()
            insert_item(
                db,
                source_id=chart_id, feed_key=feed_key, source_name=source_name,
                display_mode="chart_only",
                title=f"Billboard Hot 100 · {datetime.now(UTC).strftime('%Y-%m-%d')}",
                content=content, created_at=now_iso(),
                extra_columns={"fetched_full": 0},
            )
        return

    try:
        entries = rss_collector.fetch_entries(feed_url)

        for entry in entries:
            try:
                if db == "report":
                    process_report_entry(entry, feed_key=feed_key,
                                         source_name=source_name, r=r)
                elif db == "paper" and feed_key.startswith("rss.paper.arxiv"):
                    process_paper_entry(entry, feed_key=feed_key,
                                       source_name=source_name, r=r)
                else:
                    process_entry(entry, db=db, feed_key=feed_key,
                                  source_name=source_name, display_mode=display_mode, r=r)
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
        db = group.get("db", "core")
        if target_dbs and db not in target_dbs:
            continue

        feed_key     = group["key"]
        group_mode   = group.get("display_mode")

        for src in group.get("sources", []):
            url = src.get("url", "")
            if not url or url == "FILL_ME":
                continue
            if src.get("no_store"):
                # e.g. TLDR: fetched live in render_daily, never persisted (time-sensitive content)
                continue
            display_mode = src.get("display_mode") or group_mode or "title_excerpt"
            tasks.append(dict(feed_url=url, db=db, feed_key=feed_key,
                              source_name=src["name"], display_mode=display_mode, r=r))

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
