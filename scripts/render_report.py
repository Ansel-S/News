"""
render_report.py — Report monthly (1st of each month)
Email: title list only. PDFs stored in report.db are written to
out_report_pdfs/ + a manifest, for the workflow to attach.
"""
from __future__ import annotations
import json
from pathlib import Path
from render_base import render_simple_digest, block_title_only

ISSUE_TYPE  = "report_monthly"
ROOT        = Path(__file__).resolve().parent.parent
OUT_PDF_DIR = ROOT / "out_report_pdfs"
OUT_PDF_MANIFEST = ROOT / "out_report_pdf_manifest.json"


def _write_pdfs(rows) -> dict:
    """pre_hook: write any stored PDF blobs to disk + a manifest, return the
    file list so summary_fn can report a PDF count."""
    OUT_PDF_DIR.mkdir(exist_ok=True)
    pdf_files: list[str] = []
    for row in rows:
        if row["pdf_data"]:
            safe_title = "".join(c if c.isalnum() or c in "-_ " else "_"
                                 for c in (row["title"] or row["id"]))
            fname = f"{safe_title[:60]}.pdf"
            path  = OUT_PDF_DIR / fname
            path.write_bytes(row["pdf_data"])
            pdf_files.append(str(path))
    OUT_PDF_MANIFEST.write_text(json.dumps(pdf_files, indent=2))
    return {"pdf_files": pdf_files}


def _dispatch(row, is_first: bool) -> str:
    return block_title_only(row["title"] or "", row["source_name"], row["source_id"])


def _summary(rows, extra) -> str:
    pdf_files = extra.get("pdf_files", [])
    suffix = f" &middot; {len(pdf_files)} PDFs attached" if pdf_files else ""
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
