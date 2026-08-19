"""
render_research.py — Research Weekly (every Friday), replaces the old
Paper Weekly + Report Monthly (merged per /DESIGN.md §4.4, resolved as
part of Phase 6 — this was the explicitly flagged open product decision).

Pulls from two databases in one issue: content.db's arXiv/paper-topic
entries and report.db's thinktank reports — the first real exercise of
issues/builder.py's multi-db support (see its module docstring). PDFs
from both are bundled into a single research.zip; entries with no PDF
(fetch failed or none found) are omitted from the zip but still listed in
the email — same policy the two predecessor renderers had individually.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_SCRIPTS_DIR = _Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_SCRIPTS_DIR))
from pathlib import Path
from render.render_base import render_simple_digest, block_title_only, export_pdf_zip

ISSUE_TYPE = "research_weekly"
ROOT       = Path(__file__).resolve().parent.parent.parent  # scripts/<subpkg>/this_file.py -> repo root
OUT_ZIP    = ROOT / "research.zip"

LABELS: dict[str, str] = {
    "rss.daily.ai":         "AI Research",
    "rss.daily.economics":  "Economics",
    "rss.research.cs":      "Computer Science",
    "rss.research.science": "Science",
    "rss.research.economics": "Finance & Economics",
    "rss.paper.arxiv":      "arXiv",
    "rss.report":           "Think Tanks",
}


def _dispatch(row, is_first: bool) -> str:
    return block_title_only(row["title"] or "", row["source_name"], row["source_id"])


def _label(feed_key: str, rows) -> str:
    return LABELS.get(feed_key, feed_key)


def _write_pdfs(rows) -> dict:
    """pre_hook: bundle any downloaded PDF blobs (from either content.db's
    papers or report.db's reports — export_pdf_zip doesn't care which db a
    row came from, it just reads row["pdf_data"] generically) into
    research.zip. Deletes the zip again if it ended up empty, so the
    workflow's `if -f research.zip` check correctly skips attaching a
    pointless empty archive."""
    pdf_count, skipped = export_pdf_zip(rows, OUT_ZIP)
    if pdf_count == 0 and OUT_ZIP.exists():
        OUT_ZIP.unlink()
    return {"pdf_count": pdf_count, "pdf_skipped": skipped}


def _summary(rows, extra) -> str:
    pdf_count = extra.get("pdf_count", 0)
    skipped   = extra.get("pdf_skipped", 0)
    suffix = f" &middot; {pdf_count} PDFs attached" if pdf_count else ""
    if skipped:
        suffix += f" ({skipped} omitted to keep the email under size limits)"
    return f"{len(rows)} papers & reports &mdash; click titles to read{suffix}"


def main() -> None:
    render_simple_digest(
        db="content", issue_type=ISSUE_TYPE,   # `db` kwarg unused when use_builder=True
        title_prefix="Research", issue_label="Research Weekly",
        subject_prefix="Dewsletter Research", out_name="out_research",
        block_dispatch=_dispatch, group_by="feed_key",
        group_label_fn=_label, wrap_ul=True,
        pre_hook=_write_pdfs, summary_fn=_summary,
        use_builder=True,
    )


if __name__ == "__main__":
    main()
