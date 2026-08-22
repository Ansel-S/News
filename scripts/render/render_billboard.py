"""
render_billboard.py — Billboard Hot 100, monthly, standalone.

Not part of the RSS/content.db pipeline: config/sources/rss.yml's
`billboard-hot-100` entry has always had `url: FILL_ME` (billboard.com
has no real chart RSS feed), so ingest_rss.py has always silently
skipped it, and collectors/scraper.py's regex-based scrape_billboard()
was the standing attempt to work around that — fragile (breaks whenever
billboard.com's markup changes) and never actually wired to a live URL.

This replaces that with the Parse.bot scraper API (a hosted scraper for
billboard.com, see the API's `get_chart` endpoint), fetched live and
never persisted to any database — there's nothing to dedup across a
monthly cadence, so no db_utils/db table involvement at all.

Usage:
  PARSE_API_KEY=... python scripts/render/render_billboard.py

Writes out_billboard.html + out_billboard_subject.txt (repo root) if the
chart fetch succeeds. Writes nothing on failure — same "nothing to
send" convention as every other render_*.py — so the workflow's subject
guard skips the send step rather than emailing an empty/broken chart.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_SCRIPTS_DIR = _Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_SCRIPTS_DIR))

import html
import os

import requests

from render.render_base import fmt_date, email_shell, MUTED, TEXT, BORDER, MONO

ROOT     = _Path(__file__).resolve().parent.parent.parent
OUT_HTML = ROOT / "out_billboard.html"
OUT_SUBJ = ROOT / "out_billboard_subject.txt"

PARSE_API_KEY = os.environ.get("PARSE_API_KEY", "")
PARSE_URL = (
    "https://api.parse.bot/scraper/8ec93041-c361-44bc-ad64-f2eab79c1730"
    "/get_chart"
)
CHART_NAME = "hot-100"


def fetch_chart() -> list[dict]:
    """Return chart items (rank/title/artist), raising on any failure —
    caller decides what "no chart" means for the render step."""
    if not PARSE_API_KEY:
        raise RuntimeError("PARSE_API_KEY is not set")
    r = requests.get(
        PARSE_URL,
        params={"chart_name": CHART_NAME},
        headers={"X-API-Key": PARSE_API_KEY},
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    items = payload.get("data", {}).get("items", [])
    if not items:
        raise RuntimeError("Parse.bot returned no chart items")
    return items


def render_table(items: list[dict]) -> str:
    rows = []
    for entry in items:
        rank   = html.escape(str(entry.get("rank", "")))
        title  = html.escape(str(entry.get("title", "")))
        artist = html.escape(str(entry.get("artist", "")))
        rows.append(
            "<tr>"
            f"<td style='padding:6px 12px;text-align:left;width:44px;"
            f"border-bottom:1px solid {BORDER}'>{rank}</td>"
            f"<td style='padding:6px 12px;text-align:left;"
            f"border-bottom:1px solid {BORDER}'>{title}</td>"
            f"<td style='padding:6px 12px;text-align:left;"
            f"border-bottom:1px solid {BORDER};color:{MUTED}'>{artist}</td>"
            "</tr>"
        )
    header = (
        "<tr>"
        f"<th style='padding:6px 12px;text-align:left;font-size:11px;"
        f"text-transform:uppercase;letter-spacing:.08em;color:{MUTED};"
        f"font-family:{MONO};border-bottom:1px solid {TEXT}'>Rank</th>"
        f"<th style='padding:6px 12px;text-align:left;font-size:11px;"
        f"text-transform:uppercase;letter-spacing:.08em;color:{MUTED};"
        f"font-family:{MONO};border-bottom:1px solid {TEXT}'>Title</th>"
        f"<th style='padding:6px 12px;text-align:left;font-size:11px;"
        f"text-transform:uppercase;letter-spacing:.08em;color:{MUTED};"
        f"font-family:{MONO};border-bottom:1px solid {TEXT}'>Artist</th>"
        "</tr>"
    )
    return (
        "<table style='width:100%;border-collapse:collapse;font-size:13px'>"
        f"<thead>{header}</thead><tbody>{''.join(rows)}</tbody></table>"
    )


def main() -> None:
    try:
        items = fetch_chart()
    except Exception as ex:
        print(f"render_billboard: nothing to send ({ex})")
        return

    date_str = fmt_date()
    body = render_table(items)
    html_out = email_shell(
        title=date_str,
        subtitle=f"Billboard Hot 100 · {len(items)} entries",
        body=body,
        issue_label="Billboard Hot 100",
    )
    OUT_HTML.write_text(html_out, encoding="utf-8")
    OUT_SUBJ.write_text(f"Dewsletter · Billboard Hot 100 · {date_str}")
    print(f"render_billboard: {len(items)} entries → {OUT_HTML.name}")


if __name__ == "__main__":
    main()
