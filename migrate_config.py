#!/usr/bin/env python3
"""
migrate_config.py — Phase 1 of the config-layer redesign.

Reads the CURRENT feeds/rss.yaml, feeds/hn.yaml, feeds/yt.yaml and writes:
  config/sources/rss.yml
  config/sources/hn.yml
  config/sources/youtube.yml
  config/topics.yml
  config/issues.yml

feeds/*.yaml is left untouched — this is purely additive. The only
hand-authored judgment call here is TOPIC_MAP (old feed `key` -> topic
dot-path); everything else is a mechanical field rename/reshape so there's
no risk of silently dropping or duplicating a source.

Deliberate exception: TLDR / Ruanyf Weekly / HelloGitHub get topics under a
dedicated `extra.*` branch instead of their content-shape-implied topic
(digest.tech / essay.technology / digest.opensource) — putting them under
those broader branches would make them get swept up by Daily's or Dive's
topic-prefix `include` rules, which is exactly the bug that was already
fixed once (they were missing from Extra for months because of a similar
routing mismatch). `extra.*` is a legitimate 6th topic branch (content
that's daily-adjacent but doesn't fit the daily digest's brevity), not a
taxonomy failure — same rationale as TLDR's existing `fetch: live` flag
being a named exception rather than a forced fit.

Second deliberate design fix, found while first running this script: topic
alone can't distinguish "digest.tech from an RSS feed" from "digest.tech
from a YouTube channel" — two different collectors can legitimately share
a topic while needing to land in different issues (Daily never wants
video, YT Weekly never wants articles). Every topic-based include rule in
the generated issues.yml is therefore scoped by `collector` as well as
`topic`, not topic alone.

Third thing this script produces: config/_phase1_legacy_keys.yml — a
source_id -> original feed `key` map. This is Phase-1-only scaffolding,
not part of the target design: config.py's adapter needs it to
reconstruct groups using the EXACT original key strings (`rss.daily.tech`
etc), because config.py's DAILY_ORDER dict and any already-ingested,
not-yet-sent rows already sitting in a live database both key off that
exact string. Inventing new synthetic group keys instead would silently
reorder or misplace anything mid-flight at deploy time. Delete this file
in Phase 3 once the real issue builder replaces the adapter and nothing
reads `feed_key` as an ordering key anymore.

Fourth thing: config/_phase1_legacy_group_meta.yml — legacy key -> the
ORIGINAL group's {db, issue}. Also Phase-1-only scaffolding. Needed
because db/issue were group-level properties in the old yaml, and
re-deriving them from topic via a heuristic (an earlier draft of this
adapter tried that) got them wrong for several sources — e.g. Billboard/
Bandcamp's topic is culture.music but their db was core, not zen; Quanta
Magazine's topic doesn't cleanly imply paper.db either. Copying the
ground truth at migration time is more robust than guessing from topic
at adapter time.
"""
from __future__ import annotations
import re
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FEEDS = ROOT / "feeds"
CONFIG = ROOT / "config"

# ── old feed `key` -> topic dot-path ────────────────────────────────────────
# This is the one real judgment call in this script. Everything else below
# is a mechanical reshape. Topic branches follow the user's own proposed
# knowledge-type taxonomy: news / digest / essay / research / culture, plus
# the `extra` exception branch documented above.
TOPIC_MAP = {
    "rss.daily.tech":        "digest.tech",        # TLDR handled as an override below (extra.*)
    "rss.daily.github":      "digest.tech",         # GitHub Trending; HelloGitHub overridden below
    "rss.daily.music":       "culture.music",
    "rss.digest.podcast":    "digest.podcast",
    "rss.digest.ai":         "digest.ai",
    "rss.digest.engineering":"digest.engineering",
    "rss.digest.economics":  "digest.economics",
    "rss.dive":              "essay.general",
    "rss.research.cs":       "research.papers",
    "rss.research.science":  "research.science",
    "rss.research.economics":"research.papers",
    "rss.daily.ai":          "research.papers",
    "rss.daily.economics":   "research.papers",
    "rss.paper.arxiv":       "research.papers",
    "rss.report":            "research.think-tanks",
    "rss.zen":               "culture.digital-life",   # per-source override below for Bubbles Town / TIFO
}

# per-source overrides where the group-level topic above is wrong for one
# specific source in that group (name match, case-sensitive, exact)
SOURCE_TOPIC_OVERRIDE = {
    "TLDR Tech":            "extra.tldr",
    "TLDR Dev":             "extra.tldr",
    "Ruanyf Weekly":        "extra.longform",
    "HelloGitHub":          "extra.opensource",
    "Bubbles Town":         "culture.curiosity",
    "Today I Found Out":    "culture.curiosity",
}

