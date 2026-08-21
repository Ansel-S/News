"""
collectors/rss.py — Fetch a single RSS/Atom feed URL and return raw
feedparser entries.

Deliberately does nothing beyond HTTP fetch + feedparser.parse: no
full-text extraction, no PDF download, no dedup, no storage. Those are
processors/ concerns (see processors/article.py, processors/paper.py,
processors/report.py) — this module's only job is "give me the raw
entries for this URL", same contract collectors/scraper.py's functions
have for their non-RSS sources.

Moved out of ingest_rss.py verbatim (Phase 2 of the architecture redesign,
see /DESIGN.md) — behavior is unchanged, only the file changed.
"""
from __future__ import annotations
import feedparser
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Dewsletter/1.0)"}


def fetch_entries(feed_url: str, *, timeout: int = 30) -> list:
    """Fetch and parse a feed URL. Raises on HTTP failure — callers
    (ingest_rss.py's per-source dispatch) are responsible for catching and
    logging to the errors table, same as before this was split out."""
    resp = requests.get(feed_url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    return feed.entries
