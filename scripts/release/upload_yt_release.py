"""
upload_yt_release.py — Upload low-res video/audio files (from ingest_youtube.py's
`video`/`audio` mode downloads) as GitHub Release assets, then record the
resulting download URL back into youtube.db.

See release_utils.py for the release-organization rationale (day-keyed tags,
create-if-not-exists) and GitHub's asset size limits.

Usage:
  python scripts/upload_yt_release.py --repo owner/name --tag 2026-07-27
"""
from __future__ import annotations


import sys as _sys
from pathlib import Path as _Path
_SCRIPTS_DIR = _Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_SCRIPTS_DIR))
import argparse
import sys
from pathlib import Path

from db.db_utils import set_yt_media_url
from release.release_utils import ensure_release, upload_file

ROOT = Path(__file__).resolve().parent.parent.parent  # scripts/<subpkg>/this_file.py -> repo root
MEDIA_DIR = ROOT / "media_out"


def video_id_and_kind_from_filename(path: Path) -> tuple[str, str]:
    """Files are named '<video_id>.<kind>.<ext>', e.g. 'abc123.video.webm' or
    'abc123.audio.m4a'. Falls back to kind='video' for older-style filenames
    that don't have the kind segment."""
    stem = path.stem  # strips only the last extension, e.g. "abc123.video"
    parts = stem.rsplit(".", 1)
    if len(parts) == 2 and parts[1] in ("video", "audio"):
        return parts[0], parts[1]
    return stem, "video"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--tag", required=True, help="release tag, e.g. 2026-07-27")
    args = ap.parse_args()

    if not MEDIA_DIR.exists():
        print("upload_yt_release: no media_out/ directory, nothing to upload")
        return

    files = sorted(p for p in MEDIA_DIR.glob("*.*") if p.suffix != ".tsv")
    if not files:
        print("upload_yt_release: media_out/ is empty, nothing to upload")
        return

    ok, failed = 0, 0
    ensure_release(args.repo, args.tag, notes="Dewsletter YouTube weekly media")
    for f in files:
        url = upload_file(args.repo, args.tag, f)
        if not url:
            failed += 1
            continue
        ok += 1
        vid, kind = video_id_and_kind_from_filename(f)
        set_yt_media_url(vid, kind, url)
        print(f"  [ok] {f.name} ({kind}) -> {url}")

    print(f"upload_yt_release: {ok} uploaded, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
