"""
render_zen.py — Zen weekly (every Sunday)
Grouped by source_name; each row dispatches to block_full (display_mode=full)
or block_title_excerpt (everything else).
"""
from __future__ import annotations
from render_base import render_simple_digest, block_full, block_title_excerpt

ISSUE_TYPE = "zen_weekly"


def _dispatch(row, is_first: bool) -> str:
    kw = dict(title=row["title"] or "", source_name=row["source_name"],
              url=row["source_id"], content=row["content"] or "", sep=not is_first)
    if row["display_mode"] == "full":
        return block_full(**kw, read_minutes=row["read_minutes"] or 0)
    return block_title_excerpt(**kw)


def main() -> None:
    render_simple_digest(
        db="zen", issue_type=ISSUE_TYPE,
        title_prefix="Zen", issue_label="Zen Weekly",
        subject_prefix="Dewsletter Zen", out_name="out_zen",
        block_dispatch=_dispatch, show_group_count=False,
    )


if __name__ == "__main__":
    main()
