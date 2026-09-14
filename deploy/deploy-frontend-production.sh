#!/usr/bin/env bash

# Production wrapper for the shared frontend deployment implementation.
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

exec env \
  ENVIRONMENT=production \
  SOURCE="${SOURCE:-/home/asianode/src/asianodeagent-front}" \
  ROOT="${ROOT:-/home/asianode/asianode-production/frontend}" \
  BUILD_ENV="${BUILD_ENV:-/home/asianode/asianode-production/frontend/shared/build/frontend.build.env}" \
  PROJECT="${PROJECT:-asianode-production-frontend}" \
  BRANCH="${BRANCH:-main}" \
  "$SCRIPT_DIR/deploy-frontend.sh" "$@"
