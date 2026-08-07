"""
config.py — Load feeds from config/sources/*.yml + config/topics.yml +
config/issues.yml (Phase 1 of the architecture redesign — see
migrate_config.py and DESIGN.md).

Every public function below keeps its EXACT original return shape
(rss_feeds() still returns a list of {key, db, issue, sources: [...]}
groups, etc) — every other script in this repo (ingest_rss.py,
ingest_hn.py, ingest_youtube.py, render_*.py) reads config.py's output and
none of them had to change for this migration. What changed is only what's
*behind* these functions: they now reconstruct the old shape from the new
three-layer config instead of reading feeds/*.yaml directly.

feeds/*.yaml is left on disk untouched (not read by this file anymore) —
kept as a reference/rollback copy until Phase 3 replaces this adapter
entirely with a real topic-based issue builder that doesn't need to
reconstruct anything old-shaped.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from collections import defaultdict
import yaml

ROOT      = Path(__file__).resolve().parent.parent
FEEDS_DIR = ROOT / "feeds"          # unused now, kept only as a rollback reference
CONFIG_DIR = ROOT / "config"
DB_DIR    = ROOT / "database"

# Daily section render order (lower = higher up in email) — unchanged from
# before. Still keyed by the exact old feed `key` strings on purpose: any
# row already ingested-but-unsent in a live database has this string
# stored as its feed_key, and render_daily.py looks up order by that exact
# value. Regenerating new synthetic keys here would silently reorder
# anything already queued at deploy time.
DAILY_ORDER: dict[str, int] = {
    "rss.daily.tech":         1,
    "rss.daily.github":       2,
    "rss.digest.ai":          3,
    "rss.digest.engineering":  4,
    "rss.digest.economics":   5,
    "rss.digest.podcast":     6,
    "hn":                     7,
    "rss.daily.music":        8,
}


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _topics() -> dict[str, str]:
    data = _load_yaml(CONFIG_DIR / "topics.yml")
    return {sid: v["topic"] for sid, v in data.get("sources", {}).items()}


def _legacy_keys() -> dict[str, str]:
    """Phase-1-only scaffolding — see migrate_config.py docstring. Delete
    this function and its call sites in Phase 3."""
    path = CONFIG_DIR / "_phase1_legacy_keys.yml"
    if not path.exists():
        return {}
    return _load_yaml(path).get("legacy_keys", {})


def _legacy_group_meta() -> dict[str, dict]:
    """Phase-1-only scaffolding — see migrate_config.py docstring. Delete
    this function and its call sites in Phase 3.

    db/issue were always group-level properties in the old yaml (every
    source within one group shared the same db, same issue) — an earlier
    draft of this adapter tried to re-derive them per-source from topic
    instead, which both got several sources' db wrong (topic doesn't
    cleanly imply db — Billboard/Bandcamp are topic culture.music but
    db core, not zen) and silently collapsed sources that share a legacy
    group but route to different issues (e.g. GitHub Trending Weekly and
    HelloGitHub both live under the old `rss.daily.github` group, but only
    HelloGitHub goes to Extra) down to whichever source's issue was
    computed last. Copying the ground truth at migration time sidesteps
    both problems."""
    path = CONFIG_DIR / "_phase1_legacy_group_meta.yml"
    if not path.exists():
        return {}
    return _load_yaml(path).get("legacy_group_meta", {})


def _issues() -> dict[str, Any]:
    return _load_yaml(CONFIG_DIR / "issues.yml").get("issues", {})


def rss_feeds() -> list[dict[str, Any]]:
    sources = _load_yaml(CONFIG_DIR / "sources" / "rss.yml").get("sources", [])
    legacy = _legacy_keys()
    group_meta = _legacy_group_meta()

    # group sources back by their legacy key so DAILY_ORDER, db, and issue
    # all keep working unmodified — see _legacy_group_meta()'s docstring
    # for why these are looked up per-group instead of re-derived per-source
    groups: dict[str, list[dict]] = defaultdict(list)
    for src in sources:
        sid = src["id"]
        key = legacy.get(sid, sid)
        if key not in group_meta:
            continue  # source not part of any known legacy group — skip

        entry = {"name": src.get("name", _display_name(sid)), "url": src["url"]}
        if "display_mode" in src:
            entry["display_mode"] = src["display_mode"]
        if src.get("fetch") == "live":
            entry["no_store"] = True
        groups[key].append(entry)

    out = []
    for key, srcs in groups.items():
        meta = group_meta[key]
        out.append({"key": key, "db": meta["db"], "issue": meta["issue"], "sources": srcs})
    return out


def _display_name(sid: str) -> str:
    # Fallback only — config/sources/rss.yml now carries the real name
    # (fixed after an initial draft of this adapter reconstructed names
    # from slugs, e.g. "tldr-tech" -> "Tldr Tech" instead of "TLDR Tech",
    # which would have silently changed what every email displays). This
    # only fires if a source is somehow missing its `name` field.
    return sid.replace("-", " ").title()


def hn_config() -> dict[str, Any]:
    sources = _load_yaml(CONFIG_DIR / "sources" / "hn.yml").get("sources", [])
    hn = next((s for s in sources if s["id"] == "hackernews"), {})
    meta = _legacy_group_meta().get("hn", {"db": "hn", "issue": "daily"})
    return {
        "db": meta["db"],
        "issue": meta["issue"],
        "filter": {"min_score": hn.get("min_score", 350), "max_age_hours": hn.get("max_age_hours", 48)},
        "fetch": {"top_n": hn.get("top_n", 200), "workers": hn.get("workers", 10)},
    }


def yt_feeds() -> list[dict[str, Any]]:
    sources = _load_yaml(CONFIG_DIR / "sources" / "youtube.yml").get("sources", [])
    legacy = _legacy_keys()
    group_meta = _legacy_group_meta()

    groups: dict[str, list[dict]] = defaultdict(list)
    for src in sources:
        sid = src["id"]
        key = legacy.get(sid, sid)
        if key not in group_meta:
            continue
        groups[key].append({
            "name": src["name"], "channel_id": src["channel_id"], "mode": src.get("mode", ["mixed"]),
        })

    return [{"key": key, "db": group_meta[key]["db"], "issue": group_meta[key]["issue"], "sources": srcs}
            for key, srcs in groups.items()]


def rss_feeds_for_db(db: str) -> list[dict[str, Any]]:
    return [g for g in rss_feeds() if g.get("db") == db]


def db_path(name: str) -> Path:
    return DB_DIR / f"{name}.db"
