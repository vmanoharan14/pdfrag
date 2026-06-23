#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

export UV_CACHE_DIR="$PWD/.runtime/uv-cache"
export UV_PROJECT_ENVIRONMENT="$PWD/.runtime/venv"
uv sync --python python3

echo
echo "Backend environment is ready."
echo "Start it with ./scripts/start_backend.sh"
