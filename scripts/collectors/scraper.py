"""
collectors/scraper.py — Non-feed sources: Billboard (scraped directly,
never had RSS) and report.db sources with no RSS/Atom feed at all (AI
Index, Institute for Progress, Brookings, NBER, Carnegie Endowment —
unlike RAND/PIIE/Epoch AI, which do have RSS and go through the normal
collectors/rss.py path).

Correction to the original plan: Epoch AI turns out to publish on Substack
(epochai.substack.com), and every Substack exposes a standard RSS feed at
/feed — so Epoch AI does NOT need a scraper here; it's a normal RSS source
in config/sources/rss.yml (db: report), same as RAND/PIIE.

Each report scraper returns a list of "fake entries" shaped just enough
like a feedparser entry (title/link/published/summary keys) to be handed
to processors/report.py's process_report_entry() unchanged — that keeps
the PDF-download logic, dedup, and error handling all in one place instead
of duplicating it per source.

Implemented: AI Index, Institute for Progress (both grounded in each
site's real page structure at the time of writing — if either scraper
starts returning nothing, the site's markup has likely changed and this
needs a re-check, not a silent "just no reports this month"). The
remaining three (Brookings, NBER, Carnegie) are stubbed with a
NotImplementedError-raising placeholder — their listing pages are either
large multi-topic publication indexes or (NBER's /papers) appear to be
populated client-side rather than present in static HTML, both needing
more investigation than could be done confidently here — so
ingest_report_scrapers() skips them with a clear error entry in report.db's
errors table rather than silently doing nothing or shipping a scraper
likely to break on the first real run.

Moved out of ingest_scrapers.py + ingest_rss.py's scrape_billboard()
verbatim (Phase 2 of the architecture redesign, see /DESIGN.md) — behavior
is unchanged, only the file (and module name) changed. ingest_scrapers.py
no longer exists; import from here instead.

Usage (called automatically from ingest_rss.py::main() when report.db is a
target — no separate workflow step needed):
  from collectors.scraper import ingest_report_scrapers
  ingest_report_scrapers(run_id)
"""
from __future__ import annotations

import re
from datetime import datetime, UTC
from typing import Callable

import requests
import trafilatura

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Dewsletter/1.0)"}


# ── Billboard ────────────────────────────────────────────────────────────

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


def _fake_entry(*, title: str, link: str, published: str | None = None,
                summary: str = "") -> dict:
    """Build a dict shaped enough like a feedparser entry for
    process_report_entry() to consume directly.
    published: ISO8601 string, or None to mean "no date available"."""
    entry = {"title": title, "link": link, "summary": summary}
    if published:
        entry["published"] = published
        try:
            dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            entry["published_parsed"] = dt.utctimetuple()
        except ValueError:
            pass
    return entry


# ── AI Index (Stanford HAI) ───────────────────────────────────────────────
# One report per year at a predictable URL: hai.stanford.edu/ai-index/{Y}-
# ai-index-report. We don't hardcode the PDF asset URL directly (Stanford
# doesn't guarantee that pattern will hold forever) — process_report_entry()
# already handles fetching the landing page and scraping it for the actual
# PDF link (find_pdf_link), same as any other report source. This scraper's
# only job is to hand it the right landing-page URL.

AI_INDEX_LANDING = "https://hai.stanford.edu/ai-index/{year}-ai-index-report"


def scrape_ai_index() -> list[dict]:
    """Return zero or one fake entries for the current year's AI Index
    report (or last year's, if this year's isn't published yet)."""
    now_year = datetime.now(UTC).year
    for year in (now_year, now_year - 1):
        url = AI_INDEX_LANDING.format(year=year)
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code != 200:
                continue
        except Exception:
            continue

        return [_fake_entry(
            title=f"The {year} AI Index Report",
            link=url,
            published=f"{year}-01-01T00:00:00Z",
            summary="Stanford HAI's annual AI Index Report.",
        )]
    return []


# ── Institute for Progress (ifp.org) ──────────────────────────────────────
# ifp.org/latest-publications/ is a static (non-JS-rendered) WordPress
# listing of report cards, each linking to https://ifp.org/{slug}/ with a
# title and a "Month Dth Year" byline nearby. There's no direct PDF link on
# the listing page itself — process_report_entry() already handles that by
# fetching each article page and scraping it for a PDF link (find_pdf_link);
# many IFP pieces are HTML-only reports with no PDF at all, in which case
# process_report_entry() just stores no PDF, same as any other report.db
# source with no downloadable PDF (still listed in the email, just excluded
# from reports.zip).

