"""
render_zen.py — Zen weekly (every Sunday)
Grouped by source_name; each row dispatches to block_full (email_mode=full)
or block_title_excerpt (everything else).

Uses issues.builder instead of a hand-written get_unpushed(db, issue_type)
call — see render_dive.py's docstring / issues/builder.py's module
docstring for why this is safe for zen_weekly specifically.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_SCRIPTS_DIR = _Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_SCRIPTS_DIR))
from render.render_base import render_simple_digest, block_full, block_title_excerpt

ISSUE_TYPE = "zen_weekly"


def _dispatch(row, is_first: bool) -> str:
    kw = dict(title=row["title"] or "", source_name=row["source_name"],
              url=row["source_id"], content=row["content"] or "", sep=not is_first)
    if row["email_mode"] == "full":
        return block_full(**kw, read_minutes=row["read_minutes"] or 0)
    return block_title_excerpt(**kw)


def main() -> None:
    render_simple_digest(
        db="content", issue_type=ISSUE_TYPE,
        title_prefix="Zen", issue_label="Zen Weekly",
        subject_prefix="Dewsletter Zen", out_name="out_zen",
        block_dispatch=_dispatch, show_group_count=False,
        use_builder=True,
    )


if __name__ == "__main__":
    main()
