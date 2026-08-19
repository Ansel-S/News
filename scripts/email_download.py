"""
email_download.py — Email-triggered download-to-release pipeline.

An inbound email with subject "[github(<url>)asong56]" triggers downloading
<url> and uploading it as a GitHub Release asset, then emails the result
back. Runs on a cron schedule (every 3 days), not event-driven.

handled.db is the sole source of truth for processing state; marking an
email read/seen is inbox hygiene only.

Required env vars: SMTP_USER, SMTP_PASS, IMAP_HOST, GH_TOKEN, GITHUB_REPOSITORY
"""
from __future__ import annotations

import email
import imaplib
import json
import os
import re
import smtplib
import sqlite3
import sys
import uuid as uuid_mod
from datetime import datetime, timedelta, UTC
from email.header import decode_header, make_header
from email.mime.text import MIMEText
from pathlib import Path

import requests

from config import ROOT, db_path
from db.db_utils import now_iso
import release.release_utils as release_utils

SUBJECT_RE = re.compile(r"^\[github\((?P<url>.+)\)asong56\]$")

RETRY_BUDGET_ATTEMPTS = 3
DOWNLOAD_TIMEOUT_SECONDS = 60
MAX_DOWNLOAD_BYTES = 1_900_000_000  # stay under GitHub's 2 GiB asset limit
CHUNK_SIZE = 1024 * 1024

FAILURE_LOG_PATH = ROOT / "database" / "email_download_failures.json"
FAILURE_LOG_MAX_AGE_DAYS = 60
TMP_DIR = ROOT / "tmp_downloads"

IMAP_HOST = os.environ.get("IMAP_HOST", "imap.gmail.com")
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
GH_REPO = os.environ.get("GITHUB_REPOSITORY")


