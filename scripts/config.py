"""
config.py — Load feeds from config/sources/{rss,hn,youtube}.yml.

Each source's full identity (name, url, issues, db/table, display
behavior, optional section label) lives in ONE record in ONE file. See
config/README.md for the record shape.

Every public function keeps its original return shape — no other script
had to change when this replaced the earlier topics.yml/feed_keys.yml/
storage.yml split.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from collections import defaultdict
import yaml

ROOT      = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DB_DIR    = ROOT / "database"


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _sources(kind: str) -> list[dict]:
    return _load_yaml(CONFIG_DIR / "sources" / f"{kind}.yml").get("sources", [])


def rss_sources() -> list[dict]:
    """Full raw source records for every RSS source (not grouped) — for
    callers that need per-source fields beyond what rss_feeds()'s grouped
    shape carries, e.g. render_daily.py's render_style lookup."""
    return _sources("rss")


def rss_feeds() -> list[dict[str, Any]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    group_db: dict[str, str] = {}
    group_issue: dict[str, set[str]] = defaultdict(set)
    for src in _sources("rss"):
        sid = src["id"]
        key = src.get("section", sid)

        entry = {"name": src.get("name", _display_name(sid)), "url": src["url"], "source_key": sid}
        if "extract_mode" in src:
            entry["extract_mode"] = src["extract_mode"]
        if "email_mode" in src:
            entry["email_mode"] = src["email_mode"]
        if src.get("fetch") == "live":
            entry["no_store"] = True
        if "pdf" in src:
            # real field, not a string match on the display feed_key —
            # a prior version broke arXiv routing this way
            entry["pdf"] = src["pdf"]
        if "render_style" in src:
            entry["render_style"] = src["render_style"]
        groups[key].append(entry)
        group_db[key] = src.get("db", "content")
        group_issue[key].update(src.get("issues", []))

    out = []
    for key, srcs in groups.items():
        issues_here = group_issue[key]
        # Nothing downstream reads group["issue"] for groups spanning
        # multiple issues — picking any one deterministically is safe.
        issue = sorted(issues_here)[0] if issues_here else None
        out.append({"key": key, "db": group_db[key], "issue": issue, "sources": srcs})
    return out


def _display_name(sid: str) -> str:
    # Fallback only — real sources always carry their own `name`.
    return sid.replace("-", " ").title()


def hn_config() -> dict[str, Any]:
    sources = _sources("hn")
    hn = next((s for s in sources if s["id"] == "hackernews"), {})
    return {
        "db": hn.get("db", "hn"),
        "issue": sorted(hn.get("issues", ["daily"]))[0],
        "filter": {"min_score": hn.get("min_score", 350), "max_age_hours": hn.get("max_age_hours", 48)},
        "fetch": {"top_n": hn.get("top_n", 200), "workers": hn.get("workers", 10)},
    }


def yt_feeds() -> list[dict[str, Any]]:
    # YouTube's db/issue aren't derived from config — routing there is
    # per-video (subtitle vs not), not per-source. See issues/builder.py.
    groups: dict[str, list[dict]] = defaultdict(list)
    for src in _sources("youtube"):
        sid = src["id"]
        key = src.get("section", sid)
        groups[key].append({
            "name": src["name"], "channel_id": src["channel_id"], "mode": src.get("mode", ["mixed"]),
        })

    return [{"key": key, "db": "youtube", "issue": "yt_weekly", "sources": srcs}
            for key, srcs in groups.items()]


def rss_feeds_for_db(db: str) -> list[dict[str, Any]]:
    return [g for g in rss_feeds() if g.get("db") == db]


def db_path(name: str) -> Path:
    return DB_DIR / f"{name}.db"
