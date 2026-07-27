"""
upload_daily_release.py — Upload arbitrary files (daily's full-article zip,
papers zip, report PDFs, etc.) as assets on TODAY's GitHub Release.

Shares the same day-keyed release as upload_yt_release.py: tag = yyyy-mm-dd,
create-if-not-exists. Whichever workflow runs first today creates the
release; later workflows just add more assets to it.

Usage:
  python scripts/upload_daily_release.py --repo owner/name --tag 2026-07-27 \
      out_daily.zip out_papers.zip
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

MAX_ASSET_BYTES = 2 * 1024**3  # 2 GiB, GitHub's hard per-file limit


def ensure_release(repo: str, tag: str) -> None:
    check = subprocess.run(
        ["gh", "release", "view", tag, "--repo", repo],
        capture_output=True, text=True,
    )
    if check.returncode != 0:
        subprocess.run(
            ["gh", "release", "create", tag, "--repo", repo,
             "--title", tag, "--notes", f"Dewsletter assets for {tag}"],
            check=True,
        )


def upload_file(repo: str, tag: str, path: Path) -> bool:
    size = path.stat().st_size
    if size >= MAX_ASSET_BYTES:
        print(f"  [skip] {path.name} is {size/1024**3:.2f} GiB, over the 2 GiB per-asset limit")
        return False
    result = subprocess.run(
        ["gh", "release", "upload", tag, str(path), "--repo", repo, "--clobber"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  [fail] {path.name}: {result.stderr.strip()}")
        return False
    print(f"  [ok] {path.name}")
    return True


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

    ensure_release(args.repo, args.tag)

    ok, failed = 0, 0
    for p in paths:
        if upload_file(args.repo, args.tag, p):
            ok += 1
        else:
            failed += 1

    print(f"upload_daily_release: {ok} uploaded, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()