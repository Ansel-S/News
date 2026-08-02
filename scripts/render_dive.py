"""
render_dive.py — Dive weekly (long-form deep dives)
All rows are display_mode='full' — every article gets full text inline,
grouped by source_name.
"""
from __future__ import annotations
from render_base import render_simple_digest, block_full

ISSUE_TYPE = "dive_weekly"


def _dispatch(row, is_first: bool) -> str:
    return block_full(
        title=row["title"] or "", source_name=row["source_name"],
        url=row["source_id"], content=row["content"] or "",
        read_minutes=row["read_minutes"] or 0, sep=not is_first,
    )


def _summary(rows, extra) -> str:
    total_min = sum(r["read_minutes"] or 0 for r in rows)
    return f"{len(rows)} long reads &middot; ~{total_min} min"


def main() -> None:
    render_simple_digest(
        db="dive", issue_type=ISSUE_TYPE,
        title_prefix="Dive", issue_label="Dive Weekly",
        subject_prefix="Dewsletter Dive", out_name="out_dive",
        block_dispatch=_dispatch, show_group_count=False, summary_fn=_summary,
    )


if __name__ == "__main__":
    main()
