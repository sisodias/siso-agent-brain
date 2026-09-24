#!/bin/zsh
# ship_spine_delta.sh — laptop→Mini spine delta sync (idempotent)
#
# Steps:
#   1. VACUUM INTO a clean snapshot in /tmp (avoids shipping WAL state)
#   2. rsync the snapshot to Mini staging directory
#   3. SSH-run spine_merge.py on Mini (source=staged snapshot, target=Mini canonical)
#   4. Capture merge output + exit code
#   5. Clean up staging file on Mini
#
# Idempotent by design: re-running inserts 0 rows once in sync.
# Safe: never replaces either spine file — only INSERT OR IGNORE merges.
#
# Usage: ./ship_spine_delta.sh [--dry-run]
#   --dry-run  passes --dry-run to spine_merge.py (no writes to Mini spine)
#
# Environment:
#   LAPTOP_DB  — laptop spine path (default: ~/SISO_Workspace/.SystemDB/sisosystem.db)
#   MINI_HOST  — Mini SSH hostname (default: shaans-mac-mini.tail100d11.ts.net)
#   MINI_USER  — Mini SSH user (default: shaansisodia)
#   MINI_DB    — Mini canonical spine path (default: ~/SISO_Workspace/.SystemDB/sisosystem.db)
#   MERGE_SCRIPT — path to spine_merge.py on Mini (default: ~/SISO_Workspace/SISO_Agents/siso-agent-brain/extensions/braind/spine_merge.py)

set -euo pipefail

LAPTOP_DB="${LAPTOP_DB:-$HOME/SISO_Workspace/.SystemDB/sisosystem.db}"
MINI_HOST="${MINI_HOST:-shaans-mac-mini.tail100d11.ts.net}"
MINI_USER="${MINI_USER:-shaansisodia}"
MINI_DB="${MINI_DB:-$HOME/SISO_Workspace/.SystemDB/sisosystem.db}"
MERGE_SCRIPT="${MERGE_SCRIPT:-$HOME/SISO_Workspace/SISO_Agents/siso-agent-brain/extensions/braind/spine_merge.py}"

DRY_RUN_FLAG=""
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN_FLAG="--dry-run"  # NOTE: spine_merge.py uses --apply, so absence = dry-run
    echo "[ship_spine_delta] DRY-RUN mode — no writes to Mini spine"
fi

APPLY_FLAG=""
if [[ -z "$DRY_RUN_FLAG" ]]; then
    APPLY_FLAG="--apply"
fi

TS=$(date +%Y%m%d-%H%M%S)
SNAP_LOCAL="/tmp/spine-delta-snap-${TS}.db"
SNAP_REMOTE="/tmp/spine-delta-staged-${TS}.db"

# VACUUM INTO creates a large local temporary file before the network step.
# Always remove it when the sync exits, including DNS/SSH/rsync failures.
cleanup_local_snapshot() {
    rm -f -- "$SNAP_LOCAL"
}
trap cleanup_local_snapshot EXIT

echo "[ship_spine_delta] START $(date '+%Y-%m-%d %H:%M:%S')"
echo "  laptop: $LAPTOP_DB"
echo "  mini:   ${MINI_USER}@${MINI_HOST}:${MINI_DB}"
echo "  apply:  ${APPLY_FLAG:-'(dry-run)'}"

# ── Step 1: VACUUM INTO snapshot (clean, WAL-free) ─────────────────────────
echo "[ship_spine_delta] Step 1: VACUUM INTO $SNAP_LOCAL"
if [[ ! -f "$LAPTOP_DB" ]]; then
    echo "ERROR: Laptop DB not found: $LAPTOP_DB" >&2
    exit 1
fi

# Use sqlite3 CLI — VACUUM INTO acquires a shared lock so concurrent writers are safe
/usr/bin/sqlite3 "$LAPTOP_DB" ".timeout 15000" "VACUUM INTO '${SNAP_LOCAL}'"
SNAP_SIZE=$(du -sh "$SNAP_LOCAL" | cut -f1)
echo "  snapshot: $SNAP_LOCAL ($SNAP_SIZE)"

# ── Step 2: rsync snapshot to Mini staging ─────────────────────────────────
echo "[ship_spine_delta] Step 2: rsync to Mini staging"
rsync -az --progress \
    --timeout=1800 \
    "$SNAP_LOCAL" \
    "${MINI_USER}@${MINI_HOST}:${SNAP_REMOTE}"
echo "  staged: ${MINI_HOST}:${SNAP_REMOTE}"

# ── Step 3: SSH-run spine_merge.py on Mini ─────────────────────────────────
echo "[ship_spine_delta] Step 3: running spine_merge.py on Mini"
MERGE_OUTPUT=$(ssh "${MINI_USER}@${MINI_HOST}" \
    "python3 '${MERGE_SCRIPT}' --source '${SNAP_REMOTE}' --target '${MINI_DB}' ${APPLY_FLAG}" 2>&1)
MERGE_EXIT=$?

echo "$MERGE_OUTPUT"

# ── Step 4: Evaluate result ────────────────────────────────────────────────
if [[ $MERGE_EXIT -ne 0 ]]; then
    echo ""
    echo "ERROR: spine_merge.py exited $MERGE_EXIT — merge FAILED or ABORTED" >&2
    # Still clean up staging even on failure
    ssh "${MINI_USER}@${MINI_HOST}" "rm -f '${SNAP_REMOTE}'" 2>/dev/null || true
    rm -f "$SNAP_LOCAL"
    exit $MERGE_EXIT
fi

# ── Step 5: Clean up staging ───────────────────────────────────────────────
echo "[ship_spine_delta] Step 5: cleaning staging files"
ssh "${MINI_USER}@${MINI_HOST}" "rm -f '${SNAP_REMOTE}'" 2>/dev/null || true
rm -f "$SNAP_LOCAL"

echo "[ship_spine_delta] DONE $(date '+%Y-%m-%d %H:%M:%S')"
