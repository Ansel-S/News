"""
AllStar Finance & Tech News Terminal — Feed Aggregator
Fetches RSS/Atom feeds, cleans content, deduplicates, and writes data.json.
Run manually or via GitHub Actions every 4 hours.
"""

import feedparser
import json
import hashlib
import re
import html
import datetime
from urllib.parse import urlparse


# ─────────────────────────────────────────────
#  SOURCE REGISTRY
#  Each source has: id, label, url, column, limit
# ─────────────────────────────────────────────
SOURCES = [
    # ── LEFT COLUMN: Real-time Pulse ──────────────────────────────────
    {
        "id": "reuters",
        "label": "Reuters",
        "icon": "📡",
        "url": "https://feeds.reuters.com/reuters/topNews",
        "column": "pulse",
        "limit": 8,
        "tag": "Global Macro",
    },
    {
        "id": "nbc",
        "label": "NBC News",
        "icon": "📺",
        "url": "https://feeds.nbcnews.com/nbcnews/public/business",
        "column": "pulse",
        "limit": 6,
        "tag": "US Business",
    },
    {
        "id": "thehill",
        "label": "The Hill",
        "icon": "🏛️",
        "url": "https://thehill.com/feed/",
        "column": "pulse",
        "limit": 6,
        "tag": "DC Policy",
    },
    # ── X / Twitter via RSSHub (Real-time Flash) ──────────────────────
    {
        "id": "deltaone",
        "label": "@Deltaone",
        "icon": "⚡",
        "url": "https://rsshub.app/twitter/user/Deltaone",
        "column": "pulse",
        "limit": 5,
        "tag": "Flash News",
    },
    {
        "id": "goldmansachs",
        "label": "@GoldmanSachs",
        "icon": "🏦",
        "url": "https://rsshub.app/twitter/user/GoldmanSachs",
        "column": "pulse",
        "limit": 5,
        "tag": "Institutional",
    },
    {
        "id": "soberlook",
        "label": "@SoberLook",
        "icon": "📊",
        "url": "https://rsshub.app/twitter/user/SoberLook",
        "column": "pulse",
        "limit": 5,
        "tag": "Macro Charts",
    },
    {
        "id": "howardmarks",
        "label": "@HowardMarksBook",
        "icon": "📖",
        "url": "https://rsshub.app/twitter/user/HowardMarksBook",
        "column": "pulse",
        "limit": 5,
        "tag": "Philosophy",
    },
    # ── CENTER COLUMN: Hard Facts ──────────────────────────────────────
    {
        "id": "jpmorgan",
        "label": "J.P. Morgan",
        "icon": "💼",
        "url": "https://www.jpmorgan.com/insights/research/rss.xml",
        "column": "facts",
        "limit": 6,
        "tag": "Research",
    },
    {
        "id": "hackernews",
        "label": "Hacker News",
        "icon": "🔶",
        "url": "https://news.ycombinator.com/rss",
        "column": "facts",
        "limit": 8,
        "tag": "Tech Frontier",
    },
    # ── RIGHT COLUMN: Geek & China ─────────────────────────────────────
    {
        "id": "sspai",
        "label": "少数派 (sspai)",
        "icon": "🐼",
        "url": "https://sspai.com/feed",
        "column": "geek",
        "limit": 6,
        "tag": "CN Tech",
    },
    {
        "id": "v2ex",
        "label": "V2EX",
        "icon": "🧑‍💻",
        "url": "https://www.v2ex.com/feed/tab/tech.xml",
        "column": "geek",
        "limit": 6,
        "tag": "Dev Insights",
    },
    {
        "id": "googledeepmind",
        "label": "@GoogleDeepMind",
        "icon": "🧠",
        "url": "https://rsshub.app/twitter/user/GoogleDeepMind",
        "column": "geek",
        "limit": 5,
        "tag": "AI Research",
    },
    {
        "id": "stabilityai",
        "label": "@StabilityAI",
        "icon": "🎨",
        "url": "https://rsshub.app/twitter/user/StabilityAI",
        "column": "geek",
        "limit": 5,
        "tag": "Gen AI",
    },
]

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def _uid(url: str, title: str) -> str:
    """Deterministic ID for deduplication."""
    raw = (url + title).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def _clean_html(raw: str) -> str:
    """Strip tags, collapse whitespace, decode HTML entities."""
    if not raw:
        return ""
    # Remove script/style blocks
    raw = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    # Remove all remaining HTML tags
    raw = re.sub(r"<[^>]+>", " ", raw)
    # Decode entities
    raw = html.unescape(raw)
    # Collapse whitespace
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def _sanitize_html(raw: str) -> str:
    """
    Light sanitization: keep a safe subset of HTML tags for the reader pane.
    Strips scripts, inline event handlers, and dangerous attributes.
    """
    if not raw:
        return ""
    # Remove script/style
    raw = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    # Remove on* event handlers
    raw = re.sub(r'\s+on\w+="[^"]*"', "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s+on\w+='[^']*'", "", raw, flags=re.IGNORECASE)
    # Remove javascript: hrefs
    raw = re.sub(r'href=["\']javascript:[^"\']*["\']', 'href="#"', raw, flags=re.IGNORECASE)
    return raw.strip()


