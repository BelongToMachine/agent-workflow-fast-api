#!/usr/bin/env bash

# Deploy the staging FastAPI service from the latest approved main commit.
#
# This script is intended to run as the `asianode` user on sg-vps. It builds
# from a clean source checkout on the staging VPS, keeps runtime configuration
# outside the release, and only exposes the API on the VPS loopback address.
# It never stops production, performs public-domain checks, or runs database
# migrations automatically.

set -Eeuo pipefail
umask 077

# The staging account owns a rootless Docker daemon. A non-login SSH command
# does not always inherit DOCKER_HOST, so point every Docker CLI invocation at
# the staging user's daemon explicitly.
DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"
export DOCKER_HOST

# Fixed paths and deployment settings.
SOURCE="${SOURCE:-/home/asianode/src/agent-workflow-fast-api}"
ROOT="${ROOT:-/home/asianode/asianode-staging}"
BUILD_ENV="${BUILD_ENV:-$ROOT/shared/build/build.env}"
RUNTIME_ENV="${RUNTIME_ENV:-$ROOT/shared/env/.env.staging}"

NEW_PROJECT="${NEW_PROJECT:-asianode-staging}"
COMPOSE_FILE_NAME="compose.staging.yaml"
LOCAL_HEALTH_URL="${LOCAL_HEALTH_URL:-http://127.0.0.1:18000/api/v1/healthz}"
LOCAL_READY_URL="${LOCAL_READY_URL:-http://127.0.0.1:18000/api/v1/readyz}"

# The base image is normally detected from the first FROM instruction. It can
# be overridden for a Dockerfile that uses an indirect or generated base
# image. This is checked against the same rootless Docker daemon used by
# Compose.
BASE_IMAGE="${BASE_IMAGE:-}"
BASE_IMAGE_SOURCE=""
BUILD_PULL=0

RELEASE=""
NEW_STARTED=0

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
  log "ERROR: $*" >&2
  return 1
}

# Compose wrappers keep the project name, environment file, and release
# Compose file explicit. This prevents accidental operations on other stacks.
new_compose() {
  docker compose \
    --project-name "$NEW_PROJECT" \
    --env-file "$BUILD_ENV" \
    -f "$RELEASE/$COMPOSE_FILE_NAME" \
    "$@"
}

# If anything fails after the new stack has started, stop only this staging
# stack. The release and deployment record remain available for diagnosis.
on_error() {
  local exit_code=$?

  if [[ -n "$RELEASE" && -f "$RELEASE/release-info" ]]; then
    sed -i 's/^status=.*/status=failed/' "$RELEASE/release-info" || true
  fi

  if (( NEW_STARTED == 1 )); then
    log "Deployment failed; stopping the incomplete staging stack."
    new_compose stop api redis >/dev/null 2>&1 || true
  fi

  exit "$exit_code"
}

trap on_error ERR

# The deployment user must be the owner of the rootless daemon and staging
# secrets. Run `sudo -iu asianode` first when connecting as the admin user.
[[ "$(id -un)" == "asianode" ]] || fail "Run this script as the asianode user"
[[ -d "$SOURCE/.git" ]] || fail "Git checkout not found: $SOURCE"
[[ -f "$BUILD_ENV" ]] || fail "Build environment file not found: $BUILD_ENV"
[[ -f "$RUNTIME_ENV" ]] || fail "Runtime environment file not found: $RUNTIME_ENV"
[[ -d "$ROOT/releases" ]] || fail "Staging releases directory not found: $ROOT/releases"
[[ -d "$ROOT/deploy" ]] || fail "Staging deploy directory not found: $ROOT/deploy"

# Serialize deployments without deleting or replacing any existing release.
exec 9>"$ROOT/deploy/deploy.lock"
flock -n 9 || fail "Another staging deployment is already running"

