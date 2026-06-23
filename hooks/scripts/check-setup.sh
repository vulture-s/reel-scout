#!/usr/bin/env bash
# reel-scout SessionStart preflight: silent on success, advisory on failure.
# Never blocks the session (exit 0 always) — just surfaces a one-line hint if
# the local pipeline isn't ready. The skill's Step 0 does the real gating.
set -u

ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"

# Prefer python3, fall back to python (Windows Git Bash).
PY="python3"
command -v python3 >/dev/null 2>&1 || PY="python"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "reel-scout: python not found on PATH — install Python 3.9+ to use this skill." >&2
  exit 0
fi

"$PY" "$ROOT/scripts/setup.py" --check
code=$?

if [ "$code" -ne 0 ]; then
  echo "reel-scout: setup incomplete (exit $code). Run: $PY \"$ROOT/scripts/setup.py\" for remediation." >&2
fi

exit 0
