"""
render_base.py — Email HTML rendering primitives (all English)
"""
from __future__ import annotations
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
    <h1 style="margin:0 0 8px;font-size:26px;font-weight:700;
               letter-spacing:-.02em;line-height:1.2;color:{TEXT}">{html.escape(title)}</h1>
    <p style="margin:0;font-size:13px;color:{MUTED};line-height:1.5">{html.escape(subtitle)}</p>
  </header>

  <main>{body}</main>

  <footer style="margin-top:48px;padding-top:20px;border-top:1px solid {BORDER}">
    <p style="margin:0 0 10px;font-size:11px;color:{MUTED};line-height:1.6">
      Generated by <strong style="color:{TEXT}">Dewsletter</strong>
      &middot; GitHub Actions &middot; RSS aggregator
    </p>
    <p style="margin:0;font-size:11px;color:{MUTED};line-height:1.6">
      <a href="https://github.com/asong56" style="color:{MUTED};text-decoration:none;
         display:inline-flex;align-items:center;vertical-align:middle">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"
             style="vertical-align:middle;margin-right:4px" aria-hidden="true">
          <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38
                   0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13
                   -.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07
                   -1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12
                   0 0 .67-.21 2.2.82a7.6 7.6 0 0 1 4 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08
                   2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48
                   0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/>
        </svg>github.com/asong56</a>
      &middot;
      <a href="https://github.com/asong56/dewsletter" style="color:{MUTED};text-decoration:none"
      >github.com/asong56/dewsletter</a>
    </p>
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
# Any section rendered with display_mode == "full" gets its full text exported
# as one .md file per article, zipped as an email attachment instead — plain
# text opens anywhere, isn't flagged as suspicious by mail clients, and
# compresses far better than an HTML/db attachment would.

import zipfile as _zipfile
import shutil as _shutil
from pathlib import Path as _Path


def _slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^\w\s-]", "", text or "", flags=re.UNICODE).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:max_len].strip("-") or "untitled"


def export_full_articles_zip(rows, zip_path, *, title_key="title",
                              source_key="source_name", url_key="source_id",
                              content_key="content", date_key="created_at") -> int:
    """Write one .md file per row to a temp dir and zip it to zip_path.
    Only call this with rows whose display_mode == 'full' already filtered.
    Returns the number of files written."""
    zip_path = _Path(zip_path)
    tmp_dir = zip_path.with_suffix("")  # e.g. out_daily.zip -> out_daily/
    if tmp_dir.exists():
        _shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)

    seen: dict[str, int] = {}
    paths: list[_Path] = []
    for row in rows:
        title = row[title_key] or "(untitled)"
        slug  = _slugify(title)
        n     = seen.get(slug, 0)
        seen[slug] = n + 1
        fname = f"{slug}.md" if n == 0 else f"{slug}-{n}.md"

        header = f"# {title}\n\n*{row[source_key]}"
        date = (row[date_key] or "")[:10] if date_key in row.keys() else ""
        if date:
            header += f" · {date}"
        header += f"*\n\n{row[url_key]}\n\n---\n\n"

        path = tmp_dir / fname
        path.write_text(header + (row[content_key] or "") + "\n", encoding="utf-8")
        paths.append(path)

    if zip_path.exists():
        zip_path.unlink()
    with _zipfile.ZipFile(zip_path, "w", _zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, arcname=p.name)
    _shutil.rmtree(tmp_dir)
    return len(paths)


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
