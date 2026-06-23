#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ ! -x .runtime/venv/bin/alembic ]]; then
  echo "Backend environment is missing. Run ./scripts/setup_backend.sh first."
  exit 1
fi

exec .runtime/venv/bin/alembic upgrade head
