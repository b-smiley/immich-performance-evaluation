#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly FIXTURE_DIR="${FIXTURE_DIR:-${ROOT_DIR}/data/fixtures}"
readonly RESULTS_DIR="${RESULTS_DIR:-${ROOT_DIR}/data/results}"

# Load local configuration when the caller did not provide the key explicitly.
# Environment variables supplied by the caller take precedence over .env.
if [[ -z "${IMMICH_API_KEY:-}" && -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
  set +a
fi

if [[ -z "${IMMICH_API_KEY:-}" ]]; then
  IMMICH_ENV_FILE="${ROOT_DIR}/.env" \
    python3 "${SCRIPT_DIR}/setup-test-user.py"
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
  set +a
fi

: "${IMMICH_API_KEY:?Ephemeral Immich API-key setup did not produce a key.}"

mkdir -p "${RESULTS_DIR}"
python3 "${SCRIPT_DIR}/generate_fixtures.py" --output "${FIXTURE_DIR}"

# Git Bash rewrites container paths unless MSYS path conversion is disabled.
MSYS_NO_PATHCONV=1 docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "${ROOT_DIR}/loadtest:/scripts:ro" \
  --volume "${FIXTURE_DIR}:/fixtures:ro" \
  --volume "${RESULTS_DIR}:/results" \
  --env "IMMICH_URL=${IMMICH_URL:-http://host.docker.internal:2283}" \
  --env "IMMICH_API_KEY=${IMMICH_API_KEY}" \
  --env "VUS=${VUS:-1}" \
  --env "DURATION=${DURATION:-30s}" \
  --env "PHOTO_RATIO=${PHOTO_RATIO:-0.5}" \
  --env "K6_PROMETHEUS_RW_SERVER_URL=${K6_PROMETHEUS_RW_SERVER_URL:-http://host.docker.internal:9090/api/v1/write}" \
  grafana/k6:0.54.0 run \
  --out json=/results/k6.json \
  --out experimental-prometheus-rw \
  /scripts/upload.js
