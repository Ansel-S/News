#!/usr/bin/env bash
# test_local.sh — Dewsletter full local test
# Run inside GitHub Codespace or any Linux environment
# Usage: bash test_local.sh [step]
#   steps: deps | init | rss | hn | yt | render | all
# Example: bash test_local.sh all

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$ROOT/scripts"
PASS=0; FAIL=0

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓ $*${NC}"; ((PASS++)) || true; }
fail() { echo -e "${RED}  ✗ $*${NC}"; ((FAIL++)) || true; }
info() { echo -e "${YELLOW}▶ $*${NC}"; }

# ── Step runner ───────────────────────────────────────────────────────────────
run() {
    local label="$1"; shift
    info "$label"
    if "$@"; then ok "$label"; else fail "$label"; fi
    echo
}

# ── 1. Dependencies ───────────────────────────────────────────────────────────
step_deps() {
    info "Installing Python dependencies..."
    pip install -q feedparser requests trafilatura pyyaml yt-dlp
    ok "pip install done"

    # yt-dlp sanity check
    if yt-dlp --version &>/dev/null; then
        ok "yt-dlp $(yt-dlp --version)"
    else
        fail "yt-dlp not found"
    fi
    echo
}

# ── 2. DB init ────────────────────────────────────────────────────────────────
step_init() {
    info "Initializing databases..."
    cd "$ROOT"
    python scripts/db_init.py
    for db in core hn dive zen paper report youtube; do
        if [ -f "database/${db}.db" ]; then
            ok "database/${db}.db created"
        else
            fail "database/${db}.db missing"
        fi
    done
    echo
}

# ── 3. RSS ingest (uses real network, limited to 2 feeds for speed) ───────────
step_rss() {
    info "Testing RSS ingest (core.db only, LOOKBACK_DAYS=1)..."
    cd "$ROOT"
    LOOKBACK_DAYS=1 RSS_WORKERS=4 python scripts/ingest_rss.py core

    count=$(sqlite3 database/core.db "SELECT COUNT(*) FROM items;" 2>/dev/null || echo 0)
    if [ "$count" -gt 0 ]; then
        ok "core.db: $count items ingested"
    else
        fail "core.db: 0 items — check network or feed URLs"
    fi

    err_count=$(sqlite3 database/core.db "SELECT COUNT(*) FROM errors;" 2>/dev/null || echo 0)
    if [ "$err_count" -gt 0 ]; then
        echo -e "${YELLOW}  ⚠ $err_count errors logged in core.db errors table:${NC}"
        sqlite3 database/core.db "SELECT source_id, stage, message FROM errors LIMIT 5;"
    fi
    echo
}

# ── 4. HN ingest ─────────────────────────────────────────────────────────────
step_hn() {
    info "Testing HackerNews ingest..."
    cd "$ROOT"
    python scripts/ingest_hn.py

    count=$(sqlite3 database/hn.db "SELECT COUNT(*) FROM hn_items;" 2>/dev/null || echo 0)
    if [ "$count" -gt 0 ]; then
        ok "hn.db: $count items (score > 350)"
        sqlite3 database/hn.db "SELECT score, title FROM hn_items ORDER BY score DESC LIMIT 3;" \
            | while IFS='|' read -r score title; do
            echo "    ▲${score} ${title:0:70}"
        done
    else
        fail "hn.db: 0 items — HN API may be rate-limited, try again"
    fi
    echo
}

# ── 5. YouTube ingest (single public channel, no channel_id required) ─────────
step_yt() {
    info "Testing YouTube ingest (FISH13 — hardcoded channel_id in yt.yaml)..."
    cd "$ROOT"

    # Only run if at least one channel_id is filled in yt.yaml
    filled=$(grep -v "FILL_ME" feeds/yt.yaml | grep "channel_id:" | wc -l || true)
    if [ "$filled" -eq 0 ]; then
        echo -e "${YELLOW}  ⚠ No channel_ids filled in feeds/yt.yaml — skipping YouTube test${NC}"
        echo -e "    FISH13 (UCQnmZZUKvpY3IVSGf44MVVg) is pre-filled and will be tested."
        echo
    fi

    LOOKBACK_DAYS=3 YT_WORKERS=1 python scripts/ingest_youtube.py

    count=$(sqlite3 database/youtube.db "SELECT COUNT(*) FROM yt_items;" 2>/dev/null || echo 0)
    sub_count=$(sqlite3 database/youtube.db "SELECT COUNT(*) FROM yt_items WHERE has_subtitle=1;" 2>/dev/null || echo 0)

    if [ "$count" -gt 0 ]; then
        ok "youtube.db: $count videos, $sub_count with subtitles"
    else
        fail "youtube.db: 0 items"
    fi
    echo
}

