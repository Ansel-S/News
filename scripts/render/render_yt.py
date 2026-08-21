"""
render_yt.py — YouTube weekly (every Wednesday)
Title list grouped by section. No thumbnails.
youtube.db attached as file containing full subtitles.

Section heading comes from each row's own feed_key — the source's
`section` from config, or (for a channel with no shared section) a
fallback to that channel's own name, never the raw channel_id string.
SECTION_LABEL below only needs entries for the *shared, multi-channel*
sections (grouped under config/sources/youtube.yml's `section` field);
anything else already has a readable label by construction, so there's
nothing here that can silently go stale the way a hand-duplicated label
covering every possible feed_key could.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_SCRIPTS_DIR = _Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_SCRIPTS_DIR))
import html as _html
from collections import defaultdict
from pathlib import Path
from db.db_utils import get_unpushed, mark_pushed, get_yt_media, run_id as new_run_id
from config import db_path, yt_feeds
from render.render_base import (
    fmt_date, email_shell, section_heading, export_full_articles_zip,
    MUTED, TEXT, ACCENT, BORDER, MONO,
)

ROOT       = Path(__file__).resolve().parent.parent.parent  # scripts/<subpkg>/this_file.py -> repo root
OUT_HTML   = ROOT / "out_yt.html"
OUT_SUBJ   = ROOT / "out_yt_subject.txt"
OUT_ZIP    = ROOT / "out_yt.zip"
ISSUE_TYPE = "yt_weekly"

SECTION_LABEL: dict[str, str] = {
    "yt.daily.tech":     "Tech & Gadgets",
    "yt.daily.ios":      "iOS & Apple",
    "yt.daily.gfw":      "News & Commentary",
    "yt.digest.finance": "Finance",
    "yt.digest.history": "History",
    "yt.digest.sport":   "Sports",
    "yt.dive.study":     "Science & Learning",
    "yt.dive.politics":  "Politics & Current Affairs",
    "yt.zen":            "Lifestyle",
    "yt.zen.lovers":     "Relationships",
    "yt.zen.music":      "Music",
    "yt.zen.pets":       "Pets",
    "yt.zen.psychology": "Psychology",
}


def _section_order_and_fallback_labels() -> tuple[list[str], dict[str, str]]:
    """(ordered list of every feed_key that actually appears in config,
    fallback label for feed_keys not in SECTION_LABEL — i.e. singleton
    groups, labeled by that channel's own name instead of its raw id)."""
    order: list[str] = []
    fallback: dict[str, str] = {}
    for group in yt_feeds():
        key = group["key"]
        if key not in order:
            order.append(key)
        if key not in SECTION_LABEL and len(group["sources"]) == 1:
            fallback[key] = group["sources"][0]["name"]
    return order, fallback


def video_row(row) -> str:
    title    = _html.escape(row["title"] or "(untitled)")
    url      = _html.escape(row["source_id"])
    ch       = _html.escape(row["source_name"])
    pub      = (row["created_at"] or "")[:10]
    # yt_media_items rows have content=NULL (no subtitle text was ever found)
    has_sub  = bool(row["content"])
    media_links = get_yt_media(row["video_id"])

    is_blocked = (row["mode"] or "") == "blocked"
    badges = []
    if is_blocked:
        badges.append(
            f'<span style="font-size:10px;background:#f3f4f6;color:#6b7280;'
            f'padding:1px 5px;border-radius:3px;font-family:{MONO}">blocked</span>'
        )
    elif has_sub:
        badges.append(
            f'<span style="font-size:10px;background:#dcfce7;color:#166534;'
            f'padding:1px 5px;border-radius:3px;font-family:{MONO}">sub</span>'
        )
    if not is_blocked and media_links.get("video"):
        badges.append(
            f'<a href="{_html.escape(media_links["video"])}" style="font-size:10px;'
            f'background:#dbeafe;color:#1e40af;padding:1px 5px;border-radius:3px;'
            f'font-family:{MONO};text-decoration:none">720p ↓</a>'
        )
    if not is_blocked and media_links.get("audio"):
        badges.append(
            f'<a href="{_html.escape(media_links["audio"])}" style="font-size:10px;'
            f'background:#fef3c7;color:#92400e;padding:1px 5px;border-radius:3px;'
            f'font-family:{MONO};text-decoration:none">audio ↓</a>'
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
    sub_rows   = get_unpushed("youtube", ISSUE_TYPE, table="yt_items")
    media_rows = get_unpushed("youtube", ISSUE_TYPE, table="yt_media_items")
    rows = list(sub_rows) + list(media_rows)
    if not rows:
        print("render_yt: nothing to send")
        return

    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        groups[row["feed_key"]].append(row)

    section_order, fallback_labels = _section_order_and_fallback_labels()

    def order(k: str) -> int:
        try:
            return section_order.index(k)
        except ValueError:
            return 99

    # Only yt_items rows have subtitle text to export; yt_media_items rows
    # are title + download-link only and are shown inline via video_row().
    # yt_items already uses the standard items field names (source_id,
    # source_name, content, created_at), so no custom key mapping needed.
    # fetched_full is always 1 for yt_items (subtitle fetch is the "full
    # fetch" here — see db_utils.insert_yt), but filtering on it explicitly
    # keeps this consistent with how daily/extra decide zip eligibility.
    zip_rows     = [r for r in sub_rows if r["fetched_full"]]
    zip_count    = export_full_articles_zip(zip_rows, OUT_ZIP) if zip_rows else 0
    blocked_rows = [r for r in media_rows if (r["mode"] or "") == "blocked"]
    n_blocked    = len(blocked_rows)

    meta_parts = [f"{len(rows)} videos"]
    if len(sub_rows):
        meta_parts.append(f"{len(sub_rows)} with subtitles")
    if n_blocked:
        meta_parts.append(f"{n_blocked} blocked")
    meta_str = " &middot; ".join(meta_parts)

    parts = [
        f'<p style="margin:0 0 32px;font-size:13px;color:{MUTED}">'
        f'{meta_str}'
        + (
            f' &middot; full subtitles ({zip_count} files) in attached '
            f'<strong style="color:{TEXT}">yt_subtitles.zip</strong>'
            if zip_count else ""
        )
        + (
            f' &middot; 720p/audio downloads linked inline where available'
            if len(media_rows) - n_blocked else ""
        )
        + (
            f' &middot; <span style="color:#6b7280">yt-dlp blocked this run'
            f' — titles only for {n_blocked} video(s)</span>'
            if n_blocked else ""
        )
        + f'</p>'
    ]

    for fk in sorted(groups, key=order):
        label = SECTION_LABEL.get(fk) or fallback_labels.get(fk, fk)
        grp   = groups[fk]
        parts.append(section_heading(label, len(grp)))
        parts.append('<ul style="list-style:none;margin:0;padding:0">')
        for row in grp:
            parts.append(video_row(row))
        parts.append("</ul>")

    date_str = fmt_date()
    subj_extra = f" · {n_blocked} blocked" if n_blocked else ""
    html_out = email_shell(
        title=f"YouTube · {date_str}",
        subtitle=meta_str.replace(" &middot; ", " · "),
        body="\n".join(parts),
        issue_label="YouTube Weekly",
    )
    OUT_HTML.write_text(html_out, encoding="utf-8")
    OUT_SUBJ.write_text(f"Dewsletter YouTube · {date_str} · {len(rows)} videos{subj_extra}")

    for row in rows:
        mark_pushed("youtube", row["id"], ISSUE_TYPE, issue_id)
    print(f"render_yt: {len(rows)} videos ({len(sub_rows)} subtitle + "
          f"{len(media_rows) - n_blocked} media-only + {n_blocked} blocked) → {OUT_HTML.name}")


if __name__ == "__main__":
    main()
