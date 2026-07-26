"""
ingest_rss.py — Unified RSS ingest for all non-HN, non-YouTube feeds
Usage:
  python scripts/ingest_rss.py              # all RSS feeds
  python scripts/ingest_rss.py core         # only feeds writing to core.db
  python scripts/ingest_rss.py core dive    # multiple dbs

Billboard is scraped directly from billboard.com (display_mode: chart_only).
Reports (report.db) attempt to download the PDF linked from each entry.
"""
from __future__ import annotations

import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, UTC

import feedparser
import requests
import trafilatura

from config import rss_feeds
from db_utils import (
    run_id, now_iso,
    item_exists, insert_item, insert_error,
    report_exists, insert_report,
)

LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "8"))
MAX_WORKERS   = int(os.getenv("RSS_WORKERS", "8"))
RETRY_SOURCE  = os.getenv("RETRY_ONLY_SOURCE")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Dewsletter/1.0)"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_recent(entry) -> bool:
    pub = entry.get("published_parsed")
    if pub is None:
        return True
    try:
        return datetime(*pub[:6], tzinfo=UTC) >= datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)
    except Exception:
        return True


def fetch_text(url: str) -> str | None:
    raw = trafilatura.fetch_url(url)
    if raw:
        text = trafilatura.extract(raw, output_format="markdown")
        if text:
            return text
    return None


def fetch_pdf(url: str) -> bytes | None:
    """Try to download a PDF. Returns raw bytes or None."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=60, stream=True)
        r.raise_for_status()
        ct = r.headers.get("content-type", "")
        if "pdf" in ct or url.lower().endswith(".pdf"):
            return r.content
    except Exception:
        pass
    return None


def find_pdf_link(html: str, base_url: str) -> str | None:
    """Extract first PDF href from HTML."""
    matches = re.findall(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', html, re.I)
    if not matches:
        return None
    link = matches[0]
    if link.startswith("http"):
        return link
    from urllib.parse import urljoin
    return urljoin(base_url, link)


# ── Billboard scraper ─────────────────────────────────────────────────────────

def scrape_billboard() -> str:
    url = "https://www.billboard.com/charts/hot-100/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        return f"Billboard fetch failed: {e}"

    html = r.text
    entries = re.findall(
        r'<h3[^>]+id="[^"]*"[^>]*class="[^"]*c-title[^"]*"[^>]*>\s*(.*?)\s*</h3>.*?'
        r'<span[^>]+class="[^"]*c-label[^"]*a-no-trucate[^"]*"[^>]*>\s*(.*?)\s*</span>',
        html, re.DOTALL
    )

    if not entries:
        text = trafilatura.extract(html)
        return text or "Billboard parse failed"

    lines = ["| Rank | Title | Artist |", "|------|-------|--------|"]
    for i, (song, artist) in enumerate(entries[:20], 1):
        song   = re.sub(r"<[^>]+>", "", song).strip()
        artist = re.sub(r"<[^>]+>", "", artist).strip()
        lines.append(f"| {i} | {song} | {artist} |")
    return "\n".join(lines)


# ── Content extraction ────────────────────────────────────────────────────────

def extract_content(url: str, summary: str, display_mode: str) -> str:
    if display_mode in ("title_only", "chart_only"):
        return summary or ""
    text = fetch_text(url)
    if text:
        return text
    # Wayback fallback
    try:
        wb = f"https://web.archive.org/web/{url}"
        text = fetch_text(wb)
        if text:
            return text
    except Exception:
        pass
    return summary or ""


# ── Report entry processing ───────────────────────────────────────────────────

def process_report_entry(entry, *, feed_key: str, source_name: str, r: str) -> None:
    url = entry.get("link", "")
    if not url or report_exists(url):
        return

    title      = entry.get("title", "")
    created_at = entry.get("published", r)

    # Try to find and download PDF
    pdf_url: str | None  = None
    pdf_data: bytes | None = None
    try:
        page = requests.get(url, headers=HEADERS, timeout=30)
        page.raise_for_status()
        ct = page.headers.get("content-type", "")
        if "pdf" in ct:
            pdf_url  = url
            pdf_data = page.content
        else:
            link = find_pdf_link(page.text, url)
            if link:
                pdf_url  = link
                pdf_data = fetch_pdf(link)
    except Exception as e:
        insert_error("report", run_id=r, source_id=url,
                     stage="fetch", error_type="network", message=str(e))

    insert_report(
        source_id=url, feed_key=feed_key, source_name=source_name,
        title=title, pdf_url=pdf_url, pdf_data=pdf_data, created_at=created_at,
    )
    pdf_status = f"PDF {len(pdf_data)//1024}KB" if pdf_data else "no PDF"
    print(f"  [report] {title[:60]} — {pdf_status}")


# ── Generic RSS entry processing ──────────────────────────────────────────────

def process_entry(entry, *, db: str, feed_key: str, source_name: str,
                  display_mode: str, r: str) -> None:
    url = entry.get("link", "")
    if not url:
        return
    if RETRY_SOURCE and feed_key != RETRY_SOURCE:
        return
    if not is_recent(entry):
        return
    if item_exists(db, url):
        return

    summary = entry.get("summary", "")
    content = extract_content(url, summary, display_mode)

    insert_item(
        db,
        source_id=url, feed_key=feed_key, source_name=source_name,
        display_mode=display_mode, title=entry.get("title", ""),
        content=content, created_at=entry.get("published", r),
    )


# ── Per-feed fetch ────────────────────────────────────────────────────────────

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
            )
        return

    try:
        resp = requests.get(feed_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)

        for entry in feed.entries:
            try:
                if db == "report":
                    process_report_entry(entry, feed_key=feed_key,
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


# ── Entry point ───────────────────────────────────────────────────────────────

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
            tasks.append(dict(url=url, db=db, feed_key=feed_key,
                              source_name=src["name"], display_mode=display_mode))

    print(f"ingest_rss: {len(tasks)} feeds, {MAX_WORKERS} workers")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        futures = {
            exe.submit(fetch_feed, t["url"], db=t["db"], feed_key=t["feed_key"],
                       source_name=t["source_name"], display_mode=t["display_mode"], r=r): t["url"]
            for t in tasks
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as ex:
                print(f"[unhandled] {futures[future]}: {ex}")


if __name__ == "__main__":
    target = sys.argv[1:] if len(sys.argv) > 1 else None
    main(target)
