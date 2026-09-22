#!/usr/bin/env bash

# Staging wrapper for the shared frontend deployment implementation.
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

exec env \
  ENVIRONMENT=staging \
  SOURCE="${SOURCE:-/home/asianode/src/asianodeagent-front}" \
  ROOT="${ROOT:-/home/asianode/asianode-staging/frontend}" \
  BUILD_ENV="${BUILD_ENV:-/home/asianode/asianode-staging/frontend/shared/build/frontend.build.env}" \
  PROJECT="${PROJECT:-asianode-staging-frontend}" \
  BRANCH="${BRANCH:-staging}" \
  "$SCRIPT_DIR/deploy-frontend.sh" "$@"
