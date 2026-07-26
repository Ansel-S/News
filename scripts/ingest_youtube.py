"""
ingest_youtube.py — YouTube subtitle ingest
Reads feeds/yt.yaml, fetches video lists via YouTube RSS feed,
downloads subtitles with yt-dlp, stores in youtube.db.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, UTC
from pathlib import Path

import feedparser
import requests

from config import yt_feeds
from db_utils import run_id, yt_exists, insert_yt, insert_error as _err, now_iso

MAX_WORKERS   = int(os.getenv("YT_WORKERS", "3"))
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "8"))
RETRY_SOURCE  = os.getenv("RETRY_ONLY_SOURCE")

# Where low-res video/audio downloads land before being uploaded as GitHub
# Release assets by the workflow. Each file must stay under GitHub's 2 GiB
# per-asset limit (no total-size limit on a release) — see docs.github.com
# /en/repositories/releasing-projects-on-github/about-releases
MEDIA_OUT_DIR = Path(os.getenv("YT_MEDIA_DIR", "media_out"))
MEDIA_MAP_FILE = MEDIA_OUT_DIR / "_video_id_to_url.tsv"

# Target: smallest reasonable quality, still watchable/listenable.
# vp09/av01 @ 720p (or below, whichever is available) video-only when we don't
# need subtitles at all; audio-only (m4a/opus) when the video track is useless.
VIDEO_FORMAT = "bestvideo[height<=720][vcodec^=vp09]/bestvideo[height<=720][vcodec^=av01]/bestvideo[height<=720]+bestaudio/best[height<=720]"
AUDIO_FORMAT = "bestaudio[abr<=96]/bestaudio"

VALID_MODES = {"subtitle", "video", "mixed", "audio"}


def yt_feed_url(channel_id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def is_recent(entry) -> bool:
    pub = entry.get("published_parsed")
    if pub is None:
        return True
    try:
        return datetime(*pub[:6], tzinfo=UTC) >= datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)
    except Exception:
        return True


def pick_vtt(tmp_dir: Path) -> Path | None:
    vtt_files = list(tmp_dir.glob("*.vtt"))
    if not vtt_files:
        return None
    non_en = [
        f for f in vtt_files
        if not re.search(r"\.(en|en-orig|en-US|en-GB)[.-]", f.name)
        and not f.name.endswith(".en.vtt")
    ]
    return non_en[0] if non_en else vtt_files[0]


def download_subtitle(video_url: str) -> str | None:
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [
            "yt-dlp", "--skip-download",
            "--write-sub", "--write-auto-sub",
            "--sub-langs", "all,-live_chat",
            "--sub-format", "vtt",
            "--output", f"{tmp}/%(id)s",
            video_url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return None
        chosen = pick_vtt(Path(tmp))
        return chosen.read_text("utf-8", errors="ignore") if chosen else None


def clean_vtt(vtt: str) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for block in re.split(r"\n\s*\n", vtt.strip()):
        for raw in block.splitlines():
            raw = raw.strip()
            if (not raw or "-->" in raw or raw.startswith(("WEBVTT", "NOTE", "Kind:", "Language:"))
                    or re.fullmatch(r"\d+", raw)):
                continue
            text = re.sub(r"<[^>]+>", "", raw).strip()
            if text and text not in seen:
                seen.add(text)
                lines.append(text)
    return " ".join(lines)


def download_media(video_url: str, video_id: str, *, audio_only: bool) -> Path | None:
    """Download a low-res video (vp09/av01, <=720p) or audio-only track for
    channels where subtitles aren't useful. Returns the output file path, or
    None on failure. Caller is responsible for uploading it as a GitHub
    Release asset and deleting the local copy afterwards."""
    MEDIA_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(MEDIA_OUT_DIR / f"{video_id}.%(ext)s")
    fmt = AUDIO_FORMAT if audio_only else VIDEO_FORMAT
    cmd = [
        "yt-dlp", "-f", fmt,
        "--no-playlist",
        "--output", out_tmpl,
        video_url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    matches = list(MEDIA_OUT_DIR.glob(f"{video_id}.*"))
    return matches[0] if matches else None


def insert_error(r: str, source_id: str, stage: str, msg: str) -> None:
    _err("youtube", run_id=r, source_id=source_id,
         stage=stage, error_type="unknown", message=msg)


def process_entry(entry, *, channel_id: str, channel_name: str,
                  feed_key: str, mode: str, r: str) -> None:
    video_url = entry.get("link", "")
    if not video_url:
        return
    if RETRY_SOURCE and channel_id != RETRY_SOURCE:
        return
    if not is_recent(entry):
        return
    if yt_exists(video_url):
        return

    video_id = entry.get("yt_videoid") or ""
    if not video_id:
        m = re.search(r"v=([^&]+)", video_url)
        video_id = m.group(1) if m else ""

    subtitle: str | None = None
    media_path: Path | None = None

    if mode in ("subtitle", "mixed"):
        vtt      = download_subtitle(video_url)
        subtitle = clean_vtt(vtt) if vtt else None

    if mode in ("video", "audio"):
        media_path = download_media(video_url, video_id, audio_only=(mode == "audio"))
        # media_path is left on disk under MEDIA_OUT_DIR; the calling workflow
        # step uploads it as a GitHub Release asset (gh release upload) and
        # is responsible for cleanup — see .github/workflows/yt_weekly.yml
    elif mode == "mixed" and not subtitle:
        # Subtitles came back empty for a "mixed" channel — fall back to a
        # low-res video so the story isn't lost entirely.
        media_path = download_media(video_url, video_id, audio_only=False)

    if media_path:
        MEDIA_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MEDIA_MAP_FILE, "a", encoding="utf-8") as f:
            f.write(f"{video_id}\t{video_url}\n")

    insert_yt(
        video_url=video_url, video_id=video_id,
        channel_id=channel_id, channel_name=channel_name,
        feed_key=feed_key, title=entry.get("title", ""),
        subtitle=subtitle, published_at=entry.get("published", r),
        mode=mode,
        # media_url is filled in later by the workflow, after the GitHub
        # Release upload step, via set_yt_media_url()
    )
    status = "subtitle OK" if subtitle else ("media OK" if media_path else "no subtitle/media")
    print(f"  [{channel_name}] {entry.get('title', '')[:55]} — {status} (mode={mode})")


def fetch_channel(channel_id: str, channel_name: str, feed_key: str, mode: str, r: str) -> None:
    url = yt_feed_url(channel_id)
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        for entry in feed.entries:
            try:
                process_entry(entry, channel_id=channel_id, channel_name=channel_name,
                              feed_key=feed_key, mode=mode, r=r)
            except Exception as ex:
                insert_error(r, entry.get("link", url), "parse", str(ex))
    except Exception as ex:
        insert_error(r, url, "fetch", str(ex))


def main() -> None:
    r     = run_id()
    tasks = []
    for group in yt_feeds():
        feed_key = group["key"]
        for src in group.get("sources", []):
            cid = src.get("channel_id", "")
            if not cid or cid == "FILL_ME":
                continue
            mode = src.get("mode", "mixed")
            if mode == "FILL_ME" or mode not in VALID_MODES:
                mode = "mixed"  # unclassified channels get today's default behavior
            tasks.append(dict(channel_id=cid, channel_name=src["name"],
                              feed_key=feed_key, mode=mode))

    print(f"ingest_youtube: {len(tasks)} channels, {MAX_WORKERS} workers")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        futures = {
            exe.submit(fetch_channel, t["channel_id"], t["channel_name"],
                      t["feed_key"], t["mode"], r): t
            for t in tasks
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as ex:
                print(f"[unhandled] {futures[future]['channel_name']}: {ex}")

    print("ingest_youtube: done")


if __name__ == "__main__":
    main()
