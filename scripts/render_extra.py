"""
render_extra.py — "Dewsletter Extra" email
Renders TLDR (live-fetched, never stored) + Ruanyf Weekly + HelloGitHub as
their own standalone email, separate from the daily digest — these three are
long-form and/or have a predictable rhythm that doesn't fit well folded into
the daily's shorter-form sections.

Ruanyf/HelloGitHub are identified by source_name (see
render_base.EXTRA_SOURCE_NAMES) since feeds/rss.yaml nests them under
rss.daily.tech / rss.daily.github alongside their daily-bound feed-mates,
not a dedicated rss.extra.* key.

Ruanyf rows with a successful full-text fetch (fetched_full=1) are added to
the same zip as TLDR. HelloGitHub is repo_card — never full-text fetched,
never zip-eligible (see ingest_rss.py).

Section order: TLDR (teaser + zip attachment) → Ruanyf Weekly → HelloGitHub
"""
from __future__ import annotations
import html
from pathlib import Path

from db_utils import get_unpushed, mark_pushed, run_id as new_run_id
from render_base import (
    fmt_date, email_shell, section_heading,
    block_title_excerpt, block_repo_card,
    export_full_articles_zip,
    MUTED, TEXT, MONO, BORDER,
)
import tldr_fetch
import zipfile as _zipfile

ROOT       = Path(__file__).resolve().parent.parent
OUT_HTML   = ROOT / "out_extra.html"
OUT_SUBJ   = ROOT / "out_extra_subject.txt"
OUT_ZIP    = ROOT / "out_extra.zip"
ISSUE_TYPE = "extra_daily"


def render_tldr_section() -> tuple[str, int, list]:
    """Fetch TLDR live, return (html_teaser_block, article_count, tldr_articles)
    for the caller to zip separately. Not stored in any db (time-sensitive)."""
    articles = tldr_fetch.fetch_all()
    if not articles:
        return "", 0, []

    total_minutes = sum(a.read_minutes for a in articles)
    parts = [section_heading("TLDR", len(articles))]
    parts.append(
        f'<p style="margin:0 0 14px;font-size:12px;color:{MUTED};line-height:1.6">'
        f'Full articles (~{total_minutes} min total) are in the attached '
        f'<strong style="color:{TEXT}">extra.zip</strong> &mdash; one .md file per story.</p>'
    )
    parts.append('<ul style="list-style:none;margin:0;padding:0">')
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
    return "\n".join(parts), len(articles), articles


def render_rss_section(rows, heading: str, block_fn) -> str:
    if not rows:
        return ""
    parts = [section_heading(heading, len(rows))]
    for i, row in enumerate(rows):
        parts.append(block_fn(
            title=row["title"] or "", source_name=row["source_name"],
            url=row["source_id"], content=row["content"] or "", sep=(i > 0),
        ))
    return "\n".join(parts)


def main() -> None:
    issue_id = new_run_id()

    tldr_html, tldr_count, tldr_articles = render_tldr_section()

    extra_rows = get_unpushed("core", ISSUE_TYPE)
    ruanyf_rows = [r for r in extra_rows if r["source_name"] == "Ruanyf Weekly"]
    hellogh_rows = [r for r in extra_rows if r["source_name"] == "HelloGitHub"]

    ruanyf_html = render_rss_section(ruanyf_rows, "Ruanyf Weekly", block_title_excerpt)
    hellogh_html = render_rss_section(hellogh_rows, "HelloGitHub", block_repo_card)

    total = tldr_count + len(ruanyf_rows) + len(hellogh_rows)
    if total == 0:
        print("render_extra: nothing to send")
        return

    # TLDR articles + any Ruanyf rows with a successful full-text fetch get
    # written + zipped here (separate zip from daily's). HelloGitHub
    # (repo_card) is never zip-eligible — see ingest_rss.py.
    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    zip_count = 0
    ruanyf_full_rows = [r for r in ruanyf_rows if r["fetched_full"]]

    if tldr_articles or ruanyf_full_rows:
        import shutil
        tmp_dir = ROOT / ".extra_tmp"
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        tmp_dir.mkdir(parents=True)

        if tldr_articles:
            tldr_fetch.write_markdown_files(tldr_articles, tmp_dir)
        if ruanyf_full_rows:
            # Reuse export_full_articles_zip's per-row .md writing by pointing
            # it at a throwaway zip, then merge that zip's contents into
            # tmp_dir so both sources land in one final archive.
            ruanyf_zip = ROOT / ".ruanyf_tmp.zip"
            export_full_articles_zip(ruanyf_full_rows, ruanyf_zip)
            with _zipfile.ZipFile(ruanyf_zip) as zf_in:
                zf_in.extractall(tmp_dir)
            ruanyf_zip.unlink()

        with _zipfile.ZipFile(OUT_ZIP, "w", _zipfile.ZIP_DEFLATED) as zf:
            for p in tmp_dir.iterdir():
                zf.write(p, arcname=p.name)
                zip_count += 1
        shutil.rmtree(tmp_dir)

    summary = (
        f'<p style="margin:0 0 32px;font-size:13px;color:{MUTED};line-height:1.6">'
        f'{total} items'
        f'{" &middot; full text in attachment" if zip_count else ""}</p>'
    )

    date_str = fmt_date()
    html_out = email_shell(
        title=date_str,
        subtitle=f"{total} items",
        body=summary + tldr_html + ruanyf_html + hellogh_html,
        issue_label="Extra",
    )
    OUT_HTML.write_text(html_out, encoding="utf-8")
    OUT_SUBJ.write_text(f"Dewsletter Extra · {date_str} · {total} items")

    for row in ruanyf_rows + hellogh_rows:
        mark_pushed("core", row["id"], ISSUE_TYPE, issue_id)

    print(f"render_extra: {tldr_count} TLDR + {len(ruanyf_rows)} Ruanyf + "
          f"{len(hellogh_rows)} HelloGitHub → {OUT_HTML.name}")


if __name__ == "__main__":
    main()
