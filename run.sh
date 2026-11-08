#!/usr/bin/env bash
# One-command launcher for macOS / Linux: creates a virtual environment on first run,
# installs the requirements, then starts the helper. Extra arguments are passed on:
#   ./run.sh --comment "Great teaching" --chrome-version 138
set -e
cd "$(dirname "$0")"

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PY="$c"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.9 or newer was not found. Install it from https://www.python.org/downloads/" >&2
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating virtual environment..."
  "$PY" -m venv .venv
fi

echo "Installing requirements (first run only takes a minute)..."
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt

exec .venv/bin/python main.py "$@"
