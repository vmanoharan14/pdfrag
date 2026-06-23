#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ ! -x .runtime/venv/bin/dramatiq ]]; then
  echo "Backend environment is missing. Run ./scripts/setup_backend.sh first."
  exit 1
fi

export PYTHONPATH="$PWD/backend"
exec .runtime/venv/bin/dramatiq \
  app.parsing \
  --queues ingestion \
  --processes 1 \
  --threads 1 \
  --watch backend/app
