"""
upload_daily_release.py — Upload arbitrary files (daily's full-article zip,
papers zip, report PDFs, etc.) as assets on TODAY's GitHub Release.

Shares the same day-keyed release as upload_yt_release.py — see
release_utils.py for the release-organization rationale.

Usage:
  python scripts/upload_daily_release.py --repo owner/name --tag 2026-07-27 \
      out_daily.zip out_papers.zip
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from release_utils import upload_files


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--tag", required=True, help="release tag, e.g. 2026-07-27")
    ap.add_argument("files", nargs="+", help="files to attach to today's release")
    args = ap.parse_args()

    paths = [Path(f) for f in args.files if Path(f).exists()]
    if not paths:
        print("upload_daily_release: no existing files given, nothing to upload")
        return

    ok, failed = upload_files(args.repo, args.tag, paths)
    print(f"upload_daily_release: {ok} uploaded, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
