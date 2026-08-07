"""
render_paper.py — Paper weekly (every Friday) — title list only

arXiv PDFs downloaded during ingest (see ingest_rss.py::process_paper_entry)
are bundled into papers.zip; entries whose PDF download failed (or that
aren't from arXiv and never had a PDF to begin with — ACM Queue, Quanta,
etc, which have title+abstract only) are simply omitted from the zip.
"""
from __future__ import annotations
from pathlib import Path
from render_base import render_simple_digest, block_title_only, export_pdf_zip

ISSUE_TYPE = "paper_weekly"
ROOT       = Path(__file__).resolve().parent.parent
OUT_ZIP    = ROOT / "papers.zip"

LABELS: dict[str, str] = {
    "rss.daily.ai":           "AI Research",
    "rss.daily.economics":    "Economics",
    "rss.research.cs":        "Computer Science",
    "rss.research.science":   "Science",
    "rss.research.economics": "Finance & Economics",
    "rss.paper.arxiv":        "arXiv",
}


def _dispatch(row, is_first: bool) -> str:
    return block_title_only(row["title"] or "", row["source_name"], row["source_id"])


def _label(feed_key: str, rows) -> str:
    return LABELS.get(feed_key, feed_key)


def _write_pdfs(rows) -> dict:
    """pre_hook: bundle any downloaded PDF blobs into papers.zip, return the
    count so summary_fn can report it. Deletes the zip again if it ended up
    empty, so the workflow's `if -f papers.zip` check correctly skips
    attaching a pointless empty archive."""
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
    return f"{len(rows)} papers &mdash; click titles to read{suffix}"


def main() -> None:
    render_simple_digest(
        db="paper", issue_type=ISSUE_TYPE,
        title_prefix="Papers", issue_label="Paper Weekly",
        subject_prefix="Dewsletter Papers", out_name="out_paper",
        block_dispatch=_dispatch, group_by="feed_key",
        group_label_fn=_label, wrap_ul=True,
        pre_hook=_write_pdfs, summary_fn=_summary,
    )


if __name__ == "__main__":
    main()
