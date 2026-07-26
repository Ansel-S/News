"""
render_yt.py — YouTube weekly (every Wednesday)
Title list grouped by section. No thumbnails.
youtube.db attached as file containing full subtitles.
"""
from __future__ import annotations
import html as _html
from collections import defaultdict
from pathlib import Path
from db_utils import get_unpushed_yt, mark_pushed_yt, run_id as new_run_id
from config import db_path
from render_base import fmt_date, email_shell, section_heading, MUTED, TEXT, ACCENT, BORDER, MONO
import render_yt_markdown

ROOT       = Path(__file__).resolve().parent.parent
OUT_HTML   = ROOT / "out_yt.html"
OUT_SUBJ   = ROOT / "out_yt_subject.txt"
ISSUE_TYPE = "yt_weekly"

SECTION_LABEL: dict[str, str] = {
    "yt.daily.tech":     "Tech & Gadgets",
    "yt.daily.ios":      "iOS & Apple",
    "yt.digest.finance": "Finance",
    "yt.digest.history": "History",
    "yt.digest.sport":   "Sports",
    "yt.dive.science":   "Science",
    "yt.dive.politics":  "Politics & Current Affairs",
    "yt.zen":            "Lifestyle",
    "yt.zen.girl":       "Social",
    "yt.zen.music":      "Music",
    "yt.zen.asmr":       "ASMR",
}
SECTION_ORDER = list(SECTION_LABEL)


def video_row(row) -> str:
    title    = _html.escape(row["title"] or "(untitled)")
    url      = _html.escape(row["video_url"])
    ch       = _html.escape(row["channel_name"])
    pub      = (row["published_at"] or "")[:10]
    has_sub  = bool(row["has_subtitle"])
    media_url = row["media_url"] if "media_url" in row.keys() else None

    badges = []
    if has_sub:
        badges.append(
            f'<span style="font-size:10px;background:#dcfce7;color:#166534;'
            f'padding:1px 5px;border-radius:3px;font-family:{MONO}">sub</span>'
        )
    if media_url:
        badges.append(
            f'<a href="{_html.escape(media_url)}" style="font-size:10px;background:#dbeafe;'
            f'color:#1e40af;padding:1px 5px;border-radius:3px;font-family:{MONO};'
            f'text-decoration:none">720p ↓</a>'
        )
    badge_html = "".join(f" {b}" for b in badges)

    return (
        f'<li style="margin:8px 0;font-size:13px;line-height:1.5">'
        f'<a href="{url}" style="color:{TEXT};text-decoration:none;font-weight:500">{title}</a>'
        f'{badge_html}'
        f' <span style="color:{MUTED};font-size:11px">&mdash; {ch} &middot; {pub}</span>'
        f'</li>'
    )


def main() -> None:
    issue_id = new_run_id()
    rows     = get_unpushed_yt(ISSUE_TYPE)
    if not rows:
        print("render_yt: nothing to send")
        return

    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        groups[row["feed_key"]].append(row)

    def order(k: str) -> int:
        try:
            return SECTION_ORDER.index(k)
        except ValueError:
            return 99

    with_sub = sum(1 for r in rows if r["has_subtitle"])
    zip_count = render_yt_markdown.write_and_zip(rows)

    parts = [
        f'<p style="margin:0 0 32px;font-size:13px;color:{MUTED}">'
        f'{len(rows)} videos &middot; {with_sub} with subtitles &middot; '
        f'full subtitles ({zip_count} files) in attached '
        f'<strong style="color:{TEXT}">yt_subtitles.zip</strong> &middot; '
        f'720p downloads linked inline where available'
        f'</p>'
    ]

    for fk in sorted(groups, key=order):
        label = SECTION_LABEL.get(fk, fk)
        grp   = groups[fk]
        parts.append(section_heading(label, len(grp)))
        parts.append('<ul style="list-style:none;margin:0;padding:0">')
        for row in grp:
            parts.append(video_row(row))
        parts.append("</ul>")

    date_str = fmt_date()
    html_out = email_shell(
        title=f"YouTube · {date_str}",
        subtitle=f"{len(rows)} videos · {with_sub} with subtitles",
        body="\n".join(parts),
        issue_label="YouTube Weekly",
    )
    OUT_HTML.write_text(html_out, encoding="utf-8")
    OUT_SUBJ.write_text(f"Dewsletter YouTube · {date_str} · {len(rows)} videos")

    for row in rows:
        mark_pushed_yt(row["id"], ISSUE_TYPE, issue_id)
    print(f"render_yt: {len(rows)} videos → {OUT_HTML.name}")


if __name__ == "__main__":
    main()
