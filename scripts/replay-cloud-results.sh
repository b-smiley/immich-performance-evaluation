#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly RUN_ID="${1:-}"
readonly RESULTS_DIR="${ROOT_DIR}/data/results/cloud-${RUN_ID}"
readonly SERVER_ARTIFACT="${RESULTS_DIR}/server"
readonly CLIENT_ARTIFACT="${RESULTS_DIR}/client"

if [[ -z "${RUN_ID}" ]]; then
  printf 'Usage: %s <github-actions-run-id>\n' "$(basename "$0")" >&2
  exit 2
fi

command -v gh >/dev/null 2>&1 ||
  { printf 'Error: gh CLI is required.\n' >&2; exit 1; }

rm -rf "${RESULTS_DIR}"
mkdir -p "${SERVER_ARTIFACT}" "${CLIENT_ARTIFACT}"

gh run download "${RUN_ID}" \
  --name "immich-load-${RUN_ID}-server" \
  --dir "${SERVER_ARTIFACT}"
gh run download "${RUN_ID}" \
  --name "immich-load-${RUN_ID}-client" \
  --dir "${CLIENT_ARTIFACT}"

readonly ARCHIVE="${SERVER_ARTIFACT}/prometheus-tsdb.tar.gz"
[[ -s "${ARCHIVE}" ]] ||
  { printf 'Error: server artifact did not contain %s.\n' "${ARCHIVE}" >&2; exit 1; }

bash "${SCRIPT_DIR}/replay-results.sh" "${ARCHIVE}"

readonly GRAFANA_URL="http://localhost:${REPLAY_GRAFANA_PORT:-3001}"
for attempt in $(seq 1 30); do
  if curl --fail --silent "${GRAFANA_URL}/api/health" >/dev/null; then
    break
  fi
  sleep 1
done

if command -v powershell.exe >/dev/null 2>&1; then
  powershell.exe -NoProfile -Command \
    "Start-Process '${GRAFANA_URL}/d/immich-overview/immich-overview'; Start-Process '${GRAFANA_URL}/d/k6-prometheus/k6-prometheus'"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "${GRAFANA_URL}/d/immich-overview/immich-overview" >/dev/null 2>&1 &
  xdg-open "${GRAFANA_URL}/d/k6-prometheus/k6-prometheus" >/dev/null 2>&1 &
elif command -v open >/dev/null 2>&1; then
  open "${GRAFANA_URL}/d/immich-overview/immich-overview"
  open "${GRAFANA_URL}/d/k6-prometheus/k6-prometheus"
else
  printf 'Dashboards are ready at %s\n' "${GRAFANA_URL}"
fi

printf 'Cloud results: %s\n' "${RESULTS_DIR}"
printf 'Grafana dashboards opened at %s\n' "${GRAFANA_URL}"
