#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
  echo '请先执行：python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt' >&2
  exit 1
fi
if [[ ! -f config.json ]]; then
  cp -n config.example.json config.json
fi
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export SHORT_DRAMA_MULTIUSER="${SHORT_DRAMA_MULTIUSER:-0}"
export SHORT_DRAMA_PORT="${SHORT_DRAMA_PORT:-7860}"
exec .venv/bin/python -u app.py
