"""
render_daily.py — Daily digest renderer
Section order: TLDR (attachment teaser) → GitHub → Digest → HN → Billboard/Bandcamp

Any "full" article (TLDR, or any other core.db source with display_mode=full)
gets its complete text written as a .md file and zipped into out_daily.zip
instead of dumped inline — the email body shows a title+teaser only. TLDR
itself is fetched live and never stored in core.db (time-sensitive content).
"""
from __future__ import annotations
import html
import shutil
import zipfile
from collections import defaultdict
from datetime import datetime, UTC
from pathlib import Path

from config import DAILY_ORDER
from db_utils import get_unpushed, get_unpushed_hn, mark_pushed, mark_pushed_hn, run_id as new_run_id
from render_base import (
    fmt_date, email_shell, section_heading, excerpt,
    block_title_excerpt, block_repo_card, block_hn, chart_table,
    export_full_articles_zip,
    MUTED, TEXT, ACCENT, MONO, BORDER,
)
import tldr_fetch

ROOT       = Path(__file__).resolve().parent.parent
OUT_HTML   = ROOT / "out_daily.html"
OUT_SUBJ   = ROOT / "out_daily_subject.txt"
OUT_ZIP    = ROOT / "out_daily.zip"
TLDR_TMP_DIR = ROOT / ".tldr_tmp"
ISSUE_TYPE = "daily"


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


def render_tldr_section() -> tuple[str, int, list[Path]]:
    """Fetch TLDR live and write per-article markdown files (not zipped here —
    the caller merges them with any other 'full' articles into one zip).
    Returns (html_teaser_block, article_count, list_of_md_file_paths)."""
    articles = tldr_fetch.fetch_all()
    if not articles:
        return "", 0, []

    if TLDR_TMP_DIR.exists():
        shutil.rmtree(TLDR_TMP_DIR)
    paths = tldr_fetch.write_markdown_files(articles, TLDR_TMP_DIR)

    total_minutes = sum(a.read_minutes for a in articles)
    parts = [section_heading("TLDR", len(articles))]
    parts.append(
        f'<p style="margin:0 0 14px;font-size:12px;color:{MUTED};line-height:1.6">'
        f'Full articles (~{total_minutes} min total) are in the attached '
        f'<strong style="color:{TEXT}">daily.zip</strong> &mdash; one .md file per story.</p>'
    )
    parts.append(f'<ul style="list-style:none;margin:0;padding:0">')
    for a in articles:
        teaser = html.escape(tldr_fetch.summary_line(a))
        rt = f" &middot; ~{a.read_minutes} min" if a.read_minutes else ""
        parts.append(
            f'<li style="margin:10px 0;padding-bottom:10px;border-bottom:1px solid {BORDER};'
            f'font-size:13px;line-height:1.5">'
            f'<p style="margin:0 0 3px;font-weight:600;color:{TEXT}">{html.escape(a.title)}'
            f'<span style="font-weight:400;color:{MUTED};font-size:11px">{rt}</span></p>'
            f'<p style="margin:0;color:{MUTED};font-size:12px">{teaser}</p>'
            f'</li>'
        )
    parts.append("</ul>")
    return "\n".join(parts), len(articles), paths


def render_rss_sections(rows) -> tuple[str, int, int, list]:
    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        groups[row["feed_key"]].append(row)

    def order(k: str) -> int:
        for prefix, v in DAILY_ORDER.items():
            if k.startswith(prefix):
                return v
        return 99

    parts, total_count, total_minutes = [], 0, 0
    full_rows_for_zip: list = []

    for fk in sorted(groups, key=order):
        grp = groups[fk]
        parts.append(section_heading(grp[0]["source_name"], len(grp)))
        for i, row in enumerate(grp):
            mode = row["display_mode"]
            kw   = dict(title=row["title"] or "", source_name=row["source_name"],
                        url=row["source_id"], content=row["content"] or "", sep=(i > 0))
            if mode == "full":
                parts.append(_full_teaser_block(**kw, read_minutes=row["read_minutes"] or 0))
                full_rows_for_zip.append(row)
            elif mode == "repo_card":
                parts.append(block_repo_card(**kw))
            elif mode == "chart_only":
                parts.append(chart_table(row["content"] or ""))
            else:
                parts.append(block_title_excerpt(**kw))
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
            title=row["title"], url=row["url"] or row["source_id"],
            score=row["score"], by=row["by"] or "",
            descendants=row["descendants"] or 0, hn_url=row["source_id"],
        ))
    parts.append("</ul>")
    return "\n".join(parts)


def main() -> None:
    issue_id = new_run_id()
    rss_rows = get_unpushed("core", ISSUE_TYPE)
    hn_rows  = get_unpushed_hn(ISSUE_TYPE)

    tldr_html, tldr_count, tldr_paths = render_tldr_section()
    rss_html, rss_count, rss_minutes, full_rows = render_rss_sections(rss_rows)
    hn_html  = render_hn_section(hn_rows)
    total    = rss_count + len(hn_rows) + tldr_count

    # Merge TLDR's already-written .md files with markdown exported from any
    # other "full" core.db rows into a single zip attachment.
    zip_file_count = 0
    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    if tldr_paths or full_rows:
        with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in tldr_paths:
                zf.write(p, arcname=p.name)
                zip_file_count += 1
        if TLDR_TMP_DIR.exists():
            shutil.rmtree(TLDR_TMP_DIR)
        if full_rows:
            # export_full_articles_zip creates its own zip; merge its entries in
            tmp_full_zip = ROOT / "_full_rows.zip"
            n = export_full_articles_zip(full_rows, tmp_full_zip)
            with zipfile.ZipFile(tmp_full_zip) as src, \
                 zipfile.ZipFile(OUT_ZIP, "a", zipfile.ZIP_DEFLATED) as dst:
                for name in src.namelist():
                    dst.writestr(name, src.read(name))
            tmp_full_zip.unlink()
            zip_file_count += n

    summary = (
        f'<p style="margin:0 0 32px;font-size:13px;color:{MUTED};line-height:1.6">'
        f'{total} items &middot; ~{rss_minutes} min read (full articles in attachment)</p>'
    )

    date_str = fmt_date()
    html_out = email_shell(
        title=date_str,
        subtitle=f"{total} items · ~{rss_minutes} min read",
        body=summary + tldr_html + rss_html + hn_html,
        issue_label="Daily",
    )
    OUT_HTML.write_text(html_out, encoding="utf-8")
    OUT_SUBJ.write_text(f"Dewsletter Daily · {date_str} · {total} items")

    for row in rss_rows:
        mark_pushed("core", row["id"], ISSUE_TYPE, issue_id)
    for row in hn_rows:
        mark_pushed_hn(row["id"], ISSUE_TYPE, issue_id)

    zip_note = f", {zip_file_count} full articles → {OUT_ZIP.name}" if zip_file_count else ""
    print(f"render_daily: {rss_count} RSS + {len(hn_rows)} HN + {tldr_count} TLDR{zip_note} → {OUT_HTML.name}")


if __name__ == "__main__":
    main()
