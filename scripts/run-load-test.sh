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
readonly CONCURRENT_UPLOADS="${CONCURRENT_UPLOADS:-1}"
readonly USERS="${USERS:-1}"
readonly THINK_TIME_SECONDS="${THINK_TIME_SECONDS:-0}"
readonly DURATION="${DURATION:-30s}"
readonly PHOTO_RATIO="${PHOTO_RATIO:-0.5}"
readonly SIZE_LEVEL="${SIZE_LEVEL:-small}"
readonly RESOLUTION="${RESOLUTION:-1080p}"
readonly ITERATIONS="${ITERATIONS:-}"
readonly FIXTURE_KINDS="$(awk -v ratio="${PHOTO_RATIO}" \
  'BEGIN { print (ratio <= 0) ? "video" : (ratio >= 1) ? "photo" : "both" }')"

[[ "${USERS}" =~ ^[1-9][0-9]*$ ]] ||
  { printf 'Error: USERS must be a positive whole number, got %s.\n' "${USERS}" >&2; exit 2; }

# Each account needs its own key. The keys stay out of RESULTS_DIR, which is
# uploaded as an artifact.
immich_api_keys=""
if (( USERS > 1 )); then
  keys_file="$(mktemp)"
  env USERS="${USERS}" IMMICH_API_KEYS_FILE="${keys_file}" \
    IMMICH_URL="${IMMICH_URL/host.docker.internal/localhost}" \
    python3 "${SCRIPT_DIR}/setup-test-user.py" ||
    { rm -f "${keys_file}"; exit 1; }
  immich_api_keys="$(cat "${keys_file}")"
  rm -f "${keys_file}"
fi

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
  --vus "${CONCURRENT_UPLOADS}" \
  ${K6_MEMORY_BUDGET_BYTES:+--budget "${K6_MEMORY_BUDGET_BYTES}"}

# The server disk can only be checked when Immich runs on this machine.
case "${IMMICH_URL}" in
  *://localhost[:/]* | *://127.0.0.1[:/]* | *://host.docker.internal[:/]*)
    upload_path="${UPLOAD_LOCATION:-./data/upload}"
    [[ "${upload_path}" == /* ]] || upload_path="${ROOT_DIR}/${upload_path}"
    python3 "${SCRIPT_DIR}/preflight.py" disk \
      --manifest "${FIXTURE_DIR}/manifest.json" \
      --path "${upload_path}" \
      --vus "${CONCURRENT_UPLOADS}" \
      --think-time "${THINK_TIME_SECONDS}" \
      --duration "${DURATION}" \
      --iterations "${ITERATIONS:-0}" \
      --photo-ratio "${PHOTO_RATIO}" \
      --upload-mbps "${UPLOAD_MBPS:-1000}"
    ;;
esac

# The watcher runs on this machine, not in a container, and keeps the run open
# until background jobs catch up so server metrics cover that period too.
readonly LOAD_FINISHED_FILE="${RESULTS_DIR}/.load-finished"
rm -f "${LOAD_FINISHED_FILE}"
IMMICH_API_KEY="${IMMICH_API_KEY}" python3 "${SCRIPT_DIR}/watch_queues.py" \
  --url "${IMMICH_URL/host.docker.internal/localhost}" \
  --output-dir "${RESULTS_DIR}" \
  --stop-file "${LOAD_FINISHED_FILE}" \
  --drain-timeout "${DRAIN_TIMEOUT_SECONDS:-1800}" &
queue_watcher_pid=$!
trap 'kill "${queue_watcher_pid}" 2>/dev/null || true; rm -f "${LOAD_FINISHED_FILE}"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

k6_status=0
# Git Bash rewrites container paths unless MSYS path conversion is disabled.
MSYS_NO_PATHCONV=1 docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "${ROOT_DIR}/loadtest:/scripts:ro" \
  --volume "${FIXTURE_DIR}:/fixtures:ro" \
  --volume "${RESULTS_DIR}:/results" \
  --env "IMMICH_URL=${IMMICH_URL}" \
  --env "IMMICH_API_KEY=${IMMICH_API_KEY}" \
  --env "IMMICH_API_KEYS=${immich_api_keys}" \
  --env "CONCURRENT_UPLOADS=${CONCURRENT_UPLOADS}" \
  --env "THINK_TIME_SECONDS=${THINK_TIME_SECONDS}" \
  --env "DURATION=${DURATION}" \
  --env "PHOTO_RATIO=${PHOTO_RATIO}" \
  --env "ITERATIONS=${ITERATIONS}" \
  --env "UPLOAD_TIMEOUT=${UPLOAD_TIMEOUT:-10m}" \
  --env "K6_PROMETHEUS_RW_SERVER_URL=${K6_PROMETHEUS_RW_SERVER_URL:-http://host.docker.internal:9090/api/v1/write}" \
  --env "K6_PROMETHEUS_RW_TREND_STATS=p(50),p(75),p(90),p(95),p(99),min,max" \
  --env "K6_PROMETHEUS_RW_STALE_MARKERS=true" \
  grafana/k6:0.54.0 run \
  --out json=/results/k6.json \
  --out experimental-prometheus-rw \
  /scripts/upload.js || k6_status=$?

touch "${LOAD_FINISHED_FILE}"
wait "${queue_watcher_pid}" ||
  printf '::warning::The queue watcher exited unexpectedly, so catch-up was not measured.\n' >&2

prometheus_url="${K6_PROMETHEUS_RW_SERVER_URL:-http://localhost:9090/api/v1/write}"
prometheus_url="$(printf '%s' "${prometheus_url%/api/v1/write}" | sed 's/host.docker.internal/localhost/')"
python3 "${SCRIPT_DIR}/summarize_service_latency.py" \
  --prometheus-url "${prometheus_url}" \
  --results-dir "${RESULTS_DIR}" ||
  printf '::warning::The service latency summary exited unexpectedly.\n' >&2
python3 "${SCRIPT_DIR}/summarize_resource_usage.py" \
  --prometheus-url "${prometheus_url}" \
  --results-dir "${RESULTS_DIR}" ||
  printf '::warning::The resource usage summary exited unexpectedly.\n' >&2
exit "${k6_status}"
