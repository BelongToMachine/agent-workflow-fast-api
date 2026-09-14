#!/usr/bin/env bash

# Deploy the Vite frontend from a clean Git release on the target VPS.
#
# The script is shared by staging and production wrappers. It builds the SPA
# on the target VPS, serves the immutable dist output with Nginx, keeps public
# build variables outside the release, and never touches the FastAPI stack.

set -Eeuo pipefail
umask 077

# Both VPS instances use rootless Docker. An SSH command may not inherit the
# user's Docker socket, so set it explicitly for every Compose invocation.
DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"
export DOCKER_HOST

ENVIRONMENT="${ENVIRONMENT:?ENVIRONMENT must be staging or production}"
case "$ENVIRONMENT" in
  staging|production) ;;
  *) printf 'ERROR: unsupported ENVIRONMENT: %s\n' "$ENVIRONMENT" >&2; exit 1 ;;
esac

# Source and release paths are intentionally separate. The source checkout is
# only used to prepare a release and is never mounted into the running Nginx.
SOURCE="${SOURCE:-/home/asianode/src/asianodeagent-front}"
ROOT="${ROOT:-/home/asianode/asianode-${ENVIRONMENT}/frontend}"
BUILD_ENV="${BUILD_ENV:-$ROOT/shared/build/frontend.build.env}"
PROJECT="${PROJECT:-asianode-${ENVIRONMENT}-frontend}"
BRANCH="${BRANCH:-main}"
COMPOSE_FILE_NAME="compose.${ENVIRONMENT}.yaml"

RELEASE=""
NEW_STARTED=0
BASE_IMAGES=()
BASE_IMAGE_SOURCE=""
BUILD_PULL=0

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
  log "ERROR: $*" >&2
  return 1
}

new_compose() {
  docker compose \
    --project-name "$PROJECT" \
    --env-file "$BUILD_ENV" \
    -f "$RELEASE/$COMPOSE_FILE_NAME" \
    "$@"
}

on_error() {
  local exit_code=$?

  if [[ -n "$RELEASE" && -f "$RELEASE/release-info" ]]; then
    sed -i 's/^status=.*/status=failed/' "$RELEASE/release-info" || true
  fi

  if (( NEW_STARTED == 1 )); then
    log "Deployment failed; stopping only the incomplete ${ENVIRONMENT} frontend."
    new_compose stop frontend >/dev/null 2>&1 || true
  fi

  exit "$exit_code"
}

trap on_error ERR

[[ "$(id -un)" == "asianode" ]] || fail "Run this script as the asianode user"
[[ -d "$SOURCE/.git" ]] || fail "Git checkout not found: $SOURCE"
[[ -f "$BUILD_ENV" ]] || fail "Frontend build environment file not found: $BUILD_ENV"

# Frontend configuration is build-time and public. It is deliberately not a
# runtime env_file because the Nginx container has no application secrets.
grep -Fxq "FRONTEND_ENVIRONMENT=$ENVIRONMENT" "$BUILD_ENV" \
  || fail "FRONTEND_ENVIRONMENT does not match $ENVIRONMENT"
grep -Eq '^FRONTEND_API_URL=https?://[^[:space:]]+$' "$BUILD_ENV" \
  || fail "FRONTEND_API_URL must be an HTTPS or HTTP URL"
grep -Eq '^VITE_WORKSPACE_ID=[0-9a-fA-F-]{36}$' "$BUILD_ENV" \
  || fail "VITE_WORKSPACE_ID is missing or invalid"
grep -Eq '^VITE_SINGLE_WORKSPACE_MODE=(true|false)$' "$BUILD_ENV" \
  || fail "VITE_SINGLE_WORKSPACE_MODE must be true or false"

mkdir -p "$ROOT/releases" "$ROOT/deploy" "$ROOT/shared/build"
chmod 0750 "$ROOT" "$ROOT/releases" "$ROOT/deploy" "$ROOT/shared" "$ROOT/shared/build"

# Serialize deployments without deleting or replacing an existing release.
exec 9>"$ROOT/deploy/deploy.lock"
flock -n 9 || fail "Another ${ENVIRONMENT} frontend deployment is already running"

docker info >/dev/null || fail "Cannot connect to the rootless Docker daemon at $DOCKER_HOST"
docker compose version >/dev/null || fail "Docker Compose is unavailable"

cd "$SOURCE"
[[ -z "$(git status --porcelain)" ]] || fail "Source checkout is dirty: $SOURCE"

log "Fetching origin/$BRANCH."
git fetch origin "$BRANCH"
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git switch "$BRANCH"
else
  git switch --track -c "$BRANCH" "origin/$BRANCH"
fi
git pull --ff-only origin "$BRANCH"

SHA="$(git rev-parse HEAD)"
RELEASE="$ROOT/releases/$SHA"
export RELEASE
log "Preparing ${ENVIRONMENT} frontend commit $SHA."

git ls-files --error-unmatch "$COMPOSE_FILE_NAME" >/dev/null 2>&1 \
  || fail "Pulled commit does not contain tracked $COMPOSE_FILE_NAME"
