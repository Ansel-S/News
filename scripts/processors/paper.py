"""
processors/paper.py — arXiv PDF download, separate from report.db's
generic-thinktank PDF-scraping logic (processors/report.py). arXiv PDF
URLs are predictable (abs/{id} -> pdf/{id}), so no HTML scraping is needed
to find the link, unlike report.db's sources.

Moved out of ingest_rss.py verbatim (Phase 2 of the architecture redesign,
see /DESIGN.md) — behavior is unchanged, only the file changed.
"""
from __future__ import annotations
import re

from processors._http import fetch_pdf
from processors.article import is_recent
from db.db_utils import paper_exists, insert_paper, insert_error

_ARXIV_ABS_RE = re.compile(r"arxiv\.org/abs/([^/?#]+)", re.I)


def arxiv_pdf_url(abs_url: str) -> str | None:
    """Convert an arxiv.org/abs/{id} URL to its arxiv.org/pdf/{id} PDF URL.
    Returns None if the URL doesn't look like an arXiv abstract page."""
    m = _ARXIV_ABS_RE.search(abs_url)
    if not m:
        return None
    return f"https://arxiv.org/pdf/{m.group(1)}"


def process_paper_entry(entry, *, feed_key: str, source_name: str, r: str,
                        source_key: str | None = None) -> None:
    url = entry.get("link", "")
    if not url or paper_exists(url):
        return
    if not is_recent(entry):
        return

    title      = entry.get("title", "")
    summary    = entry.get("summary", "")
    created_at = entry.get("published", r)

    pdf_link = arxiv_pdf_url(url)
    pdf_data: bytes | None = None
    if pdf_link:
        pdf_data = fetch_pdf(pdf_link)
        if pdf_data is None:
            insert_error("content", run_id=r, source_id=url,
                         stage="fetch", error_type="format",
                         message=f"PDF download failed or not a PDF: {pdf_link}")
    else:
        # Not an arxiv.org/abs/ URL — this feed group probably isn't arXiv
        # after all; store the abstract/title without a PDF instead of
        # dropping the entry entirely.
        insert_error("content", run_id=r, source_id=url,
                     stage="parse", error_type="format",
                     message="URL did not match arxiv.org/abs/{id} pattern")

    insert_paper(
        source_id=url, feed_key=feed_key, source_name=source_name,
        title=title, content=summary, pdf_url=pdf_link if pdf_data else None,
        pdf_data=pdf_data, created_at=created_at, source_key=source_key,
    )
    pdf_status = f"PDF {len(pdf_data)//1024}KB" if pdf_data else "no PDF"
    print(f"  [paper] {title[:60]} — {pdf_status}")
