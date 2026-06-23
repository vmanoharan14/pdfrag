#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ ! -x .runtime/venv/bin/uvicorn ]]; then
  echo "Backend environment is missing. Run ./scripts/setup_backend.sh first."
  exit 1
fi

set -a
source .env
set +a

exec .runtime/venv/bin/uvicorn \
  app.main:app \
  --app-dir backend \
  --host 127.0.0.1 \
  --port "${BACKEND_PORT:-18000}" \
  --reload-dir backend \
  --reload
