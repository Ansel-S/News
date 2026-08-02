"""render_paper.py — Paper weekly (every Friday) — title list only"""
from __future__ import annotations
from render_base import render_simple_digest, block_title_only

ISSUE_TYPE = "paper_weekly"

LABELS: dict[str, str] = {
    "rss.daily.ai":           "AI Research",
    "rss.daily.economics":    "Economics",
    "rss.research.cs":        "Computer Science",
    "rss.research.science":   "Science",
    "rss.research.economics": "Finance & Economics",
}


def _dispatch(row, is_first: bool) -> str:
    return block_title_only(row["title"] or "", row["source_name"], row["source_id"])


def _label(feed_key: str, rows) -> str:
    return LABELS.get(feed_key, feed_key)


def _summary(rows, extra) -> str:
    return f"{len(rows)} papers &mdash; click titles to read"


def main() -> None:
    render_simple_digest(
        db="paper", issue_type=ISSUE_TYPE,
        title_prefix="Papers", issue_label="Paper Weekly",
        subject_prefix="Dewsletter Papers", out_name="out_paper",
        block_dispatch=_dispatch, group_by="feed_key",
        group_label_fn=_label, wrap_ul=True, summary_fn=_summary,
    )


if __name__ == "__main__":
    main()
