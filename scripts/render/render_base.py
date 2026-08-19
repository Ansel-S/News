"""
render_base.py — Email HTML rendering primitives (all English)
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_SCRIPTS_DIR = _Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_SCRIPTS_DIR))
import html
import re
from datetime import datetime, UTC

# ── Design tokens ─────────────────────────────────────────────────────────────
BG      = "#f8f8fa"
SURFACE = "#ffffff"
BORDER  = "#e2e2ea"
MUTED   = "#8a8a9a"
TEXT    = "#1c1c2a"
ACCENT  = "#2563eb"
TAG_BG  = "#f0f0f6"

FONT = ("'Helvetica Neue',Arial,'Liberation Sans',"
        "'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif")
MONO = "ui-monospace,'Cascadia Code','Menlo','Consolas',monospace"


# ── Date helpers ──────────────────────────────────────────────────────────────

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

def fmt_date(dt: datetime | None = None) -> str:
    if dt is None:
        dt = datetime.now(UTC)
    wd = WEEKDAYS[dt.weekday()]
    return dt.strftime(f"{wd}, %B %-d, %Y")


def fmt_date_range(start: datetime, end: datetime) -> str:
    return f"{start.strftime('%b %-d')} – {end.strftime('%b %-d, %Y')}"


# ── Text helpers ──────────────────────────────────────────────────────────────

def excerpt(text: str, chars: int = 200) -> str:
    if not text:
        return ""
    flat = " ".join(text.split())
    return flat if len(flat) <= chars else flat[:chars].rsplit(" ", 1)[0] + "…"


def _inline_md(text: str) -> str:
    """Inline markdown: bold, italic, inline code, links. Input is already html-escaped."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"`([^`]+)`", r"<code style='background:#f0f0f6;padding:1px 4px;"
                                  r"border-radius:3px;font-size:0.9em'>\1</code>", text)
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^\)]+)\)",
        r'<a href="\2" style="color:' + ACCENT + r'">\1</a>',
        text,
    )
    return text


# Sponsor-detection: TLDR (and similar newsletters) mark sponsored blurbs with
# a "(Sponsor)" suffix on the heading. We drop the whole heading+paragraph(s)
# that follow, up to the next heading, rather than matching specific wording,
# so this keeps working even if the sponsor copy changes.
_SPONSOR_HEADING_RE = re.compile(r"^(#{1,6})\s*.*\(sponsor\)\s*$", re.I)

# Trailing subscribe/CTA boilerplate ("Get the most interesting stories...",
# "Join N readers...", "one daily email", etc). Matched loosely by shape
# (short promo lines mentioning "readers"/"daily email"/"subscribe"), not by
# hardcoding exact copy, so it survives wording tweaks.
_CTA_LINE_RE = re.compile(
    r"(join\s+[\d,]+\s+readers|one\s+daily\s+email|delivered in a free daily email|"
    r"subscribe (for|to) free|sign up for free)",
    re.I,
)


def _is_heading(line: str) -> re.Match | None:
    return re.match(r"^(#{1,6})\s+(.*)$", line)


def strip_sponsor_and_cta(md_text: str) -> str:
    """Remove sponsor sections (heading contains '(Sponsor)') and trailing
    subscribe/CTA boilerplate lines from a markdown blob."""
    if not md_text:
        return md_text

    lines = md_text.split("\n")
    out: list[str] = []
    skipping_sponsor = False

    for line in lines:
        heading = _is_heading(line)
        if heading:
            if _SPONSOR_HEADING_RE.match(line):
                skipping_sponsor = True
                continue
            skipping_sponsor = False  # a new, non-sponsor heading ends the skip
        if skipping_sponsor:
            continue
        if _CTA_LINE_RE.search(line):
            continue
        out.append(line)

    # Collapse resulting multiple blank lines
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def md_to_html(text: str, *, strip_sponsors: bool = False) -> str:
    """Markdown → HTML: headings, paragraphs, bold/italic/code, links, bullet lists."""
    if not text:
        return ""
    if strip_sponsors:
        text = strip_sponsor_and_cta(text)

    lines = text.split("\n")
    out: list[str] = []
    in_ul = False

    heading_sizes = {1: 20, 2: 18, 3: 16, 4: 15, 5: 14, 6: 13}

    for raw_line in lines:
        line = raw_line.rstrip()
        heading = _is_heading(line)

        if heading:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            level = len(heading.group(1))
            content = _inline_md(html.escape(heading.group(2).strip()))
            size = heading_sizes.get(level, 13)
            out.append(
                f"<p style='margin:16px 0 8px;font-size:{size}px;font-weight:700;"
                f"line-height:1.4;color:{TEXT}'>{content}</p>"
            )
            continue

        if re.match(r"^[-*] ", line):
            if not in_ul:
                out.append("<ul style='margin:8px 0 8px 18px;padding:0'>")
                in_ul = True
            item = _inline_md(html.escape(line[2:]))
            out.append(f"<li style='margin:3px 0;line-height:1.65'>{item}</li>")
            continue

        if in_ul:
            out.append("</ul>")
            in_ul = False

        if line.strip():
            para = _inline_md(html.escape(line))
            out.append(f"<p style='margin:0 0 10px;line-height:1.75'>{para}</p>")

    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


# ── Email shell ───────────────────────────────────────────────────────────────

def email_shell(title: str, subtitle: str, body: str, issue_label: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
</head>
<body style="margin:0;padding:0;background:{BG};font-family:{FONT};color:{TEXT};
             -webkit-text-size-adjust:100%">
<div style="max-width:660px;margin:0 auto;padding:36px 20px 64px">

  <header style="padding-bottom:20px;margin-bottom:32px;border-bottom:2px solid {TEXT}">
    <p style="margin:0 0 6px;font-size:10px;font-weight:700;letter-spacing:.12em;
              text-transform:uppercase;color:{MUTED};font-family:{MONO}"
    >Dewsletter &middot; {html.escape(issue_label)}</p>
    <h1 style="margin:0 0 6px;font-size:26px;font-weight:700;
               letter-spacing:-.02em;line-height:1.2;color:{TEXT}">{html.escape(title)}</h1>
    <p style="margin:0 0 8px;font-size:13px;color:{MUTED};line-height:1.5">{html.escape(subtitle)}</p>
    <p style="margin:0;font-size:11px;color:{MUTED};line-height:1.5">
      from <a href="https://github.com/asong56" style="color:{MUTED};text-decoration:underline"
      >asong56</a>
    </p>
  </header>

  <main>{body}</main>

  <footer style="margin-top:48px;padding-top:20px;border-top:1px solid {BORDER};text-align:center">
    <a href="https://github.com/asong56/dewsletter" style="color:{MUTED};text-decoration:none;
       display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:600;
       letter-spacing:.03em">
      <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
        <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38
                 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13
                 -.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07
                 -1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12
                 0 0 .67-.21 2.2.82a7.6 7.6 0 0 1 4 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08
                 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48
                 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/>
      </svg>DewsLetter
    </a>
  </footer>

</div>
</body>
</html>"""


# ── Section heading ───────────────────────────────────────────────────────────

def section_heading(label: str, count: int | None = None) -> str:
    cnt = (f" <span style='font-weight:400;color:{MUTED}'>({count})</span>"
           if count is not None else "")
    return (
        f'<div style="margin:40px 0 16px;padding-bottom:8px;border-bottom:1px solid {BORDER}">'
        f'<p style="margin:0;font-size:10px;font-weight:700;letter-spacing:.12em;'
        f'text-transform:uppercase;color:{MUTED};font-family:{MONO}">'
        f'{html.escape(label)}{cnt}</p></div>'
    )


# ── Full-article markdown export (for zip attachments) ───────────────────────
# Raw sqlite attachments require `duckdb --ui` to read and are not pleasant.
# Any row with fetched_full=1 (successful full-text extraction — independent
# of email_mode) gets its full text exported as one .md file per article,
# zipped as an email attachment instead — plain text opens anywhere, isn't
# flagged as suspicious by mail clients, and compresses far better than an
# HTML/db attachment would.

import zipfile as _zipfile
import shutil as _shutil
from pathlib import Path as _Path


def _slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^\w\s-]", "", text or "", flags=re.UNICODE).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:max_len].strip("-") or "untitled"


def export_full_articles_zip(rows, zip_path, *, title_key="title",
                              source_key="source_name", url_key="source_id",
                              content_key="content", date_key="created_at",
                              group_key="source_name") -> int:
    """Write one .md file per row to a temp dir and zip it to zip_path,
    organized into one subfolder per `group_key` value (default:
    source_name) instead of a flat pile of files — makes a 30+-article zip
    actually navigable. Returns the number of files written."""
    zip_path = _Path(zip_path)
    tmp_dir = zip_path.with_suffix("")  # e.g. out_daily.zip -> out_daily/
    if tmp_dir.exists():
        _shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)

    seen: dict[tuple[str, str], int] = {}
    paths: list[_Path] = []
    for row in rows:
        title  = row[title_key] or "(untitled)"
        folder = _slugify(row[group_key]) if group_key in row.keys() else "misc"
        slug   = _slugify(title)
        n      = seen.get((folder, slug), 0)
        seen[(folder, slug)] = n + 1
        fname  = f"{slug}.md" if n == 0 else f"{slug}-{n}.md"

        header = f"# {title}\n\n*{row[source_key]}"
        date = (row[date_key] or "")[:10] if date_key in row.keys() else ""
        if date:
            header += f" · {date}"
        header += f"*\n\n{row[url_key]}\n\n---\n\n"

        folder_dir = tmp_dir / folder
        folder_dir.mkdir(exist_ok=True)
        path = folder_dir / fname
        path.write_text(header + (row[content_key] or "") + "\n", encoding="utf-8")
        paths.append(path)

    if zip_path.exists():
        zip_path.unlink()
    with _zipfile.ZipFile(zip_path, "w", _zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, arcname=str(p.relative_to(tmp_dir)))
    _shutil.rmtree(tmp_dir)
    return len(paths)


def export_pdf_zip(rows, zip_path, *, title_key="title",
                   pdf_key="pdf_data", max_total_bytes: int = 18_000_000) -> tuple[int, int]:
    """Write one .pdf file per row (only rows with a non-empty pdf blob) into
    zip_path. Used by render_research.py (both arXiv papers, from content.db,
    and thinktank reports, from report.db) — rows that failed to download a
    PDF are simply skipped, so failed fetches never end up in the zip.

    max_total_bytes caps the *uncompressed* PDF bytes written, stopping
    before the zip grows large enough to blow past email provider size
    limits — this is exactly what caused a real Report Monthly send to
    bounce (Gmail's raw limit is 25MB, and base64 attachment encoding
    inflates that by ~33%, so 18MB of raw PDF bytes leaves real headroom
    even for a large batch). PDFs are added in row order; once the running
    total would exceed the cap, remaining PDFs are skipped for this run —
    render_simple_digest marks every row in `rows` pushed regardless of zip
    inclusion, so skipped PDFs are NOT re-attempted next issue — they're
    still listed by title in the email, just not attached this time.

    Returns (files_written, files_skipped_for_size)."""
    zip_path = _Path(zip_path)
    if zip_path.exists():
        zip_path.unlink()

    seen: dict[str, int] = {}
    count = 0
    skipped = 0
    running_bytes = 0
    with _zipfile.ZipFile(zip_path, "w", _zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            data = row[pdf_key] if pdf_key in row.keys() else None
            if not data:
                continue
            if running_bytes + len(data) > max_total_bytes:
                skipped += 1
                continue
            title = row[title_key] or "(untitled)"
            slug  = _slugify(title)
            n     = seen.get(slug, 0)
            seen[slug] = n + 1
            fname = f"{slug}.pdf" if n == 0 else f"{slug}-{n}.pdf"
            zf.writestr(fname, data)
            running_bytes += len(data)
            count += 1
    return count, skipped


def render_simple_digest(
    *,
    db: str,
    issue_type: str,
    title_prefix: str,
    issue_label: str,
    subject_prefix: str,
    out_name: str,
    block_dispatch,
    table: str = "items",
    group_by: str = "source_name",
    group_label_fn=None,
    show_group_count: bool = True,
    wrap_ul: bool = False,
    pre_hook=None,
    summary_fn=None,
    use_builder: bool = False,
) -> None:
    """Generic 'weekly digest' renderer shared by render_dive.py, render_zen.py,
    render_research.py — three scripts that are all really the same shape:
    query unpushed rows, group them, dispatch each row to a
    block-rendering function, write the email, mark pushed. Each caller
    just supplies the bits that differ.

    block_dispatch(row, is_first_in_group) -> html string for one row. The
        is_first_in_group flag lets callers suppress a leading separator line
        (e.g. block_full's `sep` argument) for the first item under each
        heading, matching the original per-script behavior. Callers whose
        block function has no separator concept (e.g. block_title_only) can
        just ignore the second argument.
    group_label_fn(group_key, rows) -> heading text for a group (defaults to
        group_key itself — used by paper.py's feed_key -> human label mapping).
    show_group_count: whether section_heading() shows "(N)" after the label.
    wrap_ul: wrap each group's rows in <ul>...</ul> (paper.py's <li>-based
        block_title_only needs this; article-based blocks like block_full
        don't want it).
    pre_hook(rows) -> optional extra dict merged into the template context
        (e.g. report.py's PDF-writing step, which returns pdf_count/pdf_files
        for use in the subject/summary line). Return {} if nothing to add.
    summary_fn(rows, extra) -> override the one-line summary paragraph; by
        default just says "N items".
    use_builder: if True, fetch rows via issues.builder.build(issue_type)
        instead of get_unpushed(db, issue_type, table=table) directly.
        Raises IssueNotFullyScoped if the issue's sources don't exclusively
        occupy their db/table and that table has no source_key column to
        filter by instead — deliberately not caught here (a render script
        asking for an unsupported issue should fail loudly, not silently
        fall back to the old query path and mask the gap). An issue can
        span more than one db (research_weekly: content.db's papers +
        report.db's reports) — mark_pushed() is called per-row against
        whichever db that row actually came from, not the single `db`
        kwarg above (which is ignored when use_builder=True).
    """
    from collections import defaultdict
    from pathlib import Path
    from db.db_utils import get_unpushed, mark_pushed, run_id as new_run_id

    root      = Path(__file__).resolve().parent.parent.parent  # scripts/<subpkg>/this_file.py -> repo root
    out_html  = root / f"{out_name}.html"
    out_subj  = root / f"{out_name}_subject.txt"

    issue_id = new_run_id()
    if use_builder:
        from issues.builder import build as build_issue
        tagged   = build_issue(issue_type)          # [(db_name, row), ...]
        rows     = [row for _db, row in tagged]
        row_db   = {row["id"]: _db for _db, row in tagged}  # for per-row mark_pushed below —
                                                              # an issue can now span more than
                                                              # one db (research_weekly: content.db
                                                              # + report.db), so a single fixed
                                                              # `db` kwarg isn't enough anymore
    else:
        rows   = get_unpushed(db, issue_type, table=table)
        row_db = None
    if not rows:
        print(f"{out_name}: nothing to send")
        return

    extra = pre_hook(rows) if pre_hook else {}

    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        groups[row[group_by]].append(row)

    if summary_fn:
        summary_text = summary_fn(rows, extra)
    else:
        summary_text = f"{len(rows)} items"

    parts = [f'<p style="margin:0 0 32px;font-size:13px;color:{MUTED}">{summary_text}</p>']
    for key in sorted(groups):
        grp   = groups[key]
        label = group_label_fn(key, grp) if group_label_fn else key
        heading_count = len(grp) if show_group_count else None
        parts.append(section_heading(label, heading_count) if heading_count is not None
                     else section_heading(label))
        if wrap_ul:
            parts.append('<ul style="list-style:none;margin:0;padding:0">')
        for i, row in enumerate(grp):
            parts.append(block_dispatch(row, i == 0))
        if wrap_ul:
            parts.append("</ul>")

    date_str = fmt_date()
    html_out = email_shell(
        title=f"{title_prefix} · {date_str}",
        subtitle=summary_text,
        body="\n".join(parts),
        issue_label=issue_label,
    )
    out_html.write_text(html_out, encoding="utf-8")
    out_subj.write_text(f"{subject_prefix} · {date_str} · {len(rows)} items")

    for row in rows:
        mark_pushed(row_db[row["id"]] if row_db else db, row["id"], issue_type, issue_id)
    print(f"{out_name}: {len(rows)} items → {out_html.name}")


# ── Block renderers ───────────────────────────────────────────────────────────

def block_full(title: str, source_name: str, url: str,
               content: str, read_minutes: int, sep: bool = True) -> str:
    sep_css = f"border-top:1px solid {BORDER};padding-top:24px;margin-top:24px;" if sep else ""
    rm      = f" &middot; ~{read_minutes} min" if read_minutes else ""
    return f"""
<article style="{sep_css}">
  <p style="margin:0 0 5px;font-size:10px;font-weight:700;letter-spacing:.10em;
            text-transform:uppercase;color:{MUTED};font-family:{MONO}"
  >{html.escape(source_name)}{rm}</p>
  <h2 style="margin:0 0 12px;font-size:19px;font-weight:700;line-height:1.35;
             letter-spacing:-.01em;color:{TEXT}">
    <a href="{html.escape(url)}" style="color:inherit;text-decoration:none"
    >{html.escape(title or '(untitled)')}</a>
  </h2>
  <div style="font-size:14px;line-height:1.75;color:{TEXT}">{md_to_html(content, strip_sponsors=True)}</div>
</article>"""


def block_title_excerpt(title: str, source_name: str, url: str,
                        content: str, sep: bool = True) -> str:
    sep_css = f"border-top:1px solid {BORDER};padding-top:20px;margin-top:20px;" if sep else ""
    pre     = html.escape(excerpt(content, 180))
    return f"""
<article style="{sep_css}">
  <p style="margin:0 0 4px;font-size:10px;font-weight:700;letter-spacing:.10em;
            text-transform:uppercase;color:{MUTED};font-family:{MONO}"
  >{html.escape(source_name)}</p>
  <h3 style="margin:0 0 8px;font-size:16px;font-weight:600;line-height:1.4;color:{TEXT}">
    <a href="{html.escape(url)}" style="color:inherit;text-decoration:none"
    >{html.escape(title or '(untitled)')}</a>
  </h3>
  <p style="margin:0 0 8px;font-size:13px;line-height:1.65;color:{TEXT}">{pre}</p>
  <a href="{html.escape(url)}" style="font-size:12px;color:{ACCENT};text-decoration:none"
  >Read more &rarr;</a>
</article>"""


def block_title_only(title: str, source_name: str, url: str) -> str:
    return (
        f'<li style="margin:6px 0;font-size:13px;line-height:1.5">'
        f'<a href="{html.escape(url)}" style="color:{TEXT};text-decoration:none">'
        f'{html.escape(title or "(untitled)")}</a>'
        f' <span style="color:{MUTED};font-size:11px">&mdash; {html.escape(source_name)}</span>'
        f'</li>'
    )


def block_repo_card(title: str, source_name: str, url: str,
                    content: str, sep: bool = True) -> str:
    sep_css = f"border-top:1px solid {BORDER};padding-top:16px;margin-top:16px;" if sep else ""
    desc    = html.escape(excerpt(content, 120))
    return f"""
<article style="{sep_css}">
  <p style="margin:0 0 3px;font-size:10px;font-weight:700;letter-spacing:.10em;
            text-transform:uppercase;color:{MUTED};font-family:{MONO}"
  >{html.escape(source_name)}</p>
  <h3 style="margin:0 0 5px;font-size:15px;font-weight:600;font-family:{MONO};color:{ACCENT}">
    <a href="{html.escape(url)}" style="color:inherit;text-decoration:none"
    >{html.escape(title or '')}</a>
  </h3>
  <p style="margin:0;font-size:13px;line-height:1.55;color:{TEXT}">{desc}</p>
</article>"""


def block_hn(title: str, url: str, score: int,
             by: str, descendants: int, hn_url: str) -> str:
    link = html.escape(url or hn_url)
    hu   = html.escape(hn_url)
    return (
        f'<li style="margin:8px 0;font-size:13px;line-height:1.5">'
        f'<a href="{link}" style="color:{TEXT};text-decoration:none;font-weight:500">'
        f'{html.escape(title or "")}</a>'
        f' <span style="color:{MUTED};font-size:11px;font-family:{MONO}">'
        f'&#9650;{score} &middot; {html.escape(by)} &middot; '
        f'<a href="{hu}" style="color:{MUTED}">{descendants} comments</a>'
        f'</span></li>'
    )


def chart_table(markdown_table: str) -> str:
    """Convert markdown table to HTML table."""
    lines = [l for l in markdown_table.strip().splitlines() if l.strip()]
    if len(lines) < 3:
        return (f"<pre style='font-family:{MONO};font-size:12px'>"
                f"{html.escape(markdown_table)}</pre>")

    def row(cells: list[str], tag: str) -> str:
        return "<tr>" + "".join(
            f"<{tag} style='padding:6px 12px;text-align:left;"
            f"border-bottom:1px solid {BORDER}'>{html.escape(c.strip())}</{tag}>"
            for c in cells if c.strip()
        ) + "</tr>"

    rows = []
    for i, line in enumerate(lines):
        if "|---" in line:
            continue
        cells = line.split("|")[1:-1]  # strip outer pipes
        rows.append(row(cells, "th" if i == 0 else "td"))

    return (f'<table style="width:100%;border-collapse:collapse;font-size:13px;margin:12px 0">'
            f'{"".join(rows)}</table>')
