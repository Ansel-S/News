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
from pathlib import Path

import feedparser
import requests

from config import yt_feeds
from db_utils import (
    run_id, yt_exists, mark_yt_seen, insert_yt, insert_yt_media_item,
    insert_error as _err, now_iso,
)
from ingest_base import is_recent as _is_recent, run_parallel

MAX_WORKERS   = int(os.getenv("YT_WORKERS", "3"))
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "8"))
RETRY_SOURCE  = os.getenv("RETRY_ONLY_SOURCE")

# Where low-res video/audio downloads land before being uploaded as GitHub
# Release assets by the workflow. Each file must stay under GitHub's 2 GiB
# per-asset limit (no total-size limit on a release) — see docs.github.com
# /en/repositories/releasing-projects-on-github/about-releases
MEDIA_OUT_DIR = Path(os.getenv("YT_MEDIA_DIR", "media_out"))

# Target: smallest reasonable quality, still watchable/listenable.
# vp09/av01 @ 720p (or below, whichever is available) video-only when we don't
# need subtitles at all; audio-only (m4a/opus) when the video track is useless.
VIDEO_FORMAT = "bestvideo[height<=720][vcodec^=vp09]/bestvideo[height<=720][vcodec^=av01]/bestvideo[height<=720]+bestaudio/best[height<=720]"
AUDIO_FORMAT = "bestaudio[abr<=96]/bestaudio"

VALID_MODES = {"subtitle", "video", "mixed", "audio"}


