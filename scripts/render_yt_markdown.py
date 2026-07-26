"""
render_yt_markdown.py — Export this week's yt_items (with subtitles) as
individual markdown files, zipped as an email attachment, instead of
attaching the raw youtube.db (which required `duckdb --ui` to read).

Videos without subtitles (mode=video/audio, low-res media instead) are not
included here — they're linked via the GitHub Release badge in the email body.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_ZIP = ROOT / "out_yt.zip"
TMP_DIR = ROOT / ".yt_tmp"


def slugify(text: str, max_len: int = 60) -> str:
    import re
    text = re.sub(r"[^\w\s-]", "", text or "", flags=re.UNICODE).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:max_len].strip("-") or "untitled"


def write_and_zip(rows) -> int:
    """rows: sqlite3.Row list with title, channel_name, video_url, subtitle,
    published_at. Writes one .md per video with a subtitle, zips them into
    OUT_ZIP. Returns the count of files written."""
    if TMP_DIR.exists():
        import shutil
        shutil.rmtree(TMP_DIR)
    TMP_DIR.mkdir(parents=True)

    seen: dict[str, int] = {}
    paths: list[Path] = []

    for row in rows:
        if not row["subtitle"]:
            continue
        slug = slugify(row["title"])
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        fname = f"{slug}.md" if n == 0 else f"{slug}-{n}.md"

        content = (
            f"# {row['title'] or '(untitled)'}\n\n"
            f"*{row['channel_name']} · {(row['published_at'] or '')[:10]}*\n\n"
            f"{row['video_url']}\n\n---\n\n"
            f"{row['subtitle']}\n"
        )
        path = TMP_DIR / fname
        path.write_text(content, encoding="utf-8")
        paths.append(path)

    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, arcname=p.name)

    import shutil
    shutil.rmtree(TMP_DIR)
    return len(paths)
