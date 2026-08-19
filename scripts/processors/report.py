"""
processors/report.py — Report entry processing: fetches each entry's
landing page and scrapes it for a PDF link (unlike processors/paper.py's
arXiv path, which doesn't need to scrape anything since arXiv's PDF URLs
are predictable).

Handles both RSS-derived entries (RAND, Peterson Institute, Epoch AI —
routed here from ingest_rss.py's normal per-source dispatch when
db == "report") and scraper-derived "fake entries" (AI Index, Institute
for Progress, etc — routed here from collectors/scraper.py's
ingest_report_scrapers()). Both shapes are close enough to a feedparser
entry (title/link/published/summary keys) that this function doesn't need
to know which one it's looking at.

Moved out of ingest_rss.py verbatim (Phase 2 of the architecture redesign,
see /DESIGN.md) — behavior is unchanged, only the file changed.
"""
from __future__ import annotations
import requests

from processors._http import HEADERS, fetch_pdf, find_pdf_link
from db.db_utils import report_exists, insert_report, insert_error


def process_report_entry(entry, *, feed_key: str, source_name: str, r: str,
                         source_key: str | None = None) -> None:
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
        source_key=source_key,
    )
    pdf_status = f"PDF {len(pdf_data)//1024}KB" if pdf_data else "no PDF"
    print(f"  [report] {title[:60]} — {pdf_status}")
