#!/usr/bin/env bash

# Export only the files needed to build and run the FastAPI service.
# Keep this allowlist aligned with Dockerfile and the production/staging
# Compose manifests so frontend history and assets never enter API releases.

set -Eeuo pipefail

if [[ "$#" -ne 3 ]]; then
  printf 'Usage: %s <source-checkout> <commit> <release-directory>\n' "$0" >&2
  exit 64
fi

SOURCE="$1"
COMMIT="$2"
RELEASE="$3"

[[ -d "$SOURCE/.git" ]] || {
  printf 'Git checkout not found: %s\n' "$SOURCE" >&2
  exit 1
}
[[ -d "$RELEASE" ]] || {
  printf 'Release directory not found: %s\n' "$RELEASE" >&2
  exit 1
}

git -C "$SOURCE" archive --format=tar "$COMMIT" \
  .dockerignore \
  Dockerfile \
  README.md \
  app \
  compose.production.yaml \
  compose.staging.yaml \
  pyproject.toml \
  uv.lock \
  | tar -x -C "$RELEASE"