def _parse_date(entry) -> str:
    """Return ISO-8601 UTC string from feedparser entry."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                dt = datetime.datetime(*t[:6], tzinfo=datetime.timezone.utc)
                return dt.isoformat()
            except Exception:
                pass
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _extract_image(entry) -> str | None:
    """Try to pull a thumbnail/image URL from the entry."""
    # media:thumbnail
    media = getattr(entry, "media_thumbnail", None)
    if media and isinstance(media, list) and media[0].get("url"):
        return media[0]["url"]
    # media:content
    media = getattr(entry, "media_content", None)
    if media and isinstance(media, list):
        for m in media:
            if m.get("medium") == "image" and m.get("url"):
                return m["url"]
    # enclosures
    enclosures = getattr(entry, "enclosures", [])
    for enc in enclosures:
        if "image" in enc.get("type", ""):
            return enc.get("href") or enc.get("url")
    # og:image in content
    content_val = ""
    if hasattr(entry, "content") and entry.content:
        content_val = entry.content[0].get("value", "")
    elif hasattr(entry, "summary"):
        content_val = entry.summary or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content_val, re.IGNORECASE)
    if m:
        url = m.group(1)
        if url.startswith("http"):
            return url
    return None


def fetch_source(source: dict) -> list[dict]:
    """Fetch and parse a single RSS source. Returns list of article dicts."""
    print(f"  → Fetching {source['label']} ({source['url'][:60]}…)")
    try:
        feed = feedparser.parse(
            source["url"],
            request_headers={
                "User-Agent": "AllStarTerminal/1.0 (RSS Reader; +https://github.com)",
                "Accept": "application/rss+xml, application/atom+xml, text/xml, */*",
            },
            timeout=15,
        )
    except Exception as exc:
        print(f"    ✗ Parse error: {exc}")
        return []

    if feed.bozo and not feed.entries:
        print(f"    ✗ Bozo feed, no entries.")
        return []

    articles = []
    for entry in feed.entries[: source["limit"]]:
        title = _clean_html(getattr(entry, "title", "") or "")
        link = getattr(entry, "link", "") or ""
        if not title or not link:
            continue

        # Full HTML body for reader mode
        body_html = ""
        if hasattr(entry, "content") and entry.content:
            body_html = _sanitize_html(entry.content[0].get("value", ""))
        if not body_html and hasattr(entry, "summary"):
            body_html = _sanitize_html(entry.summary or "")

        # Plain-text summary (card preview)
        summary = _clean_html(body_html or getattr(entry, "summary", "") or "")
        if len(summary) > 280:
            summary = summary[:277].rsplit(" ", 1)[0] + "…"

        articles.append(
            {
                "id": _uid(link, title),
                "source_id": source["id"],
                "source_label": source["label"],
                "source_icon": source["icon"],
                "source_tag": source["tag"],
                "column": source["column"],
                "title": title,
                "summary": summary,
                "body_html": body_html,
                "link": link,
                "image": _extract_image(entry),
                "published": _parse_date(entry),
            }
        )

    print(f"    ✓ {len(articles)} articles")
    return articles


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("AllStar Terminal — Feed Aggregation Run")
    print(f"UTC: {datetime.datetime.now(datetime.timezone.utc).isoformat()}")
    print("=" * 60)

    all_articles: list[dict] = []
    seen_ids: set[str] = set()

    for source in SOURCES:
        articles = fetch_source(source)
        for article in articles:
            if article["id"] not in seen_ids:
                seen_ids.add(article["id"])
                all_articles.append(article)

    # Sort each column by published desc
    all_articles.sort(key=lambda a: a["published"], reverse=True)

    output = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total": len(all_articles),
        "articles": all_articles,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("=" * 60)
    print(f"✅ Wrote {len(all_articles)} articles → data.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
