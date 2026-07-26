"""
gen_opml.py — Export all feed sources across rss.yaml / hn.yaml / yt.yaml
into a single feed.opml, for importing into any RSS reader (e.g. to follow
the same sources Dewsletter aggregates, or to re-import into a new reader).

Usage:
  python scripts/gen_opml.py                    # writes feed.opml at repo root
  python scripts/gen_opml.py --out custom.opml
"""
from __future__ import annotations

import argparse
import html
from datetime import datetime, UTC
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from config import rss_feeds, yt_feeds, hn_config, FEEDS_DIR

ROOT = Path(__file__).resolve().parent.parent


def _outline(text: str, *, xml_url: str | None = None, feed_type: str = "rss",
             is_folder: bool = False, children: str = "") -> str:
    title = xml_escape(text)
    if is_folder:
        return f'<outline text="{title}" title="{title}">\n{children}</outline>\n'
    url_attr = f' xmlUrl="{xml_escape(xml_url)}"' if xml_url else ""
    return (f'<outline type="{feed_type}" text="{title}" title="{title}"'
            f'{url_attr} htmlUrl="{xml_escape(xml_url or "")}"/>\n')


def build_rss_outlines() -> str:
    parts = []
    for group in rss_feeds():
        key = group["key"]
        sources = group.get("sources", [])
        children = []
        for src in sources:
            url = src.get("url", "")
            if not url or url == "FILL_ME":
                continue
            children.append(_outline(src["name"], xml_url=url))
        if children:
            parts.append(_outline(key, is_folder=True, children="".join(children)))
    return "".join(parts)


def build_yt_outlines() -> str:
    parts = []
    for group in yt_feeds():
        key = group["key"]
        sources = group.get("sources", [])
        children = []
        for src in sources:
            cid = src.get("channel_id", "")
            if not cid or cid == "FILL_ME":
                continue
            feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
            children.append(_outline(src["name"], xml_url=feed_url))
        if children:
            parts.append(_outline(f"youtube.{key}", is_folder=True, children="".join(children)))
    return "".join(parts)


def build_hn_outline() -> str:
    # HN isn't a per-source RSS list — it's a single algorithmic feed. Include
    # the official HN RSS as one entry for completeness.
    return _outline("Hacker News (front page)",
                     xml_url="https://news.ycombinator.com/rss")


def build_opml() -> str:
    now = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
    body = build_rss_outlines() + build_yt_outlines() + build_hn_outline()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
<head>
  <title>Dewsletter — all feeds</title>
  <dateCreated>{now}</dateCreated>
</head>
<body>
{body}</body>
</opml>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "feed.opml"))
    args = ap.parse_args()

    opml = build_opml()
    out_path = Path(args.out)
    out_path.write_text(opml, encoding="utf-8")
    print(f"gen_opml: wrote {out_path}")


if __name__ == "__main__":
    main()