git ls-files --error-unmatch Dockerfile >/dev/null 2>&1 \
  || fail "Pulled commit does not contain tracked Dockerfile"
git ls-files --error-unmatch deploy/nginx.conf >/dev/null 2>&1 \
  || fail "Pulled commit does not contain tracked deploy/nginx.conf"

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

  # Export only files committed at this SHA. This excludes .git, local build
  # output, untracked files, and server-side build configuration.
  git archive --format=tar "$SHA" | tar -x -C "$RELEASE"

  [[ -f "$RELEASE/Dockerfile" ]] || fail "Git release has no Dockerfile"
  [[ -f "$RELEASE/$COMPOSE_FILE_NAME" ]] \
    || fail "Git release has no $COMPOSE_FILE_NAME"
  [[ -f "$RELEASE/deploy/nginx.conf" ]] \
    || fail "Git release has no deploy/nginx.conf"

  printf '%s\n' "$SHA" > "$RELEASE/.deploy-commit"
  chmod 0640 "$RELEASE/.deploy-commit"
fi

# The frontend Dockerfile has two base images. Use --pull only when at least
# one is absent from the same rootless Docker daemon that Compose will use.
while IFS= read -r image; do
  [[ -n "$image" ]] && BASE_IMAGES+=("$image")
done < <(awk '
  /^[[:space:]]*#/ { next }
  /^[[:space:]]*FROM[[:space:]]+/ {
    for (i = 2; i <= NF; i++) {
      if ($i !~ /^--/) {
        print $i
        break
      }
    }
  }
' "$RELEASE/Dockerfile" | sort -u)
[[ "${#BASE_IMAGES[@]}" -gt 0 ]] || fail "Could not determine Dockerfile base images"

for image in "${BASE_IMAGES[@]}"; do
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    BUILD_PULL=1
    break
  fi
done
if (( BUILD_PULL == 1 )); then
  BASE_IMAGE_SOURCE="remote"
  log "At least one base image is missing locally; build will use --pull."
else
  BASE_IMAGE_SOURCE="local"
  log "All frontend base images are available locally; build will not use --pull."
fi

cat > "$RELEASE/release-info" <<EOF
commit=$SHA
environment=$ENVIRONMENT
component=frontend
source=git
remote=origin
branch=$(git branch --show-current)
pulled_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
compose=$COMPOSE_FILE_NAME
build_env=$BUILD_ENV
docker_host=$DOCKER_HOST
base_images=$(IFS=,; printf '%s' "${BASE_IMAGES[*]}")
base_image_source=$BASE_IMAGE_SOURCE
build_pull=$BUILD_PULL
status=prepared-not-started
EOF
chmod 0640 "$RELEASE/release-info"

log "Validating ${ENVIRONMENT} frontend Compose configuration."
new_compose config -q

log "Building the ${ENVIRONMENT} frontend image from release $SHA."
if (( BUILD_PULL == 1 )); then
  new_compose build --pull frontend
else
  new_compose build frontend
fi

NEW_STARTED=1
log "Starting the ${ENVIRONMENT} frontend."
new_compose up -d frontend

FRONTEND_CONTAINER=""
for _ in $(seq 1 30); do
  FRONTEND_CONTAINER="$(new_compose ps -q frontend)"
  [[ -n "$FRONTEND_CONTAINER" ]] && break
  sleep 2
done
[[ -n "$FRONTEND_CONTAINER" ]] || fail "Frontend container was not created"

for _ in $(seq 1 30); do
  HEALTH="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$FRONTEND_CONTAINER" 2>/dev/null || true)"
  case "$HEALTH" in
    healthy) break ;;
    unhealthy)
      new_compose logs --tail=100 frontend >&2 || true
      fail "Frontend container became unhealthy"
      ;;
  esac
  sleep 2
done

[[ "$(docker inspect --format '{{.State.Health.Status}}' "$FRONTEND_CONTAINER")" == "healthy" ]] || {
  new_compose logs --tail=100 frontend >&2 || true
  fail "Timed out waiting for the frontend healthcheck"
}

if [[ -z "${LOCAL_HEALTH_URL:-}" ]]; then
  PUBLISHED_PORT="$(new_compose port frontend 8080 | tail -n 1)"
  [[ -n "$PUBLISHED_PORT" ]] || fail "Could not resolve the published frontend port"
  LOCAL_HEALTH_URL="http://127.0.0.1:${PUBLISHED_PORT##*:}/healthz"
fi
log "Checking $LOCAL_HEALTH_URL."
curl --fail --silent --show-error --max-time 10 "$LOCAL_HEALTH_URL" >/dev/null

ln -sfn "$RELEASE" "$ROOT/current"
sed -i 's/^status=.*/status=successful/' "$RELEASE/release-info"
sed -i '/^deployed_at=/d' "$RELEASE/release-info"
printf 'deployed_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$RELEASE/release-info"

log "${ENVIRONMENT} frontend deployment succeeded: $SHA"
log "Current frontend release: $ROOT/current"