# yt.yaml group key -> topic (same idea, mechanical for the rest)
YT_TOPIC_MAP = {
    "yt.daily.tech":        "digest.tech",
    "yt.daily.gfw":         "digest.tech",
    "yt.daily.ios":         "digest.tech",
    "yt.digest.finance":    "digest.economics",
    "yt.digest.history":    "essay.general",
    "yt.digest.sport":      "culture.curiosity",
    "yt.dive.ai":           "research.papers",
    "yt.dive.study":        "essay.general",
    "yt.dive.politics":     "essay.general",
    "yt.dive.economics":    "essay.general",
    "yt.zen":               "culture.digital-life",
    "yt.zen.psychology":    "culture.digital-life",
    "yt.zen.pets":          "culture.curiosity",
    "yt.zen.lovers":        "culture.curiosity",
    "yt.zen.music":         "culture.music",
    "yt.zen.asmr":          "culture.curiosity",
}

# old feed `issue` value -> new issue name (unchanged in Phase 1 — issue
# names/schedules are NOT being redesigned yet, only the routing mechanism)
ISSUE_PASSTHROUGH = {
    "daily": "daily",
    "dive_weekly": "dive_weekly",
    "zen_weekly": "zen_weekly",
    "paper_weekly": "paper_weekly",
    "report_monthly": "report_monthly",
    "yt_weekly": "yt_weekly",
}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return s