def yt_feed_url(channel_id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def is_recent(entry) -> bool:
    return _is_recent(entry, lookback_days=LOOKBACK_DAYS)


def pick_subtitle_file(tmp_dir: Path) -> Path | None:
    """Find the best subtitle file yt-dlp wrote, preferring non-English vtt,
    then non-English ass, then falling back to whatever English version
    exists. We don't force --sub-format vtt anymore since some channels only
    have .ass subtitles that yt-dlp can't always convert cleanly — better to
    grab whatever format is actually available and clean it ourselves."""
    candidates = list(tmp_dir.glob("*.vtt")) + list(tmp_dir.glob("*.ass"))
    if not candidates:
        return None

    def is_english(f: Path) -> bool:
        return bool(re.search(r"\.(en|en-orig|en-US|en-GB)[.-]", f.name)) or f.name.endswith((".en.vtt", ".en.ass"))

    non_en = [f for f in candidates if not is_english(f)]
    pool = non_en or candidates
    # Prefer vtt over ass when both exist for the same language, since vtt is
    # simpler to clean and usually higher fidelity for auto-generated subs.
    vtt_pool = [f for f in pool if f.suffix == ".vtt"]
    return vtt_pool[0] if vtt_pool else pool[0]


def download_subtitle(video_url: str) -> str | None:
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [
            "yt-dlp", "--skip-download",
            "--write-sub", "--write-auto-sub",
            "--sub-langs", "all,-live_chat",
            "--output", f"{tmp}/%(id)s",
            video_url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return None
        chosen = pick_subtitle_file(Path(tmp))
        if not chosen:
            return None
        raw = chosen.read_text("utf-8", errors="ignore")
        return clean_ass(raw) if chosen.suffix == ".ass" else clean_vtt(raw)


def clean_ass(ass: str) -> str:
    """Extract spoken text from an .ass subtitle file: keep only Dialogue
    lines, drop timing/style/effect fields, strip {\\...} override tags and
    line-break markers, dedupe repeated lines (common with karaoke-style
    overlapping dialogue events)."""
    seen: set[str] = set()
    lines: list[str] = []
    for raw_line in ass.splitlines():
        if not raw_line.startswith("Dialogue:"):
            continue
        # Dialogue: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
        # Text is the 10th comma-separated field, but may itself contain commas,
        # so split with a limit.
        fields = raw_line.split(",", 9)
        if len(fields) < 10:
            continue
        text = fields[9]
        text = re.sub(r"\{[^}]*\}", "", text)      # {\an8}, {\pos(...)}, etc.
        text = text.replace("\\N", " ").replace("\\n", " ").strip()
        if text and text not in seen:
            seen.add(text)
            lines.append(text)
    return " ".join(lines)


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


def download_media(video_url: str, video_id: str, *, kind: str) -> Path | None:
    """Download a low-res video (vp09/av01, <=720p) or audio-only track.
    `kind` is 'video' or 'audio' — used as a filename suffix so a channel that
    wants both doesn't have one overwrite the other. Returns the output file
    path, or None on failure. Caller uploads it as a GitHub Release asset and
    deletes the local copy afterwards."""
    MEDIA_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(MEDIA_OUT_DIR / f"{video_id}.{kind}.%(ext)s")
    fmt = AUDIO_FORMAT if kind == "audio" else VIDEO_FORMAT
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
    matches = list(MEDIA_OUT_DIR.glob(f"{video_id}.{kind}.*"))
    return matches[0] if matches else None


def insert_error(r: str, source_id: str, stage: str, msg: str) -> None:
    _err("youtube", run_id=r, source_id=source_id,
         stage=stage, error_type="unknown", message=msg)


def process_entry(entry, *, channel_id: str, channel_name: str,
                  feed_key: str, modes: list[str], r: str) -> None:
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
    media_paths: dict[str, Path] = {}  # kind -> path, e.g. {"video": ..., "audio": ...}

    want_subtitle = "subtitle" in modes or "mixed" in modes
    want_video    = "video" in modes
    want_audio    = "audio" in modes

    if want_subtitle:
        subtitle = download_subtitle(video_url)  # already cleaned (vtt or ass)

    if want_video:
        p = download_media(video_url, video_id, kind="video")
        if p:
            media_paths["video"] = p
    if want_audio:
        p = download_media(video_url, video_id, kind="audio")
        if p:
            media_paths["audio"] = p

    if "mixed" in modes and not subtitle and not media_paths:
        # Subtitles came back empty and no explicit video/audio was requested.
        # Fallback order mirrors the "listening > watching" preference:
        # try audio first, and only fall back to a low-res video if even
        # that isn't available (e.g. a members-only or otherwise restricted
        # audio stream).
        p = download_media(video_url, video_id, kind="audio")
        if p:
            media_paths["audio"] = p
        else:
            p = download_media(video_url, video_id, kind="video")
            if p:
                media_paths["video"] = p

    # Every processed video is marked seen for dedup, regardless of whether
    # it produced subtitles, video, or audio — this is what stops pure
    # video/audio-mode channels from being re-downloaded on every run even
    # though they never get a yt_items row.
    mark_yt_seen(video_url, video_id)

    insert_yt(
        video_url=video_url, video_id=video_id,
        channel_id=channel_id, channel_name=channel_name,
        feed_key=feed_key, title=entry.get("title", ""),
        subtitle=subtitle, published_at=entry.get("published", r),
        mode=",".join(modes),
        # insert_yt is a no-op if subtitle is empty/None — only videos that
        # actually produced subtitle text get a yt_items row.
    )
    if not subtitle and media_paths:
        # No subtitle text, but this video/audio-only channel still needs a
        # title + download-link row in the weekly email — see yt_media_items.
        insert_yt_media_item(
            video_url=video_url, video_id=video_id,
            channel_id=channel_id, channel_name=channel_name,
            feed_key=feed_key, title=entry.get("title", ""),
            published_at=entry.get("published", r), mode=",".join(modes),
        )
    status_bits = []
    if subtitle:
        status_bits.append("subtitle")
    status_bits += list(media_paths.keys())
    status = "+".join(status_bits) if status_bits else "nothing found"
    print(f"  [{channel_name}] {entry.get('title', '')[:55]} — {status} (modes={modes})")


def fetch_channel(channel_id: str, channel_name: str, feed_key: str, modes: list[str], r: str) -> None:
    url = yt_feed_url(channel_id)
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        for entry in feed.entries:
            try:
                process_entry(entry, channel_id=channel_id, channel_name=channel_name,
                              feed_key=feed_key, modes=modes, r=r)
            except Exception as ex:
                insert_error(r, entry.get("link", url), "parse", str(ex))
    except Exception as ex:
        insert_error(r, url, "fetch", str(ex))


def _normalize_modes(raw) -> list[str]:
    """Accept either the old single-string form or the new list form.
    Unknown/FILL_ME entries fall back to ['mixed'] (today's default behavior)."""
    if raw is None:
        return ["mixed"]
    if isinstance(raw, str):
        raw = [raw]
    modes = [m for m in raw if m in VALID_MODES]
    return modes or ["mixed"]


def main() -> None:
    r     = run_id()
    tasks = []
    for group in yt_feeds():
        feed_key = group["key"]
        for src in group.get("sources", []):
            cid = src.get("channel_id", "")
            if not cid or cid == "FILL_ME":
                continue
            modes = _normalize_modes(src.get("mode"))
            tasks.append(dict(channel_id=cid, channel_name=src["name"],
                              feed_key=feed_key, modes=modes, r=r))

    print(f"ingest_youtube: {len(tasks)} channels, {MAX_WORKERS} workers")
    run_parallel(tasks, fetch_channel, max_workers=MAX_WORKERS, label_key="channel_name")

    print("ingest_youtube: done")


if __name__ == "__main__":
    main()