# Validate the same rootless Docker daemon that will build and run Compose.
docker info >/dev/null || fail "Cannot connect to the rootless Docker daemon at $DOCKER_HOST"
docker compose version >/dev/null || fail "Docker Compose is unavailable"

# Runtime secrets stay private to the deployment user.
chmod 0600 "$RUNTIME_ENV"

# Refuse obviously wrong staging configuration before touching containers.
grep -Eq '^ENVIRONMENT=staging$' "$RUNTIME_ENV" || fail "ENVIRONMENT is not staging"
grep -Eq '^DEBUG=false$' "$RUNTIME_ENV" || fail "DEBUG must be false in staging"
grep -Eq '^AUTH_REQUIRED=true$' "$RUNTIME_ENV" || fail "AUTH_REQUIRED must be true in staging"
grep -Eq '^AUTH_SECRET=.{32,}$' "$RUNTIME_ENV" || fail "AUTH_SECRET must be at least 32 characters"
grep -Eq '^CORS_ORIGINS=[^*]+$' "$RUNTIME_ENV" || fail "CORS_ORIGINS must contain explicit origins"

# Build configuration is separate from runtime configuration. It may contain
# public package-index settings, but it must not replace the runtime env file.
grep -Eq '^RUNTIME_ENV_FILE=' "$BUILD_ENV" || fail "RUNTIME_ENV_FILE is missing from $BUILD_ENV"
grep -Eq '^PYPI_INDEX_URL=' "$BUILD_ENV" || fail "PYPI_INDEX_URL is missing from $BUILD_ENV"
grep -Fxq "RUNTIME_ENV_FILE=$RUNTIME_ENV" "$BUILD_ENV" \
  || fail "BUILD_ENV points to a different runtime environment file"

# Update the source checkout. A dirty checkout is rejected so uncommitted
# server changes can never enter a release by accident.
cd "$SOURCE"
[[ -z "$(git status --porcelain)" ]] || fail "Source checkout is dirty: $SOURCE"

log "Fetching origin/main."
git fetch origin main
git switch main
git pull --ff-only origin main

SHA="$(git rev-parse HEAD)"
RELEASE="$ROOT/releases/$SHA"
log "Preparing staging commit $SHA."

# Require the staging Compose file to be tracked in the pulled commit. This
# makes the release self-contained and prevents a stale server-side template
# from being combined with newer application code.
git ls-files --error-unmatch "$COMPOSE_FILE_NAME" >/dev/null 2>&1 \
  || fail "Pulled commit does not contain tracked $COMPOSE_FILE_NAME"

# Create an immutable release directory. If the same commit was prepared
# before, reuse it instead of overwriting the existing release.
if [[ -e "$RELEASE" ]]; then
  [[ -f "$RELEASE/.deploy-commit" ]] \
    || fail "Existing release has no .deploy-commit: $RELEASE"
  [[ "$(<"$RELEASE/.deploy-commit")" == "$SHA" ]] \
    || fail "Existing release commit marker does not match: $RELEASE"
  [[ -f "$RELEASE/$COMPOSE_FILE_NAME" ]] \
    || fail "Existing release has no $COMPOSE_FILE_NAME: $RELEASE"
  log "Reusing prepared release $RELEASE."
else
  mkdir -m 0750 "$RELEASE"

  # Export only files committed at this SHA. This excludes .git, untracked
  # files, local build output, and server-side runtime secrets.
  git archive --format=tar "$SHA" | tar -x -C "$RELEASE"

  [[ -f "$RELEASE/Dockerfile" ]] || fail "Git release has no Dockerfile"
  [[ -f "$RELEASE/$COMPOSE_FILE_NAME" ]] \
    || fail "Git release has no $COMPOSE_FILE_NAME"

  printf '%s\n' "$SHA" > "$RELEASE/.deploy-commit"
  chmod 0640 "$RELEASE/.deploy-commit"
fi

