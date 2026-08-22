"""
render_daily.py — Daily digest renderer
Section order: GitHub → Digest → HN → Bandcamp

Billboard Hot 100 is not part of Daily — it's a standalone monthly send,
see scripts/render/render_billboard.py.

TLDR / Ruanyf Weekly / HelloGitHub are rendered as a separate "Dewsletter
Extra" email by render_extra.py, not folded in here — routing is handled
by issues/builder.py: those three list `extra_daily` (not `daily`) in
their own `issues` field in config/sources/rss.yml, so they never reach
this file at all.

Any row with fetched_full=1 (successful full-text fetch — independent of
email_mode) gets its complete text written as a .md file and zipped into
out_daily.zip. The email body still renders each row per its own
email_mode (full/excerpt/title) — a "full" article whose fetch failed
still displays normally, it's just not in the zip.

Rows are grouped by their own stored feed_key (the source's `section`
from config, or the source_key itself for sources with no shared
section) — no separate topic lookup needed; each row already carries the
grouping label it was ingested with. GitHub Trending's extract_mode is
"skip" but needs bespoke HTML (repo_card), distinguished by config's
`render_style` field, looked up per source_key.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_SCRIPTS_DIR = _Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_SCRIPTS_DIR))
import html
from collections import defaultdict
from pathlib import Path

from config import rss_sources
from db.db_utils import mark_pushed, run_id as new_run_id
from issues.builder import build as build_issue, topic_order as _source_order
from render.render_base import (
    fmt_date, email_shell, section_heading, excerpt,
    block_title_excerpt, block_repo_card, block_hn, chart_table,
    export_full_articles_zip,
    MUTED, TEXT, ACCENT, MONO, BORDER,
)

ROOT       = Path(__file__).resolve().parent.parent.parent  # scripts/<subpkg>/this_file.py -> repo root
OUT_HTML   = ROOT / "out_daily.html"
OUT_SUBJ   = ROOT / "out_daily_subject.txt"
OUT_ZIP    = ROOT / "out_daily.zip"
ISSUE_TYPE = "daily"


def _render_styles() -> dict[str, str]:
    """source_key -> render_style, for the handful of sources that need
    bespoke HTML beyond the standard full/excerpt/title blocks."""
    return {s["id"]: s["render_style"] for s in rss_sources() if "render_style" in s}


def _full_teaser_block(*, title: str, source_name: str, url: str,
                        content: str, read_minutes: int, sep: bool) -> str:
    """Title + one-line teaser for a 'full' article whose complete text
    lives in the zip attachment instead of inline."""
    sep_css = f"border-top:1px solid {BORDER};padding-top:20px;margin-top:20px;" if sep else ""
    teaser  = html.escape(excerpt(content, 160))
    rm      = f" &middot; ~{read_minutes} min" if read_minutes else ""
    return f"""
<article style="{sep_css}">
  <p style="margin:0 0 4px;font-size:10px;font-weight:700;letter-spacing:.10em;
            text-transform:uppercase;color:{MUTED};font-family:{MONO}"
  >{html.escape(source_name)}{rm}</p>
  <h3 style="margin:0 0 6px;font-size:16px;font-weight:600;line-height:1.4;color:{TEXT}">
    <a href="{html.escape(url)}" style="color:inherit;text-decoration:none"
    >{html.escape(title or '(untitled)')}</a>
  </h3>
  <p style="margin:0;font-size:13px;line-height:1.6;color:{MUTED}">{teaser}
    <span style="color:{TEXT}"> &mdash; full text in attachment</span></p>
