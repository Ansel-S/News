"""
release_utils.py — Shared GitHub Release helpers.

Releases are organized by day: tag = today's date (yyyy-mm-dd), e.g. "2026-07-27".
Every workflow that produces assets for today (yt_weekly, daily, etc.) uploads
to the SAME day's release — whichever runs first creates it, later runs just
add more assets (create-if-not-exists, no waiting for a nightly batch job).

GitHub Release limits (docs.github.com/en/repositories/releasing-projects-on-github/about-releases):
  - each asset must be < 2 GiB
  - up to 1000 assets per release
  - no limit on total release size
A 720p vp09/av01 video is typically well under 2 GiB, so no chunking is needed.

Requires the `gh` CLI to be authenticated (GH_TOKEN / GITHUB_TOKEN env var,
already available by default in GitHub Actions).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

MAX_ASSET_BYTES = 2 * 1024**3  # 2 GiB, GitHub's hard per-file limit


def ensure_release(repo: str, tag: str, *, notes: str | None = None) -> None:
    """Create the release if it doesn't exist yet (idempotent)."""
    check = subprocess.run(
        ["gh", "release", "view", tag, "--repo", repo],
        capture_output=True, text=True,
    )
    if check.returncode != 0:
        subprocess.run(
            ["gh", "release", "create", tag, "--repo", repo,
             "--title", tag, "--notes", notes or f"Dewsletter assets for {tag}"],
            check=True,
        )


def upload_file(repo: str, tag: str, path: Path) -> str | None:
    """Upload one file as a release asset. Returns the download URL, or None
    on failure (oversize or upload error — details printed either way)."""
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


def upload_files(repo: str, tag: str, paths: list[Path], *, notes: str | None = None) -> tuple[int, int]:
    """Ensure the release exists, then upload every path. Returns (ok_count, fail_count)."""
    ensure_release(repo, tag, notes=notes)
    ok, failed = 0, 0
    for p in paths:
        if upload_file(repo, tag, p):
            ok += 1
        else:
            failed += 1
    return ok, failed