# BuildKit does not need to contact a registry when the Dockerfile base image
# is already available in the local rootless Docker daemon. Otherwise use
# --pull as the explicit remote fallback.
if [[ -z "$BASE_IMAGE" ]]; then
  BASE_IMAGE="$(awk '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*FROM[[:space:]]+/ {
      for (i = 2; i <= NF; i++) {
        if ($i !~ /^--/) {
          print $i
          exit
        }
      }
    }
  ' "$RELEASE/Dockerfile")"
fi
[[ -n "$BASE_IMAGE" ]] || fail "Could not determine the Dockerfile base image"

if docker image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
  BASE_IMAGE_SOURCE="local"
  BUILD_PULL=0
  log "Base image $BASE_IMAGE is available locally; build will not use --pull."
else
  BASE_IMAGE_SOURCE="remote"
  BUILD_PULL=1
  log "Base image $BASE_IMAGE is not available locally; build will use --pull."
fi

# Record source, configuration, and base-image decisions. This file contains
# no runtime secret values and stays inside the immutable release.
cat > "$RELEASE/release-info" <<EOF
commit=$SHA
environment=staging
source=git
remote=origin
branch=$(git branch --show-current)
pulled_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
compose=$COMPOSE_FILE_NAME
runtime_env=$RUNTIME_ENV
build_env=$BUILD_ENV
docker_host=$DOCKER_HOST
base_image=$BASE_IMAGE
base_image_source=$BASE_IMAGE_SOURCE
build_pull=$BUILD_PULL
status=prepared-not-started
EOF
chmod 0640 "$RELEASE/release-info"

# Validate the expanded Compose configuration. This does not start or pull
# services.
log "Validating staging Compose configuration."
new_compose config -q

# Build the API image while no staging application is serving traffic.
log "Building the staging API image from release $SHA."
if (( BUILD_PULL == 1 )); then
  new_compose build --pull api
else
  new_compose build api
fi

# Staging has no old project to stop and no public cutover. Redis is started
# before the API, then the API is started without recreating its dependency.
# Set the cleanup flag before the first `up` so a partially created stack is
# stopped if Compose fails midway through startup.
NEW_STARTED=1
log "Starting the staging Redis."
new_compose up -d redis

log "Starting the staging API."
new_compose up -d --no-deps api

# Wait for the container healthcheck before checking the local liveness and
# readiness endpoints. Readiness is expected to fail until migrations exist.
API_CONTAINER=""
for _ in $(seq 1 30); do
  API_CONTAINER="$(new_compose ps -q api)"
  [[ -n "$API_CONTAINER" ]] && break
  sleep 2
done
[[ -n "$API_CONTAINER" ]] || fail "Staging API container was not created"

for _ in $(seq 1 60); do
  HEALTH="$(docker inspect --format '{{.State.Health.Status}}' "$API_CONTAINER" 2>/dev/null || true)"
  case "$HEALTH" in
    healthy)
      break
      ;;
    unhealthy)
      new_compose logs --tail=100 api >&2 || true
      fail "Staging API container became unhealthy"
      ;;
  esac
  sleep 2
done

[[ "$(docker inspect --format '{{.State.Health.Status}}' "$API_CONTAINER")" == "healthy" ]] || {
  new_compose logs --tail=100 api >&2 || true
  fail "Timed out waiting for the staging API healthcheck"
}

for URL in "$LOCAL_HEALTH_URL" "$LOCAL_READY_URL"; do
  log "Checking $URL."
  curl --fail --silent --show-error --max-time 10 "$URL" >/dev/null
done

# Only after all local checks pass, mark this release successful and update the
# current symlink. No public mapping is changed by this script.
ln -sfn "$RELEASE" "$ROOT/current"
sed -i 's/^status=.*/status=successful/' "$RELEASE/release-info"
printf 'deployed_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$RELEASE/release-info"

log "Staging deployment succeeded: $SHA"
log "Current release: $ROOT/current"
