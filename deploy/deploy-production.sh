#!/usr/bin/env bash

# Deploy the production FastAPI service from the latest approved main commit.
#
# This script is intended to run as the `asianode` user on the production VPS.
# It keeps the old `asianode-preview` containers for rollback and never runs a
# global `docker compose down`, `docker system prune`, or database migration.

set -Eeuo pipefail
umask 077

# Fixed paths and deployment settings.
SOURCE="${SOURCE:-/home/asianode/src/agent-workflow-fast-api}"
ROOT="${ROOT:-/home/asianode/asianode-production}"
BUILD_ENV="${BUILD_ENV:-$ROOT/shared/build/build.env}"
RUNTIME_ENV="${RUNTIME_ENV:-$ROOT/shared/env/.env.production}"

NEW_PROJECT="${NEW_PROJECT:-asianode-production}"
OLD_PROJECT="${OLD_PROJECT:-asianode-preview}"
OLD_COMPOSE="${OLD_COMPOSE:-/home/asianode/asianode-preview/app/compose.preview.yaml}"

# The production Compose file is expected to be committed to the source
# repository. A temporary server-side fallback is kept only for the current
# transition period; it is used only when the pulled commit does not contain
# compose.production.yaml.
COMPOSE_TEMPLATE="${COMPOSE_TEMPLATE:-$ROOT/deploy/compose.production.yaml}"

PUBLIC_HEALTH_URL="${PUBLIC_HEALTH_URL:-https://api.asianodeatlas.com/api/v1/healthz}"
LOCAL_HEALTH_URL="${LOCAL_HEALTH_URL:-http://127.0.0.1:18000/api/v1/healthz}"
LOCAL_READY_URL="${LOCAL_READY_URL:-http://127.0.0.1:18000/api/v1/readyz}"

RELEASE=""
OLD_STOPPED=0

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
  log "ERROR: $*" >&2
  return 1
}

# Compose wrappers keep project names explicit and prevent accidental
# operations on unrelated Compose applications.
new_compose() {
  docker compose \
    --project-name "$NEW_PROJECT" \
    --env-file "$BUILD_ENV" \
    -f "$RELEASE/compose.production.yaml" \
    "$@"
}

old_compose() {
  docker compose \
    --project-name "$OLD_PROJECT" \
    -f "$OLD_COMPOSE" \
    "$@"
}

# If anything fails after the old service has been stopped, stop the new
# project and start the old containers again. The old containers are stopped,
# not removed, so their metadata and volumes remain available for rollback.
on_error() {
  local exit_code=$?

  if [[ -n "$RELEASE" && -f "$RELEASE/release-info" ]]; then
    sed -i 's/^status=.*/status=failed/' "$RELEASE/release-info" || true
  fi

  if (( OLD_STOPPED == 1 )); then
    log "Deployment failed; restoring the old asianode-preview service."
    new_compose stop api redis >/dev/null 2>&1 || true
    old_compose start api redis || true
    log "Rollback attempt finished. Check the old service manually."
  fi

  exit "$exit_code"
}

trap on_error ERR

# Validate inputs without printing any secret values.
[[ -d "$SOURCE/.git" ]] || fail "Git checkout not found: $SOURCE"
[[ -f "$BUILD_ENV" ]] || fail "Build environment file not found: $BUILD_ENV"
[[ -f "$RUNTIME_ENV" ]] || fail "Runtime environment file not found: $RUNTIME_ENV"
[[ -f "$OLD_COMPOSE" ]] || fail "Legacy Compose file not found: $OLD_COMPOSE"

# Runtime secrets must stay private to the deployment user.
chmod 0600 "$RUNTIME_ENV"

# Refuse obviously wrong environment configuration before touching containers.
grep -Eq '^ENVIRONMENT=production$' "$RUNTIME_ENV" || fail "ENVIRONMENT is not production"
grep -Eq '^DEBUG=false$' "$RUNTIME_ENV" || fail "DEBUG must be false in production"
grep -Eq '^AUTH_REQUIRED=true$' "$RUNTIME_ENV" || fail "AUTH_REQUIRED must be true in production"
if grep -Eq '^CORS_ORIGINS=.*(localhost|127\.0\.0\.1)' "$RUNTIME_ENV"; then
  fail "CORS_ORIGINS still contains a local development origin"
fi

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
log "Preparing commit $SHA."

# Check whether the pulled commit contains the production Compose file. Once
# this becomes true on origin/main, every new release will receive the exact
# Compose file from git archive and the server-side fallback will be unused.
if git ls-files --error-unmatch compose.production.yaml >/dev/null 2>&1; then
  COMPOSE_FROM_GIT=1
