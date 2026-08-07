"""
render_report.py — Report monthly (1st of each month)
Email: title list only. PDFs stored in report.db are bundled into a single
reports.zip (previously: attached as individual files by title, which is
exactly what caused a real send to exceed Gmail's message size limit with
19 reports attached at once — see the Report Monthly workflow's failure
log). Entries with no PDF (fetch failed or none found) are omitted from
the zip but still listed in the email.
"""
from __future__ import annotations
from pathlib import Path
from render_base import render_simple_digest, block_title_only, export_pdf_zip

ISSUE_TYPE = "report_monthly"
ROOT       = Path(__file__).resolve().parent.parent
OUT_ZIP    = ROOT / "reports.zip"


def _write_pdfs(rows) -> dict:
    """pre_hook: bundle any stored PDF blobs into reports.zip, return the
    count so summary_fn can report it. Deletes the zip again if it ended up
    empty, so the workflow's `if -f reports.zip` check correctly skips
    attaching a pointless empty archive."""
    pdf_count, skipped = export_pdf_zip(rows, OUT_ZIP)
    if pdf_count == 0 and OUT_ZIP.exists():
        OUT_ZIP.unlink()
    return {"pdf_count": pdf_count, "pdf_skipped": skipped}


def _dispatch(row, is_first: bool) -> str:
    return block_title_only(row["title"] or "", row["source_name"], row["source_id"])


def _summary(rows, extra) -> str:
    pdf_count = extra.get("pdf_count", 0)
    skipped   = extra.get("pdf_skipped", 0)
    suffix = f" &middot; {pdf_count} PDFs attached" if pdf_count else ""
    if skipped:
        suffix += f" ({skipped} omitted to keep the email under size limits)"
    return f"{len(rows)} reports this month{suffix}"


def main() -> None:
    render_simple_digest(
        db="report", issue_type=ISSUE_TYPE, table="report_items",
        title_prefix="Reports", issue_label="Report Monthly",
        subject_prefix="Dewsletter Reports", out_name="out_report",
        block_dispatch=_dispatch, wrap_ul=True,
        pre_hook=_write_pdfs, summary_fn=_summary,
    )


if __name__ == "__main__":
    main()