</article>"""


# Display labels for feed_key groups that hold more than one source under
# one heading (single-source groups just use that source's name instead —
# see below). Only needs entries for groups that actually appear this way
# in Daily; anything else falls back to a title-cased version of the
# feed_key's last dot-segment.
_SECTION_LABELS = {
    "rss.digest.economics": "Economics",
    "rss.daily.music":      "Music",
}


def render_rss_sections(rows) -> tuple[str, int, int, list]:
    order_map = _source_order(ISSUE_TYPE)  # source_key -> order
    render_styles = _render_styles()       # source_key -> render_style

    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        groups[row["feed_key"]].append(row)

    def order(feed_key: str) -> int:
        # every source in a group shares the same order (they were seeded
        # from the same old topic at migration time) — look up any member
        for row in groups[feed_key]:
            o = order_map.get(row["source_key"])
            if o is not None:
                return o
        return 99

    parts, total_count, total_minutes = [], 0, 0
    full_rows_for_zip: list = []

    for feed_key in sorted(groups, key=order):
        grp = groups[feed_key]
        distinct_sources = {r["source_name"] for r in grp}
        if len(distinct_sources) == 1:
            heading = grp[0]["source_name"]
        else:
            heading = _SECTION_LABELS.get(feed_key, feed_key.rsplit(".", 1)[-1].replace("-", " ").title())
        parts.append(section_heading(heading, len(grp)))
        for i, row in enumerate(grp):
            kw    = dict(title=row["title"] or "", source_name=row["source_name"],
                        url=row["source_id"], content=row["content"] or "", sep=(i > 0))
            style = render_styles.get(row["source_key"])
            if style == "repo_card":
                parts.append(block_repo_card(**kw))
            elif style == "chart":
                parts.append(chart_table(row["content"] or ""))
            elif row["email_mode"] == "full":
                parts.append(_full_teaser_block(**kw, read_minutes=row["read_minutes"] or 0))
            else:
                parts.append(block_title_excerpt(**kw))

            # Zip eligibility is independent of email_mode/rendering above —
            # it only depends on whether the full-text fetch actually
            # succeeded (row["fetched_full"]). A "full"-mode article whose
            # fetch failed still displays normally (falls back to whatever
            # content ended up in the row) but is excluded from the zip.
            if row["fetched_full"]:
                full_rows_for_zip.append(row)

            total_count   += 1
            total_minutes += row["read_minutes"] or 0

    return "\n".join(parts), total_count, total_minutes, full_rows_for_zip


def render_hn_section(hn_rows) -> str:
    if not hn_rows:
        return ""
    parts = [section_heading("Hacker News", len(hn_rows)),
             f'<ul style="list-style:none;margin:0;padding:0">']
    for row in hn_rows:
        parts.append(block_hn(
            title=row["title"], url=row["external_url"] or row["source_id"],
            score=row["score"], by=row["by"] or "",
            descendants=row["descendants"] or 0, hn_url=row["source_id"],
        ))
    parts.append("</ul>")
    return "\n".join(parts)


def main() -> None:
    issue_id = new_run_id()
    tagged = build_issue(ISSUE_TYPE)  # [(db, row), ...] — content.db's RSS
                                       # rows + hn.db's HN rows together
    rss_rows = [row for db, row in tagged if db != "hn"]
    hn_rows  = sorted((row for db, row in tagged if db == "hn"),
                      key=lambda r: r["score"] or 0, reverse=True)
    row_db   = {row["id"]: db for db, row in tagged}

    rss_html, rss_count, rss_minutes, full_rows = render_rss_sections(rss_rows)
    hn_html  = render_hn_section(hn_rows)
    total    = rss_count + len(hn_rows)

    zip_file_count = 0
    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    if full_rows:
        zip_file_count = export_full_articles_zip(full_rows, OUT_ZIP)

    summary = (
        f'<p style="margin:0 0 32px;font-size:13px;color:{MUTED};line-height:1.6">'
        f'{total} items &middot; ~{rss_minutes} min read'
        f'{" (full articles in attachment)" if zip_file_count else ""}</p>'
    )

    date_str = fmt_date()
    html_out = email_shell(
        title=date_str,
        subtitle=f"{total} items · ~{rss_minutes} min read",
        body=summary + rss_html + hn_html,
        issue_label="Daily",
    )
    OUT_HTML.write_text(html_out, encoding="utf-8")
    OUT_SUBJ.write_text(f"Dewsletter Daily · {date_str} · {total} items")

    for row in rss_rows:
        mark_pushed(row_db[row["id"]], row["id"], ISSUE_TYPE, issue_id)
    for row in hn_rows:
        mark_pushed(row_db[row["id"]], row["id"], ISSUE_TYPE, issue_id)

    zip_note = f", {zip_file_count} full articles → {OUT_ZIP.name}" if zip_file_count else ""
    print(f"render_daily: {rss_count} RSS + {len(hn_rows)} HN{zip_note} → {OUT_HTML.name}")


if __name__ == "__main__":
    main()
