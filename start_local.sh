#!/usr/bin/env bash
# Start both the Billingonaire backend and UI dev server for local development.
#
# Backend runs in the background on :8000 (TESTING=true, no Firebase creds needed).
# Frontend Vite dev server runs in the foreground on :5000.
# Ctrl-C stops both.
#
# Environment variables (all optional):
#   PYTHON_BIN  — Python interpreter (default: auto-detected from .venv)
#   BACKEND_PORT — backend port (default: 8000)
#   UI_PORT     — Vite dev port  (default: 5000, configured in vite.config.js)
#   TESTING     — "false" to use real Firebase credentials
#   RELOAD      — "false" to disable uvicorn --reload

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/billingonaire_backend"
UI_DIR="$SCRIPT_DIR/billingonaire-ui"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export TESTING="${TESTING:-true}"
export HOST="${HOST:-0.0.0.0}"
export PORT="${BACKEND_PORT:-8000}"
export RELOAD="${RELOAD:-true}"

# Locate Python.
if [ -z "${PYTHON_BIN:-}" ]; then
    for _candidate in \
        "$REPO_ROOT/.venv/bin/python" \
        "$BACKEND_DIR/venv/bin/python" \
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

# Locate npm.
if ! command -v npm &>/dev/null 2>&1; then
    echo "Error: npm not found in PATH." >&2
    exit 1
fi

cleanup() {
    echo ""
    echo "Stopping servers..."
    # Kill the background backend process group.
    if [ -n "${BACKEND_PID:-}" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        kill "$BACKEND_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

echo "============================================"
echo " Billingonaire — local dev"
echo "============================================"
echo " Backend : http://localhost:$PORT"
echo " Frontend: http://localhost:${UI_PORT:-5000}"
echo " TESTING : $TESTING"
echo "============================================"
echo ""

# Start backend in background.
echo "[backend] starting..."
"$PYTHON_BIN" "$BACKEND_DIR/dev_server.py" &
BACKEND_PID=$!

# Give uvicorn a moment to bind before printing the UI line.
sleep 2
echo "[backend] pid $BACKEND_PID — http://localhost:$PORT"
echo ""

# Start frontend in foreground (Ctrl-C here stops both via trap).
echo "[ui] starting npm run dev..."
cd "$UI_DIR"
npm run dev
