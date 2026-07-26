"""
upload_yt_release.py — Upload low-res video/audio files (from ingest_youtube.py's
`video`/`audio` mode downloads) as GitHub Release assets, then record the
resulting download URL back into youtube.db.

GitHub Release limits (docs.github.com/en/repositories/releasing-projects-on-github/about-releases):
  - each asset must be < 2 GiB
  - up to 1000 assets per release
  - no limit on total release size
A 720p vp09/av01 video is typically well under 2 GiB, so no chunking is needed.

Requires the `gh` CLI to be authenticated (GH_TOKEN / GITHUB_TOKEN env var,
already available by default in GitHub Actions).

Usage:
  python scripts/upload_yt_release.py --repo owner/name --tag yt-2026-07-22
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from db_utils import set_yt_media_url

ROOT = Path(__file__).resolve().parent.parent
MEDIA_DIR = ROOT / "media_out"

MAX_ASSET_BYTES = 2 * 1024**3  # 2 GiB, GitHub's hard per-file limit


def ensure_release(repo: str, tag: str) -> None:
    """Create the release if it doesn't exist yet (idempotent)."""
    check = subprocess.run(
        ["gh", "release", "view", tag, "--repo", repo],
        capture_output=True, text=True,
    )
    if check.returncode != 0:
        subprocess.run(
            ["gh", "release", "create", tag, "--repo", repo,
             "--title", tag, "--notes", "Dewsletter YouTube weekly media"],
            check=True,
        )


def upload_file(repo: str, tag: str, path: Path) -> str | None:
    size = path.stat().st_size
    if size >= MAX_ASSET_BYTES:
        print(f"  [skip] {path.name} is {size/1024**3:.2f} GiB, over the 2 GiB "
              f"per-asset limit — re-encode at a lower bitrate/resolution first")
        return None

    result = subprocess.run(
        ["gh", "release", "upload", tag, str(path), "--repo", repo, "--clobber"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  [fail] {path.name}: {result.stderr.strip()}")
        return None

    return f"https://github.com/{repo}/releases/download/{tag}/{path.name}"


def video_id_from_filename(path: Path) -> str:
    return path.stem  # files are named "<video_id>.<ext>"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--tag", required=True, help="release tag, e.g. yt-2026-07-22")
    ap.add_argument("--video-url-map", default=str(MEDIA_DIR / "_video_id_to_url.tsv"),
                     help=(
        "Path to a text file of '<video_id>\\t<video_url>' lines for mapping "
        "filenames back to video_url (default: media_out/_video_id_to_url.tsv, "
        "written automatically by ingest_youtube.py)."
    ))
    args = ap.parse_args()

    if not MEDIA_DIR.exists():
        print("upload_yt_release: no media_out/ directory, nothing to upload")
        return

    files = sorted(p for p in MEDIA_DIR.glob("*.*") if p.suffix != ".tsv")
    if not files:
        print("upload_yt_release: media_out/ is empty, nothing to upload")
        return

    id_to_url: dict[str, str] = {}
    if args.video_url_map:
        map_path = Path(args.video_url_map)
        if map_path.exists():
            for line in map_path.read_text(encoding="utf-8").splitlines():
                if "\t" in line:
                    vid, url = line.split("\t", 1)
                    id_to_url[vid.strip()] = url.strip()

    ensure_release(args.repo, args.tag)

    uploaded, failed = 0, 0
    for f in files:
        url = upload_file(args.repo, args.tag, f)
        if not url:
            failed += 1
            continue
        uploaded += 1
        vid = video_id_from_filename(f)
        video_url = id_to_url.get(vid)
        if video_url:
            set_yt_media_url(video_url, url)
        print(f"  [ok] {f.name} -> {url}")

    print(f"upload_yt_release: {uploaded} uploaded, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
