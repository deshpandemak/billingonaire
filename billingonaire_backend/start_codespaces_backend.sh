#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$REPO_ROOT/.venv/bin/python}"
FIREBASE_KEY_PATH="${FIREBASE_KEY_PATH:-$REPO_ROOT/secrets/firebase-service-account.json}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
RELOAD_FLAG="${RELOAD_FLAG:---reload}"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Error: Python interpreter not found at $PYTHON_BIN" >&2
  exit 1
fi

if [ ! -f "$FIREBASE_KEY_PATH" ]; then
  echo "Error: Firebase service account JSON not found at $FIREBASE_KEY_PATH" >&2
  echo "Set FIREBASE_KEY_PATH to a valid JSON key file and retry." >&2
  exit 1
fi

export GCLOUD_SERVICE_ACCOUNT_KEY="$(cat "$FIREBASE_KEY_PATH")"

echo "Starting Billingonaire backend"
echo "  repo: $REPO_ROOT"
echo "  python: $PYTHON_BIN"
echo "  firebase key: $FIREBASE_KEY_PATH"
echo "  host: $HOST"
echo "  port: $PORT"

cd "$SCRIPT_DIR"
exec "$PYTHON_BIN" -m uvicorn main:app --host "$HOST" --port "$PORT" "$RELOAD_FLAG"