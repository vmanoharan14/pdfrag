#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../frontend"
npm install

echo
echo "Frontend dependencies are ready."
echo "Start it with ./scripts/start_frontend.sh"
