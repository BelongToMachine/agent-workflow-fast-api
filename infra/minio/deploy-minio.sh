#!/usr/bin/env bash

# Deploy or upgrade the independent MinIO service for one environment.
#
# The script intentionally manages only the MinIO Compose project. It never
# stops the API/Redis project, deletes volumes, removes the data directory, or
# performs a global Docker cleanup.

set -Eeuo pipefail

MINIO_ROOT="${MINIO_ROOT:-/home/asianode/asianode-production}"
MINIO_PROJECT_NAME="${MINIO_PROJECT_NAME:-asianode-minio-production}"
MINIO_ENV_FILE="${MINIO_ENV_FILE:-$MINIO_ROOT/infra/minio/.env.minio}"
MINIO_COMPOSE_FILE="${MINIO_COMPOSE_FILE:-$MINIO_ROOT/infra/minio/compose.minio.yaml}"
MINIO_NETWORK="${MINIO_NETWORK:-asianode-storage}"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || die "docker is required"
[[ -f "$MINIO_ENV_FILE" ]] || die "missing MinIO environment file: $MINIO_ENV_FILE"
[[ -f "$MINIO_COMPOSE_FILE" ]] || die "missing Compose file: $MINIO_COMPOSE_FILE"

printf '%s\n' "[1/5] Checking external Docker network: $MINIO_NETWORK"
if ! docker network inspect "$MINIO_NETWORK" >/dev/null 2>&1; then
  docker network create "$MINIO_NETWORK" >/dev/null
fi

compose() {
  docker compose \
    --project-name "$MINIO_PROJECT_NAME" \
    --env-file "$MINIO_ENV_FILE" \
    -f "$MINIO_COMPOSE_FILE" \
    "$@"
}

printf '%s\n' "[2/5] Validating MinIO Compose configuration"
compose config -q

printf '%s\n' "[3/5] Resolving the pinned MinIO image"
MINIO_IMAGE="$(compose config --images | sed -n '1p')"
[[ -n "$MINIO_IMAGE" ]] || die "could not resolve MinIO image from Compose"

if docker image inspect "$MINIO_IMAGE" >/dev/null 2>&1; then
  printf '%s\n' "Using cached image: $MINIO_IMAGE"
else
  printf '%s\n' "Image is not cached; pulling: $MINIO_IMAGE"
  compose pull minio
fi

printf '%s\n' "[4/5] Starting MinIO without touching other Compose projects"
compose up -d minio

printf '%s\n' "[5/5] Waiting for the MinIO healthcheck"
container_id="$(compose ps -q minio)"
[[ -n "$container_id" ]] || die "MinIO container was not created"

for _ in {1..30}; do
  health="$(docker inspect --format '{{.State.Health.Status}}' "$container_id" 2>/dev/null || true)"
  case "$health" in
    healthy)
      printf '%s\n' "MinIO is healthy: $MINIO_PROJECT_NAME"
      exit 0
      ;;
    unhealthy)
      compose logs --tail=80 minio >&2
      die "MinIO healthcheck failed"
      ;;
  esac
  sleep 2
done

compose logs --tail=80 minio >&2
die "timed out waiting for MinIO healthcheck"