# ── handled.db access ────────────────────────────────────────────────────
# `requests` is a bespoke state-machine table (uuid/url/attempts/status),
# not items-shaped, so it doesn't reuse db_utils.py's item_* helpers.

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(db_path("handled"), timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    return c


def _seen_urls() -> set[str]:
    with _conn() as c:
        return {r["url"] for r in c.execute("SELECT url FROM requests")}


def _insert_request(uuid_str: str, url: str) -> None:
    with _conn() as c:
        c.execute(
            """INSERT OR IGNORE INTO requests (uuid, url, first_seen, attempts, status)
               VALUES (?, ?, ?, 0, 'pending')""",
            (uuid_str, url, now_iso()),
        )


def _pending_requests() -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute(
            "SELECT * FROM requests WHERE status='pending' AND attempts < ?",
            (RETRY_BUDGET_ATTEMPTS,),
        ).fetchall()


def _mark_done(uuid_str: str, filename: str, asset_url: str) -> None:
    with _conn() as c:
        c.execute(
            """UPDATE requests SET status='done', filename=?, asset_url=?,
               last_attempt=? WHERE uuid=?""",
            (filename, asset_url, now_iso(), uuid_str),
        )


def _mark_attempt_failed(uuid_str: str, attempts: int, error: str, *, final: bool = False) -> str:
    """Increments attempts (unless final=True, a definitive failure that skips
    the retry budget entirely, e.g. an oversize file that will never succeed).
    Returns the resulting status."""
    new_attempts = attempts if final else attempts + 1
    status = "failed-final" if final or new_attempts >= RETRY_BUDGET_ATTEMPTS else "pending"
    with _conn() as c:
        c.execute(
            """UPDATE requests SET attempts=?, last_attempt=?, status=?, error=?
               WHERE uuid=?""",
            (new_attempts, now_iso(), status, error, uuid_str),
        )
    return status


# ── Failure log ──────────────────────────────────────────────────────────
# Human-readable audit trail only. handled.db remains authoritative for
# processing state; this is appended-to and rotated, never read back.

def _append_failure_log(uuid_str: str, url: str, error: str) -> None:
    entries = []
    if FAILURE_LOG_PATH.exists():
        try:
            entries = json.loads(FAILURE_LOG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            entries = []

    cutoff = datetime.now(UTC) - timedelta(days=FAILURE_LOG_MAX_AGE_DAYS)
    kept = []
    for e in entries:
        try:
            ts = datetime.strptime(e["failed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        except (KeyError, ValueError):
            continue
        if ts >= cutoff:
            kept.append(e)

    kept.append({"uuid": uuid_str, "url": url, "error": error, "failed_at": now_iso()})
    FAILURE_LOG_PATH.parent.mkdir(exist_ok=True)
    FAILURE_LOG_PATH.write_text(json.dumps(kept, indent=2), encoding="utf-8")


# ── Email sending ────────────────────────────────────────────────────────

def _send_email(subject: str, body: str) -> None:
    if not SMTP_USER or not SMTP_PASS:
        print("email_download: SMTP_USER/SMTP_PASS not set, skipping send:", subject)
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = SMTP_USER  # self-only tool: replies go back to the same mailbox
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)


def _send_received(uuid_str: str, url: str) -> None:
    _send_email(
        f"Request Received: {uuid_str}",
        f"Your download request has been queued.\n\nUUID: {uuid_str}\nURL: {url}\n",
    )


def _send_succeed(uuid_str: str, url: str, asset_url: str) -> None:
    _send_email(
        f"Request Succeed: {uuid_str}",
        f"Your download request finished.\n\nUUID: {uuid_str}\nURL: {url}\n"
        f"Release asset: {asset_url}\n",
    )


def _send_failed(uuid_str: str, url: str, error: str) -> None:
    _send_email(
        f"Request Failed: {uuid_str}",
        f"Your download request could not be completed.\n\n"
        f"UUID: {uuid_str}\nURL: {url}\nLast error: {error}\n",
    )


# ── Phase 1: scan inbox for new requests ─────────────────────────────────

def _decode_subject(raw: str | None) -> str:
    if not raw:
        return ""
    return str(make_header(decode_header(raw))).strip()


def scan_inbox() -> None:
    if not SMTP_USER or not SMTP_PASS:
        print("email_download: SMTP_USER/SMTP_PASS not set, skipping inbox scan")
        return

    seen = _seen_urls()

    with imaplib.IMAP4_SSL(IMAP_HOST) as imap:
        imap.login(SMTP_USER, SMTP_PASS)
        status, _ = imap.select("INBOX")
        if status != "OK":
            print("email_download: IMAP SELECT INBOX failed:", status)
            return

        status, data = imap.search(None, "UNSEEN")
        if status != "OK":
            print("email_download: IMAP search failed:", status)
            return

        for msg_num in data[0].split():
            status, msg_data = imap.fetch(msg_num, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            subject = _decode_subject(msg.get("Subject"))

            m = SUBJECT_RE.match(subject)
            # Mark read regardless of match — inbox hygiene only, never
            # the thing that decides whether a request gets processed.
            imap.store(msg_num, "+FLAGS", "\\Seen")
            if not m:
                continue

            url = m.group("url").strip()
            if url in seen:
                continue  # already registered under an earlier UUID

            request_uuid = str(uuid_mod.uuid4())
            _insert_request(request_uuid, url)
            seen.add(url)
            _send_received(request_uuid, url)
            print(f"email_download: registered {request_uuid} -> {url}")


# ── Phase 2: process pending requests ────────────────────────────────────

def _derive_filename(url: str, resp: requests.Response, fallback: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";\n]+)"?', cd)
    if m:
        return m.group(1).strip()

    last_segment = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return last_segment or fallback


class OversizeError(ValueError):
    """Raised when a download exceeds MAX_DOWNLOAD_BYTES. Distinct from other
    download errors because it's a definitive failure — the file will never
    shrink on retry, so callers should skip the retry budget entirely."""


def _download(url: str, request_uuid: str) -> Path:
    """Download url to a temp file, capping actual bytes read regardless of
    what Content-Length claims (or omits)."""
    TMP_DIR.mkdir(exist_ok=True)

    with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
        resp.raise_for_status()
        filename = _derive_filename(url, resp, fallback=request_uuid)
        dest = TMP_DIR / f"{request_uuid}__{filename}"

        total = 0
        try:
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise OversizeError(
                            f"download exceeded {MAX_DOWNLOAD_BYTES} byte cap"
                        )
                    f.write(chunk)
        except Exception:
            dest.unlink(missing_ok=True)
            raise

    return dest


def _process_one(row: sqlite3.Row, tag: str) -> None:
    request_uuid, url, attempts = row["uuid"], row["url"], row["attempts"]
    try:
        local_path = _download(url, request_uuid)
        renamed = local_path.parent / f"{request_uuid}-{local_path.name.split('__', 1)[-1]}"
        local_path.rename(renamed)

        asset_url = release_utils.upload_file(GH_REPO, tag, renamed)
        if asset_url is None:
            raise RuntimeError("release upload failed (see release_utils output above)")

        _mark_done(request_uuid, renamed.name, asset_url)
        _send_succeed(request_uuid, url, asset_url)
        print(f"email_download: {request_uuid} done -> {asset_url}")

    except OversizeError as exc:
        # Definitive failure: retrying won't make the file smaller, so skip
        # straight to failed-final instead of burning the retry budget.
        error_msg = str(exc)
        _mark_attempt_failed(request_uuid, attempts, error_msg, final=True)
        _append_failure_log(request_uuid, url, error_msg)
        _send_failed(request_uuid, url, error_msg)
        print(f"email_download: {request_uuid} oversize, failed-final ({error_msg})")

    except Exception as exc:  # noqa: BLE001 — any other failure just retries/logs
        error_msg = str(exc)
        status = _mark_attempt_failed(request_uuid, attempts, error_msg)
        print(f"email_download: {request_uuid} attempt failed ({error_msg})")
        if status == "failed-final":
            _append_failure_log(request_uuid, url, error_msg)
            _send_failed(request_uuid, url, error_msg)

    finally:
        for stray in TMP_DIR.glob(f"{request_uuid}*"):
            stray.unlink(missing_ok=True)


def process_pending() -> None:
    if not GH_REPO:
        print("email_download: GITHUB_REPOSITORY not set, skipping processing")
        return

    pending = _pending_requests()
    if not pending:
        return

    # One release per run, shared by every pending request today.
    # ensure_release is a no-op if it already exists.
    tag = f"email-download-{datetime.now(UTC).strftime('%Y%m%d')}"
    release_utils.ensure_release(GH_REPO, tag, notes=f"Dewsletter email-triggered downloads for {tag}")

    for row in pending:
        _process_one(row, tag)


def main() -> None:
    scan_inbox()
    process_pending()


if __name__ == "__main__":
    sys.exit(main())
