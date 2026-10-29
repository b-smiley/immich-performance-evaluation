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

readonly IMMICH_URL="${IMMICH_URL:-http://host.docker.internal:2283}"
readonly VUS="${VUS:-1}"
readonly DURATION="${DURATION:-30s}"
readonly PHOTO_RATIO="${PHOTO_RATIO:-0.5}"
readonly SIZE_LEVEL="${SIZE_LEVEL:-small}"
readonly RESOLUTION="${RESOLUTION:-1080p}"
readonly ITERATIONS="${ITERATIONS:-}"
readonly FIXTURE_KINDS="$(awk -v ratio="${PHOTO_RATIO}" \
  'BEGIN { print (ratio <= 0) ? "video" : (ratio >= 1) ? "photo" : "both" }')"

mkdir -p "${RESULTS_DIR}"
python3 "${SCRIPT_DIR}/generate_fixtures.py" \
  --output "${FIXTURE_DIR}" \
  --size-level "${SIZE_LEVEL}" \
  --resolution "${RESOLUTION}" \
  --kinds "${FIXTURE_KINDS}" \
  --seed "${FIXTURE_SEED:-533}" \
  ${POOL_SIZE:+--pool-size "${POOL_SIZE}"}

python3 "${SCRIPT_DIR}/preflight.py" memory \
  --manifest "${FIXTURE_DIR}/manifest.json" \
  --vus "${VUS}" \
  ${K6_MEMORY_BUDGET_BYTES:+--budget "${K6_MEMORY_BUDGET_BYTES}"}

# The server disk can only be checked when Immich runs on this machine.
case "${IMMICH_URL}" in
  *://localhost[:/]* | *://127.0.0.1[:/]* | *://host.docker.internal[:/]*)
    upload_path="${UPLOAD_LOCATION:-./data/upload}"
    [[ "${upload_path}" == /* ]] || upload_path="${ROOT_DIR}/${upload_path}"
    python3 "${SCRIPT_DIR}/preflight.py" disk \
      --manifest "${FIXTURE_DIR}/manifest.json" \
      --path "${upload_path}" \
      --vus "${VUS}" \
      --duration "${DURATION}" \
      --iterations "${ITERATIONS:-0}" \
      --photo-ratio "${PHOTO_RATIO}" \
      --upload-mbps "${UPLOAD_MBPS:-1000}"
    ;;
esac

# Git Bash rewrites container paths unless MSYS path conversion is disabled.
MSYS_NO_PATHCONV=1 docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "${ROOT_DIR}/loadtest:/scripts:ro" \
  --volume "${FIXTURE_DIR}:/fixtures:ro" \
  --volume "${RESULTS_DIR}:/results" \
  --env "IMMICH_URL=${IMMICH_URL}" \
  --env "IMMICH_API_KEY=${IMMICH_API_KEY}" \
  --env "VUS=${VUS}" \
  --env "DURATION=${DURATION}" \
  --env "PHOTO_RATIO=${PHOTO_RATIO}" \
  --env "ITERATIONS=${ITERATIONS}" \
  --env "UPLOAD_TIMEOUT=${UPLOAD_TIMEOUT:-10m}" \
  --env "K6_PROMETHEUS_RW_SERVER_URL=${K6_PROMETHEUS_RW_SERVER_URL:-http://host.docker.internal:9090/api/v1/write}" \
  grafana/k6:0.54.0 run \
  --out json=/results/k6.json \
  --out experimental-prometheus-rw \
  /scripts/upload.js
