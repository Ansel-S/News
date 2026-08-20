#!/usr/bin/env bash
# test_yt.sh — Standalone YouTube ingest + render test
# Run inside GitHub Codespace or any Linux environment.
#
# Usage:
#   bash test_yt.sh                 # test every configured channel
#   bash test_yt.sh <channel_id>    # test one channel only (fast — use this
#                                    # first when diagnosing a failure)
#   bash test_yt.sh <channel name>  # matches config's `name` field instead
#
# This only exercises the YouTube path (ingest_youtube.py + render_yt.py) —
# it does NOT touch content.db/hn.db/report.db, so it's safe to run
# repeatedly without affecting other issues' dedup state. Deletes and
# recreates youtube.db each run so results are never stale from a previous
# test.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PASS=0; FAIL=0

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓ $*${NC}"; ((PASS++)) || true; }
fail() { echo -e "${RED}  ✗ $*${NC}"; ((FAIL++)) || true; }
info() { echo -e "${YELLOW}▶ $*${NC}"; }

cd "$ROOT"

ONLY="${1:-}"
if [ -n "$ONLY" ]; then
    info "Testing YouTube ingest — single channel: $ONLY"
else
    info "Testing YouTube ingest — all configured channels"
fi

# ── 1. Fresh youtube.db ────────────────────────────────────────────────────
rm -f database/youtube.db
python scripts/db/db_init.py youtube
if [ -f database/youtube.db ]; then
    ok "database/youtube.db created"
else
    fail "database/youtube.db missing — aborting"
    exit 1
fi
echo

# ── 2. Ingest ────────────────────────────────────────────────────────────────
info "Running ingest_youtube.py..."
if [ -n "$ONLY" ]; then
    LOOKBACK_DAYS="${LOOKBACK_DAYS:-8}" YT_WORKERS=1 YT_ONLY_CHANNEL="$ONLY" \
        python scripts/ingest/ingest_youtube.py
else
    LOOKBACK_DAYS="${LOOKBACK_DAYS:-8}" YT_WORKERS="${YT_WORKERS:-3}" \
        python scripts/ingest/ingest_youtube.py
fi
echo

# The ok/no_media/empty/blocked/fetch_error tally printed above by ingest_youtube.py
# itself is the real diagnosis — these checks below only confirm whether
# anything landed in the db, not why.
yt_count=$(sqlite3 database/youtube.db "SELECT COUNT(*) FROM yt_items;" 2>/dev/null || echo 0)
media_count=$(sqlite3 database/youtube.db "SELECT COUNT(*) FROM yt_media_items;" 2>/dev/null || echo 0)
count=$((yt_count + media_count))

if [ "$count" -gt 0 ]; then
    ok "youtube.db: $count videos ($yt_count with subtitles, $media_count media-only)"
    echo "  Sample rows:"
    sqlite3 database/youtube.db \
        "SELECT source_name, title FROM yt_items UNION ALL SELECT source_name, title FROM yt_media_items LIMIT 5;" \
        | while IFS='|' read -r name title; do
        echo "    [$name] ${title:0:60}"
    done
else
    fail "youtube.db: 0 items — see the ok/no_media/empty/blocked/fetch_error tally above for why"
fi
echo

# ── 3. Render (only if something was actually ingested) ─────────────────────
if [ "$count" -gt 0 ]; then
    info "Rendering out_yt.html..."
    if python scripts/render/render_yt.py; then
        if [ -f out_yt.html ]; then
            size=$(wc -c < out_yt.html)
            ok "render_yt.py → out_yt.html (${size} bytes)"
        else
            fail "render_yt.py ran but out_yt.html not found"
        fi
    else
        fail "render_yt.py crashed"
    fi
else
    info "Skipping render — nothing to render"
fi
echo

# ── Summary ──────────────────────────────────────────────────────────────────
echo "──────────────────────────────────────────"
echo "Results: ${PASS} passed  ${FAIL} failed"
echo "──────────────────────────────────────────"
if [ -f out_yt.html ]; then
    echo "Preview: python -m http.server 8080, then open http://localhost:8080/out_yt.html"
fi

[ "$FAIL" -eq 0 ]