# ── 6. Render all issues ──────────────────────────────────────────────────────
step_render() {
    info "Rendering all issues..."
    cd "$ROOT"

    # Seed fake data into empty DBs so renders don't bail with "nothing to send"
    _seed_if_empty() {
        local db="$1" table="$2"
        local count
        count=$(sqlite3 "database/${db}.db" "SELECT COUNT(*) FROM ${table};" 2>/dev/null || echo 0)
        if [ "$count" -eq 0 ]; then
            echo -e "    ${YELLOW}⚠ ${db}.db empty — inserting dummy row for render test${NC}"
            case "$db" in
                dive|zen|paper)
                    sqlite3 "database/${db}.db" \
                        "INSERT OR IGNORE INTO items VALUES(
                           'test-id-${db}','http://example.com/${db}',
                           'rss.${db}','Test Source','title_only',
                           'Test Title','Test content for ${db}.',
                           '2025-01-01T00:00:00Z','2025-01-01T00:00:00Z',10,1);"
                    ;;
                report)
                    sqlite3 "database/report.db" \
                        "INSERT OR IGNORE INTO reports VALUES(
                           'test-id-report','http://example.com/report.pdf',
                           'rss.report','Test Publisher',
                           'Test Report Title',NULL,NULL,
                           '2025-01-01T00:00:00Z','2025-01-01T00:00:00Z');"
                    ;;
                youtube)
                    sqlite3 "database/youtube.db" \
                        "INSERT OR IGNORE INTO yt_items VALUES(
                           'test-id-yt','https://youtu.be/test','test_id',
                           'UC_test','Test Channel','yt.zen',
                           'Test Video Title',NULL,
                           '2025-01-01T00:00:00Z','2025-01-01T00:00:00Z',0);"
                    ;;
            esac
        fi
    }

    _seed_if_empty dive  items
    _seed_if_empty zen   items
    _seed_if_empty paper items
    _seed_if_empty report reports
    _seed_if_empty youtube yt_items

    for renderer in render_daily render_dive render_zen render_paper render_report render_yt; do
        if python "scripts/${renderer}.py"; then
            outfile="out_${renderer#render_}.html"
            # render_daily → out_daily.html (special case)
            [ "$renderer" = "render_daily" ] && outfile="out_daily.html"
            if [ -f "$outfile" ]; then
                size=$(wc -c < "$outfile")
                ok "${renderer}.py → ${outfile} (${size} bytes)"
            else
                fail "${renderer}.py ran but no output file found"
            fi
        else
            fail "${renderer}.py crashed"
        fi
    done
    echo
}

# ── 7. HTML sanity check ──────────────────────────────────────────────────────
step_html_check() {
    info "Checking rendered HTML files..."
    cd "$ROOT"
    for f in out_daily.html out_dive.html out_zen.html out_paper.html out_report.html out_yt.html; do
        if [ ! -f "$f" ]; then
            fail "$f not found"
            continue
        fi
        # Must contain basic email shell markers
        if grep -q "Dewsletter" "$f" && grep -q "</html>" "$f"; then
            size=$(wc -c < "$f")
            ok "$f OK (${size} bytes)"
        else
            fail "$f looks malformed"
        fi
    done
    echo
}

# ── Summary ───────────────────────────────────────────────────────────────────
step_summary() {
    echo "──────────────────────────────────────────"
    echo -e "Results: ${GREEN}${PASS} passed${NC}  ${RED}${FAIL} failed${NC}"
    echo "──────────────────────────────────────────"
    echo
    echo "To preview rendered emails:"
    echo "  # In Codespace: right-click out_daily.html → Open with Live Server"
    echo "  # Or serve locally:"
    echo "  python -m http.server 8080"
    echo "  # Then open http://localhost:8080/out_daily.html"
    echo
    if [ "$FAIL" -gt 0 ]; then exit 1; fi
}

# ── Main ──────────────────────────────────────────────────────────────────────
STEP="${1:-all}"

case "$STEP" in
    deps)   step_deps ;;
    init)   step_init ;;
    rss)    step_rss ;;
    hn)     step_hn ;;
    yt)     step_yt ;;
    render) step_render; step_html_check ;;
    all)
        step_deps
        step_init
        step_rss
        step_hn
        step_yt
        step_render
        step_html_check
        step_summary
        ;;
    *)
        echo "Usage: bash test_local.sh [deps|init|rss|hn|yt|render|all]"
        exit 1
        ;;
esac
