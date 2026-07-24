#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

PYTHONDONTWRITEBYTECODE=1 python3 -W error::ResourceWarning -m unittest -v companion.test_runtime
python3 -m compileall -q companion
if command -v ruff >/dev/null 2>&1; then
  ruff check companion
else
  uvx ruff check companion
fi
if command -v pip-audit >/dev/null 2>&1; then
  pip-audit --strict -r companion/requirements.txt
else
  uvx pip-audit --strict -r companion/requirements.txt
fi
bash -n start.sh
git diff --check
