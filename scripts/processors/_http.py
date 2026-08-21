"""
processors/_http.py — Shared fetch primitives used by more than one
processor (fetch_pdf is used by both paper.py and report.py; fetch_text is
used by article.py). Kept as one small shared module instead of duplicated
per-processor.

Moved out of ingest_rss.py verbatim (Phase 2 of the architecture redesign,
see /DESIGN.md) — behavior is unchanged, only the file changed.
"""
from __future__ import annotations
import re
import requests
import trafilatura

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Dewsletter/1.0)"}


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
