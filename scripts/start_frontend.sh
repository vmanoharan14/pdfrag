#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../frontend"

if [[ ! -x node_modules/.bin/next ]]; then
  echo "Frontend dependencies are missing. Run ./scripts/setup_frontend.sh first."
  exit 1
fi

exec npm run dev
