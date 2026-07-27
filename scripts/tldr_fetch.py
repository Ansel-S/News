"""
tldr_fetch.py — Live TLDR fetch + per-article split (not persisted to any DB)

TLDR content is time-sensitive (today's news, sponsor rotations) so it is never
written to core.db. Each run:
  1. Fetches the TLDR Tech / TLDR Dev RSS feeds live.
  2. Parses the markdown body into individual articles (split on level-2/3
     headings), dropping sponsor sections and subscribe/CTA boilerplate.
  3. Writes each article as its own .md file.
  4. Returns a short summary (title + first line) per article for the daily
     email body, plus the list of file paths to zip as an attachment.

No deduplication across runs — TLDR does not repeat stories, per user.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import feedparser
import requests

from render_base import strip_sponsor_and_cta, excerpt

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Dewsletter/1.0)"}

TLDR_FEEDS = [
    ("TLDR Tech", "https://tldr.tech/api/rss/tech"),
    ("TLDR Dev",  "https://tldr.tech/api/rss/dev"),
]

# Article headings in TLDR markdown are level-3 ("### Title (N minute read)").
# Level-2 headings are section dividers ("## Meta Anthropic deal ...") or the
# top newsletter title; level-1 is the "# TLDR 2026-07-20" masthead — none of
# those are individual articles.
_ARTICLE_HEADING_RE = re.compile(r"^###\s+(.*)$", re.M)
_READ_TIME_RE = re.compile(r"\((\d+)\s*minute read\)\s*$", re.I)


@dataclass
class TldrArticle:
    source_name: str
    title: str
    read_minutes: int
    body_md: str          # cleaned markdown body (no sponsor/CTA)


def _fetch_markdown(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception:
        return None
    feed = feedparser.parse(r.content)
    if not feed.entries:
        return None
    # TLDR's RSS puts the full markdown newsletter body in the first entry's
    # summary/content field.
    entry = feed.entries[0]
    if entry.get("content"):
        return entry["content"][0].get("value", "")
    return entry.get("summary", "")


def _normalize_headings(md: str) -> str:
    """TLDR's markdown sometimes runs a sponsor blurb's last sentence directly
    into the next '### Heading' with no line break (e.g. '...works.### Meta in
    Talks...'). Force every '#'-heading marker onto its own line so downstream
    regex matching (which requires headings at line start) doesn't miss them."""
    return re.sub(r"(?<![#\n])(#{1,6}\s)", r"\n\1", md)


def _split_articles(source_name: str, md: str) -> list[TldrArticle]:
    """Split one TLDR issue's markdown into individual article entries."""
    md = _normalize_headings(md)
    cleaned = strip_sponsor_and_cta(md)

    # Also drop any sponsor sub-sections that survive as ### headings
    # containing "(Sponsor)" — strip_sponsor_and_cta only removes headings
    # of any level marked that way, so re-run split on the already-cleaned text.
    positions = [m.start() for m in _ARTICLE_HEADING_RE.finditer(cleaned)]
    if not positions:
        return []
    positions.append(len(cleaned))

    articles: list[TldrArticle] = []
    for i in range(len(positions) - 1):
        chunk = cleaned[positions[i]:positions[i + 1]].strip()
        heading_match = _ARTICLE_HEADING_RE.match(chunk)
        if not heading_match:
            continue
        raw_title = heading_match.group(1).strip()
        if re.search(r"\(sponsor\)", raw_title, re.I):
            continue  # safety net, should already be stripped

        rt_match = _READ_TIME_RE.search(raw_title)
        read_minutes = int(rt_match.group(1)) if rt_match else 0
        title = _READ_TIME_RE.sub("", raw_title).strip()

        body = chunk[heading_match.end():].strip()
        # Drop a trailing standalone emoji/symbol line — TLDR uses these as
        # visual section dividers between category groups, not article content.
        body = re.sub(r"\n+[^\w\s]{1,4}\s*$", "", body).strip()
        if not body:
            continue

        articles.append(TldrArticle(
            source_name=source_name, title=title,
            read_minutes=read_minutes, body_md=body,
        ))
    return articles


def fetch_all() -> list[TldrArticle]:
    """Fetch + parse both TLDR feeds live. Returns [] entries silently skipped on failure."""
    articles: list[TldrArticle] = []
    for name, url in TLDR_FEEDS:
        md = _fetch_markdown(url)
        if not md:
            continue
        articles.extend(_split_articles(name, md))
    return articles


def slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:max_len].strip("-") or "untitled"


def write_markdown_files(articles: list[TldrArticle], out_dir: Path) -> list[Path]:
    """Write one .md file per article. Returns list of file paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    seen_slugs: dict[str, int] = {}

    for a in articles:
        slug = slugify(a.title)
        n = seen_slugs.get(slug, 0)
        seen_slugs[slug] = n + 1
        fname = f"{slug}.md" if n == 0 else f"{slug}-{n}.md"

        header = f"# {a.title}\n\n*{a.source_name}"
        if a.read_minutes:
            header += f" · ~{a.read_minutes} min read"
        header += "*\n\n"

        path = out_dir / fname
        path.write_text(header + a.body_md + "\n", encoding="utf-8")
        paths.append(path)

    return paths


def summary_line(a: TldrArticle) -> str:
    """One-line teaser for the daily email body (title + first sentence)."""
    first_line = excerpt(a.body_md, 140)
    return first_line