else
  COMPOSE_FROM_GIT=0
  [[ -f "$COMPOSE_TEMPLATE" ]] || fail "Pulled commit has no compose.production.yaml and fallback template is missing: $COMPOSE_TEMPLATE"
  log "WARNING: compose.production.yaml is not in the pulled commit; using the temporary server-side template."
fi

# Create an immutable release directory. If the same commit was prepared
# before, reuse it instead of overwriting an existing release.
if [[ -e "$RELEASE" ]]; then
  [[ -f "$RELEASE/.deploy-commit" ]] || fail "Existing release has no .deploy-commit: $RELEASE"
  [[ "$(<"$RELEASE/.deploy-commit")" == "$SHA" ]] || fail "Existing release commit marker does not match: $RELEASE"
  [[ -f "$RELEASE/compose.production.yaml" ]] || fail "Existing release has no compose.production.yaml: $RELEASE"
  log "Reusing prepared release $RELEASE."
else
  mkdir -m 0750 "$RELEASE"

  # Export only files committed at this SHA. This excludes .git, untracked
  # files, local build output, and server-side runtime secrets.
  git archive --format=tar "$SHA" | tar -x -C "$RELEASE"

  # Normally git archive supplies compose.production.yaml. The fallback is
  # only for commits from before that file was added to origin/main.
  if [[ ! -f "$RELEASE/compose.production.yaml" ]]; then
    (( COMPOSE_FROM_GIT == 0 )) || fail "Git release does not contain compose.production.yaml: $RELEASE"
    install -m 0640 "$COMPOSE_TEMPLATE" "$RELEASE/compose.production.yaml"
  fi

  printf '%s\n' "$SHA" > "$RELEASE/.deploy-commit"
  chmod 0640 "$RELEASE/.deploy-commit"
fi

# Record the source and configuration used for this release. This file has no
# secret values and can be inspected during incident response.
cat > "$RELEASE/release-info" <<EOF
commit=$SHA
source=git
remote=$(git -C "$SOURCE" remote get-url origin)
branch=$(git -C "$SOURCE" branch --show-current)
pulled_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
compose=compose.production.yaml
runtime_env=$RUNTIME_ENV
build_env=$BUILD_ENV
status=prepared-not-started
EOF
chmod 0640 "$RELEASE/release-info"

# Validate the expanded Compose configuration. This does not start, stop, or
# recreate containers.
log "Validating production Compose configuration."
new_compose config -q

# Build the API image while the old production service is still serving.
# --pull refreshes the base image and does not affect running containers.
log "Building the API image from release $SHA."
new_compose build --pull api

# Intentional cutover point: both stacks use host port 18000, so a short outage
# is expected. Stop only the old Asianode project.
log "Stopping the old asianode-preview API and Redis."
old_compose stop api redis
OLD_STOPPED=1

# Start the new Redis and API containers.
log "Starting the new production Redis."
new_compose up -d redis

log "Starting the new production API."
new_compose up -d --no-deps api

# Wait for the container healthcheck, then exercise local liveness/readiness
# and the public Cloudflare Tunnel endpoint. No application data is created.
API_CONTAINER=""
for _ in $(seq 1 30); do
  API_CONTAINER="$(new_compose ps -q api)"
  [[ -n "$API_CONTAINER" ]] && break
  sleep 2
done
[[ -n "$API_CONTAINER" ]] || fail "New API container was not created"

for _ in $(seq 1 60); do
  HEALTH="$(docker inspect --format '{{.State.Health.Status}}' "$API_CONTAINER" 2>/dev/null || true)"
  case "$HEALTH" in
    healthy)
      break
      ;;
    unhealthy)
      new_compose logs --tail=100 api >&2 || true
      fail "New API container became unhealthy"
      ;;
  esac
  sleep 2
done

[[ "$(docker inspect --format '{{.State.Health.Status}}' "$API_CONTAINER")" == "healthy" ]] || {
  new_compose logs --tail=100 api >&2 || true
  fail "Timed out waiting for the new API healthcheck"
}

for URL in "$LOCAL_HEALTH_URL" "$LOCAL_READY_URL" "$PUBLIC_HEALTH_URL"; do
  log "Checking $URL."
  curl --fail --silent --show-error --max-time 10 "$URL" >/dev/null
done

# Only after all checks pass, mark this release successful and update the
# current symlink. The old containers remain stopped but recoverable.
ln -sfn "$RELEASE" "$ROOT/current"
sed -i 's/^status=.*/status=successful/' "$RELEASE/release-info"
printf 'deployed_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$RELEASE/release-info"

log "Production deployment succeeded: $SHA"
log "Current release: $ROOT/current"
log "The old asianode-preview containers remain stopped for rollback."
