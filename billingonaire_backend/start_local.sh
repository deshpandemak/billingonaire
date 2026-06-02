#!/usr/bin/env bash
# Start the Billingonaire backend in local dev mode (no Firebase credentials needed).
#
# Environment variables (all optional):
#   PYTHON_BIN  — path to Python interpreter (default: auto-detected from .venv)
#   HOST        — bind address (default: 0.0.0.0)
#   PORT        — bind port (default: 8000)
#   TESTING     — set to "false" if you have real Firebase credentials configured
#   RELOAD      — set to "false" to disable uvicorn --reload

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Locate Python: prefer repo-root .venv, then fallback to system python3/python.
if [ -z "${PYTHON_BIN:-}" ]; then
    for _candidate in \
        "$REPO_ROOT/.venv/bin/python" \
        "$SCRIPT_DIR/venv/bin/python" \
        "python3" \
        "python"; do
        if [ -x "$_candidate" ] || command -v "$_candidate" &>/dev/null 2>&1; then
            PYTHON_BIN="$_candidate"
            break
        fi
    done
fi

if [ -z "${PYTHON_BIN:-}" ]; then
    echo "Error: no Python interpreter found. Set PYTHON_BIN or activate a venv." >&2
    exit 1
fi

export TESTING="${TESTING:-true}"
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8000}"
export RELOAD="${RELOAD:-true}"

echo "Starting Billingonaire backend (local dev)"
echo "  python : $PYTHON_BIN"
echo "  address: $HOST:$PORT"
echo "  TESTING: $TESTING"
echo "  reload : $RELOAD"
echo ""

exec "$PYTHON_BIN" "$SCRIPT_DIR/dev_server.py"