def load(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main() -> None:
    rss_data = load(FEEDS / "rss.yaml")
    hn_data  = load(FEEDS / "hn.yaml")
    yt_data  = load(FEEDS / "yt.yaml")

    rss_sources: list[dict] = []
    topics: dict[str, str] = {}
    # issue -> set of (topic, collector) pairs. collector is part of the key
    # deliberately: topic alone can't distinguish "digest.tech from an RSS
    # feed" from "digest.tech from a YouTube channel" — two different
    # collectors can legitimately share a topic while needing to land in
    # different issues (Daily never wants video, YT Weekly never wants
    # articles). Discovered this by inspecting the first draft's output
    # before wiring up the adapter — better to fix the model now than have
    # it silently cross-contaminate issues once Phase 3 does real
    # topic-based matching.
    issue_topic_includes: dict[str, set[tuple[str, str]]] = {}
    issue_source_includes: dict[str, set[str]] = {}
    seen_ids: set[str] = set()
    legacy_keys: dict[str, str] = {}   # source_id -> original feed `key`
    legacy_group_meta: dict[str, dict] = {}  # legacy key -> {db, issue} (ground truth, not re-derived)

    def uniq_id(base: str) -> str:
        sid = base
        n = 2
        while sid in seen_ids:
            sid = f"{base}-{n}"
            n += 1
        seen_ids.add(sid)
        return sid

    # ── RSS ──────────────────────────────────────────────────────────────
    for group in rss_data["feeds"]:
        key = group["key"]
        db = group.get("db", "core")
        issue = ISSUE_PASSTHROUGH[group["issue"]]
        group_mode = group.get("display_mode")
        group_topic = TOPIC_MAP.get(key)
        if group_topic is None:
            raise SystemExit(f"No topic mapping for feed key {key!r} — add it to TOPIC_MAP")
        legacy_group_meta[key] = {"db": db, "issue": issue}

        for src in group.get("sources", []):
            sid = uniq_id(slugify(src["name"]))
            display_mode = src.get("display_mode") or group_mode  # no forced default — preserve None like the old shape
            topic = SOURCE_TOPIC_OVERRIDE.get(src["name"], group_topic)

            entry = {
                "id": sid,
                "collector": "rss",
                "name": src["name"],
                "url": src["url"],
            }
            if display_mode:
                entry["display_mode"] = display_mode
            if src.get("no_store"):
                entry["fetch"] = "live"
            if key == "rss.paper.arxiv":
                entry["pdf"] = "arxiv"
            elif key == "rss.report":
                entry["pdf"] = "scrape"
            rss_sources.append(entry)
            topics[sid] = topic
            legacy_keys[sid] = key

            # routing: TLDR/Ruanyf/HelloGitHub go to `extra` by explicit
            # source id (matches the source_name-based fix already made in
            # render_extra.py); everything else routes by topic.
            if src["name"] in SOURCE_TOPIC_OVERRIDE and topic.startswith("extra."):
                issue_source_includes.setdefault("extra", set()).add(sid)
            else:
                issue_topic_includes.setdefault(issue, set()).add((topic, "rss"))

    # ── HN ───────────────────────────────────────────────────────────────
    hn_source = {
        "id": "hackernews",
        "collector": "hn",
        "min_score": hn_data["hn"]["filter"]["min_score"],
        "max_age_hours": hn_data["hn"]["filter"]["max_age_hours"],
        "top_n": hn_data["hn"]["fetch"]["top_n"],
        "workers": hn_data["hn"]["fetch"]["workers"],
    }
    topics["hackernews"] = "news.tech"
    legacy_keys["hackernews"] = "hn"
    legacy_group_meta["hn"] = {"db": hn_data["hn"]["db"], "issue": ISSUE_PASSTHROUGH[hn_data["hn"]["issue"]]}
    issue_topic_includes.setdefault(ISSUE_PASSTHROUGH[hn_data["hn"]["issue"]], set()).add(("news.tech", "hn"))

    # ── YouTube ──────────────────────────────────────────────────────────
    yt_sources: list[dict] = []
    for group in yt_data["feeds"]:
        key = group["key"]
        issue = ISSUE_PASSTHROUGH[group["issue"]]
        topic = YT_TOPIC_MAP.get(key)
        if topic is None:
            raise SystemExit(f"No topic mapping for yt key {key!r} — add it to YT_TOPIC_MAP")
        legacy_group_meta[key] = {"db": "youtube", "issue": issue}

        for src in group.get("sources", []):
            # channel_id is already a stable, unique identifier — no need
            # to hand-slug 60+ mostly-Chinese channel names
            sid = src["channel_id"]
            yt_sources.append({
                "id": sid,
                "collector": "youtube",
                "name": src["name"],
                "channel_id": src["channel_id"],
                "mode": src.get("mode", ["mixed"]),
            })
            topics[sid] = topic
            legacy_keys[sid] = key
            issue_topic_includes.setdefault(issue, set()).add((topic, "youtube"))

    # ── Write config/sources/*.yml ──────────────────────────────────────
    CONFIG.mkdir(exist_ok=True)
    (CONFIG / "sources").mkdir(exist_ok=True)

    with open(CONFIG / "sources" / "rss.yml", "w") as f:
        yaml.dump({"sources": rss_sources}, f, sort_keys=False, allow_unicode=True, width=100)

    with open(CONFIG / "sources" / "hn.yml", "w") as f:
        yaml.dump({"sources": [hn_source]}, f, sort_keys=False, allow_unicode=True, width=100)

    with open(CONFIG / "sources" / "youtube.yml", "w") as f:
        yaml.dump({"sources": yt_sources}, f, sort_keys=False, allow_unicode=True, width=100)

    # ── Write config/topics.yml ──────────────────────────────────────────
    with open(CONFIG / "topics.yml", "w") as f:
        yaml.dump(
            {"sources": {sid: {"topic": t} for sid, t in sorted(topics.items())}},
            f, sort_keys=False, allow_unicode=True, width=100,
        )

    # ── Write config/issues.yml ──────────────────────────────────────────
    issues_out = {}
    all_issue_names = set(issue_topic_includes) | set(issue_source_includes)
    for name in sorted(all_issue_names):
        include = []
        pairs = issue_topic_includes.get(name, set())
        collectors_used = {c for _, c in pairs}

        if name == "yt_weekly" and collectors_used == {"youtube"}:
            # Every current YouTube source maps to yt_weekly regardless of
            # topic — there's no real topic-based split today, so a single
            # collector catch-all is both simpler and more accurate than
            # listing every topic pair individually.
            include.append({"collector": "youtube"})
        else:
            for topic, collector in sorted(pairs):
                include.append({"topic": topic, "collector": collector})

        for sid in sorted(issue_source_includes.get(name, [])):
            include.append({"source": sid})
        issues_out[name] = {"include": include}

    with open(CONFIG / "issues.yml", "w") as f:
        yaml.dump({"issues": issues_out}, f, sort_keys=False, allow_unicode=True, width=100)

    with open(CONFIG / "_phase1_legacy_keys.yml", "w") as f:
        f.write("# Phase-1-only scaffolding — see migrate_config.py docstring.\n")
        f.write("# Delete this file (and config.py's adapter that reads it) in Phase 3.\n")
        yaml.dump({"legacy_keys": legacy_keys}, f, sort_keys=True, allow_unicode=True, width=100)

    with open(CONFIG / "_phase1_legacy_group_meta.yml", "w") as f:
        f.write("# Phase-1-only scaffolding — see migrate_config.py docstring.\n")
        f.write("# Delete this file (and config.py's adapter that reads it) in Phase 3.\n")
        yaml.dump({"legacy_group_meta": legacy_group_meta}, f, sort_keys=True, allow_unicode=True, width=100)

    print(f"Wrote {len(rss_sources)} RSS sources, 1 HN source, {len(yt_sources)} YouTube sources")
    print(f"Wrote {len(topics)} topic entries")
    print(f"Wrote {len(issues_out)} issues: {sorted(issues_out)}")


if __name__ == "__main__":
    main()