IFP_LISTING_URL = "https://ifp.org/latest-publications/"
_IFP_LINK_RE = re.compile(r'''href=["'](https://ifp\.org/[a-z0-9\-]+/)["']''')
_IFP_DATE_RE = re.compile(r'([A-Z][a-z]+ \d{1,2}(?:st|nd|rd|th) \d{4})')
_IFP_DATE_WINDOW = 600  # chars to look ahead of a link for its byline date
_IFP_SKIP_SLUGS = {  # non-report nav links that match the same URL shape
    "about", "contact", "opportunities", "projects", "privacy-policy",
}


def scrape_institute_for_progress() -> list[dict]:
    """Scrape ifp.org's publication listing for recent report links. Limited
    to the first page (most recent ~15 publications) — process_report_entry
    dedups by URL and ingest_rss's normal lookback window filters anything
    too old anyway, so there's no need to paginate.

    Deliberately conservative: this only extracts (link, nearby date) pairs
    rather than trying to parse a title out of listing markup — a
    slug-derived placeholder title is used instead, since getting the title
    wrong is a much smaller problem than missing/duplicating an entry."""
    r = requests.get(IFP_LISTING_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    html = r.text

    seen_slugs: set[str] = set()
    entries: list[dict] = []
    for m in _IFP_LINK_RE.finditer(html):
        link = m.group(1)
        slug = link.rstrip("/").rsplit("/", 1)[-1]
        if slug in _IFP_SKIP_SLUGS or slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        window = html[m.end():m.end() + _IFP_DATE_WINDOW]
        date_m = _IFP_DATE_RE.search(window)
        published = None
        if date_m:
            try:
                cleaned = re.sub(r"(st|nd|rd|th)", "", date_m.group(1))
                published = datetime.strptime(cleaned, "%B %d %Y").strftime(
                    "%Y-%m-%dT00:00:00Z")
            except ValueError:
                pass

        title = slug.replace("-", " ").title()
        entries.append(_fake_entry(title=title, link=link, published=published))
    return entries


# ── Not yet implemented ───────────────────────────────────────────────────
# Brookings and Carnegie have large, multi-topic publication listings that
# need more structural verification than could be done confidently here.
# NBER's /papers listing appears to populate client-side (JS), not present
# in the static HTML — it likely needs NBER's underlying search/API
# endpoint instead of a page scrape. Left as explicit NotImplementedError
# stubs, rather than omitted, so the dispatch loop below can report *why*
# nothing came back instead of the source silently contributing zero
# entries forever.

def scrape_brookings() -> list[dict]:
    raise NotImplementedError("Brookings scraper not yet implemented")


def scrape_nber() -> list[dict]:
    raise NotImplementedError(
        "NBER scraper not yet implemented — /papers listing appears to be "
        "populated client-side (JS), not present in the static HTML; needs "
        "NBER's underlying search/API endpoint instead of a page scrape"
    )


def scrape_carnegie() -> list[dict]:
    raise NotImplementedError("Carnegie Endowment scraper not yet implemented")


# ── Dispatch table ─────────────────────────────────────────────────────────
# key -> (source_name for report.db, feed_key, scrape function). feed_key
# uses a "report.scrape.*" prefix to distinguish these from the RSS-backed
# report.* sources (RAND, PIIE, Epoch AI) at a glance in the db.

SCRAPERS: dict[str, tuple[str, str, Callable[[], list[dict]]]] = {
    "ai_index": ("AI Index (Stanford HAI)", "report.scrape.ai_index", scrape_ai_index),
    "institute_for_progress": ("Institute for Progress",
                               "report.scrape.ifp", scrape_institute_for_progress),
    "brookings": ("Brookings", "report.scrape.brookings", scrape_brookings),
    "nber": ("NBER", "report.scrape.nber", scrape_nber),
    "carnegie": ("Carnegie Endowment for International Peace",
                 "report.scrape.carnegie", scrape_carnegie),
}


def ingest_report_scrapers(r: str) -> None:
    """Run every scraper in SCRAPERS, feeding successful results through
    processors.report.process_report_entry() exactly like an RSS-derived
    entry. `r` is the run_id, matching ingest_rss.py's convention."""
    from processors.report import process_report_entry
    from db.db_utils import insert_error

    for key, (source_name, feed_key, scrape_fn) in SCRAPERS.items():
        try:
            entries = scrape_fn()
        except NotImplementedError as ex:
            insert_error("report", run_id=r, source_id=key,
                         stage="fetch", error_type="unknown", message=str(ex))
            continue
        except Exception as ex:
            insert_error("report", run_id=r, source_id=key,
                         stage="fetch", error_type="network", message=str(ex))
            continue

        for entry in entries:
            try:
                process_report_entry(entry, feed_key=feed_key,
                                     source_name=source_name, r=r)
            except Exception as ex:
                insert_error("report", run_id=r, source_id=entry.get("link", key),
                             stage="parse", error_type="unknown", message=str(ex))


if __name__ == "__main__":
    from db.db_utils import run_id
    ingest_report_scrapers(run_id())
