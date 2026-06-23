#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

set -a
source .env
set +a

failed=0

check() {
  local service="$1"
  shift

  if "$@" >/dev/null 2>&1; then
    printf "%-12s healthy\n" "$service"
  else
    printf "%-12s unavailable\n" "$service"
    failed=1
  fi
}

check "PostgreSQL" \
  docker compose --env-file .env exec -T postgres \
  pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"

check "Redis" \
  docker compose --env-file .env exec -T redis \
  redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping

check "Qdrant" \
  curl --fail --silent \
  --header "api-key: $QDRANT_API_KEY" \
  "http://127.0.0.1:${QDRANT_HTTP_PORT}/collections"

check "MinIO API" \
  curl --fail --silent \
  "http://127.0.0.1:${MINIO_API_PORT}/minio/health/live"

if ((failed)); then
  echo
  echo "One or more services are not ready. Wait a few seconds and retry."
  exit 1
fi

echo
echo "All infrastructure services are healthy."
echo "MinIO console: http://127.0.0.1:${MINIO_CONSOLE_PORT}"
