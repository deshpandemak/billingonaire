#!/bin/bash
# Linting hook: runs black (CI version), isort, and flake8 on billingonaire_backend/.
# Called by the Stop hook in settings.json after every Claude turn.
# black version matches CI (black==23.12.1 in .github/workflows/ci.yml).

set -euo pipefail

cd "$(dirname "$0")/../billingonaire_backend"

BLACK=/tmp/black-ci-venv/bin/black
ISORT=isort
FLAKE8=/root/.local/bin/flake8

fmt_msg=""

# Auto-format with black (CI-pinned version)
if [ -x "$BLACK" ]; then
    black_out=$("$BLACK" . 2>&1)
    reformatted=$(echo "$black_out" | grep "reformatted" || true)
    [ -n "$reformatted" ] && fmt_msg+="black: $reformatted"$'\n'
fi

# Auto-sort imports with isort
if command -v "$ISORT" &>/dev/null; then
    isort_out=$("$ISORT" . 2>&1)
    isort_fixed=$(echo "$isort_out" | grep -v "^$" | grep -v "Skipped" || true)
    [ -n "$isort_fixed" ] && fmt_msg+="isort: $isort_fixed"$'\n'
fi

# Flake8 lint check (report only — cannot auto-fix)
flake8_out=""
if [ -x "$FLAKE8" ]; then
    flake8_out=$("$FLAKE8" . 2>&1 | head -40 || true)
fi

# Build the systemMessage shown in the Claude Code UI
if [ -n "$flake8_out" ]; then
    if [ -n "$fmt_msg" ]; then
        msg="$(printf '🔧 Auto-formatted:\n%s\n⚠️  Flake8 issues (fix before pushing):\n%s' "$fmt_msg" "$flake8_out")"
    else
        msg="$(printf '⚠️  Flake8 issues (fix before pushing):\n%s' "$flake8_out")"
    fi
elif [ -n "$fmt_msg" ]; then
    msg="$(printf '🔧 Auto-formatted (commit the changes):\n%s\n✅ Flake8 clean' "$fmt_msg")"
else
    msg="✅ black, isort, flake8: all clean"
fi

echo "{}" | jq --arg m "$msg" '{systemMessage: $m}'
