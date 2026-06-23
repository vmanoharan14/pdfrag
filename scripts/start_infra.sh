#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example."
  echo "Update the local passwords in .env, then run this command again."
  exit 1
fi

docker compose --env-file .env up -d

echo
echo "Infrastructure is starting. Run ./scripts/infra_status.sh to verify health."

