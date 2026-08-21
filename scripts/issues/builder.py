"""
issues/builder.py — resolves which sources belong to an issue, then
queries whichever db(s)/table(s) those sources' rows actually live in.

Each source (config/sources/{rss,hn,youtube}.yml) carries its own
`issues` list, `db`, and `table` directly — no more joining across
topics.yml/storage.yml by source_key string (see config/README.md).

TWO WAYS A (db, table) TARGET GETS RESOLVED:
1. Exclusively owned by this issue (nothing else routes there) — the
   simple case, just get_unpushed(db, issue_name, table=table) as-is.
2. Shared with other issues (content.db's items table — Daily/Extra/
   Dive/Zen/Research-issue rows all coexist there) — filtered by
   get_unpushed(..., source_keys=matched_sids). Every content-bearing
   table (items/report_items/hn_items/yt_items/yt_media_items) has a
   source_key column, so this always works for RSS/HN sources.

yt_weekly is the one remaining case build() can't resolve: which table a
video lands in (yt_items vs yt_media_items) is decided per-video by
ingest based on subtitle presence, not by the channel/source config, so
there's no static (db, table) to look up per source. render_yt.py queries
yt_items/yt_media_items directly instead of going through build().
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
import sqlite3
import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


class IssueNotFullyScoped(Exception):
    """Raised when an issue's sources don't exclusively occupy their
    db/table AND that table has no source_key column to filter by instead
    — see module docstring. Not a bug to catch and ignore; it means this
    issue needs a source_key column added to its table, or needs to be
    listed as an exception."""


def _load(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _all_sources() -> dict[str, dict]:
    """source_key -> full source record, across all three source files."""
    out: dict[str, dict] = {}
    for fname in ("rss.yml", "hn.yml", "youtube.yml"):
        data = _load(CONFIG_DIR / "sources" / fname)
        for src in data.get("sources", []):
            out[src["id"]] = src
    return out


def _valid_issue_names() -> list[str]:
    return _load(CONFIG_DIR / "issue_defs.yml").get("issues", [])


def topic_order(issue_name: str) -> dict[str, int]:
    """source_key -> order, from each source's own `order` field for this
    issue (currently only `daily` sets these). Sources with no `order`
    are simply absent — callers should default to some fallback (e.g. 99)
    same as before."""
    if issue_name not in _valid_issue_names():
        raise KeyError(f"No such issue: {issue_name!r}")
    result = {}
    for sid, src in _all_sources().items():
        order = src.get("order", {}).get(issue_name)
        if order is not None:
            result[sid] = order
    return result


def matched_source_keys(issue_name: str) -> set[str]:
    """The set of source_keys whose `issues` list includes issue_name.
    Exposed separately from build() so callers (and tests) can inspect
    resolution without needing a live database."""
    if issue_name not in _valid_issue_names():
        raise KeyError(f"No such issue: {issue_name!r}")
    return {sid for sid, src in _all_sources().items()
            if issue_name in src.get("issues", [])}


def build(issue_name: str, *, table_override: dict[str, str] | None = None) -> list[tuple[str, object]]:
    """Return every unpushed row belonging to `issue_name`, across
    whichever db(s)/table(s) its sources live in, as (db_name, row) pairs
    — not bare rows. This matters as soon as an issue spans more than one
    db (research_weekly: content.db's papers + report.db's reports) —
    mark_pushed() needs to know which db each row actually came from.

    Raises IssueNotFullyScoped if this issue's sources don't exclusively
    occupy their db/table AND that table has no source_key column to
    filter by instead (currently only possible for YouTube, which isn't
    routed through build() at all — see module docstring).

    table_override lets a caller override the table name resolved from
    config on a per-db basis (not currently exercised, kept for forward
    compatibility)."""
    from db.db_utils import get_unpushed  # deferred import: keeps this module
                                        # importable without scripts/ on sys.path during tests

    sources = _all_sources()
    matched = matched_source_keys(issue_name)

    unrouted = {sid for sid in matched if sid not in sources or "db" not in sources[sid]}
    if unrouted:
        raise IssueNotFullyScoped(
            f"Issue {issue_name!r} matches {len(unrouted)} source(s) with no "
            f"db/table assigned (e.g. {sorted(unrouted)[:3]}) — most likely "
            f"YouTube sources, which are routed by ingest per-video, not by "
            f"source config. Silently skipping these would make build() return "
            f"an incomplete or empty result instead of failing loudly."
        )

    # group matched sources by (db, table)
    targets: dict[tuple[str, str], set[str]] = {}
    for sid in matched:
        meta = sources[sid]
        key = (meta["db"], table_override.get(meta["db"], meta["table"]) if table_override else meta["table"])
        targets.setdefault(key, set()).add(sid)

    # does this issue's matched set exclusively own each target (db,
    # table), or does something else also route there?
    all_sources_by_target: dict[tuple[str, str], set[str]] = {}
    for sid, meta in sources.items():
        if "db" not in meta:
            continue
        key = (meta["db"], meta["table"])
        all_sources_by_target.setdefault(key, set()).add(sid)

    rows: list[tuple[str, object]] = []
    for (db, table), sids in targets.items():
        full_set = all_sources_by_target.get((db, table), set())
        if sids == full_set:
            # exclusive ownership — simple unfiltered query
            rows.extend((db, row) for row in get_unpushed(db, issue_name, table=table))
            continue

        # shared table — filter by source_key
        try:
            filtered = get_unpushed(db, issue_name, table=table, source_keys=sids)
        except sqlite3.OperationalError as ex:
            extra = full_set - sids
            raise IssueNotFullyScoped(
                f"Issue {issue_name!r} only claims {len(sids)}/{len(full_set)} "
                f"sources routed to {db}.{table} — {len(extra)} other source(s) "
                f"also land there (e.g. {sorted(extra)[:3]}), and {table} has no "
                f"source_key column to filter by instead ({ex})."
            ) from ex
        rows.extend((db, row) for row in filtered)

    return rows
