#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly ARCHIVE="${1:-${ROOT_DIR}/data/results/prometheus-tsdb.tar.gz}"
readonly REPLAY_DIR="${REPLAY_DATA_DIR:-${ROOT_DIR}/data/replay/prometheus}"
readonly COMPOSE_FILE="${ROOT_DIR}/monitoring/replay-compose.yml"
readonly PROJECT_NAME="${COMPOSE_PROJECT_NAME:-immich-results-replay}"

[[ -f "${ARCHIVE}" ]] ||
  { printf 'Error: archive not found: %s\n' "${ARCHIVE}" >&2; exit 1; }

docker compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" down
rm -rf "${REPLAY_DIR}"
mkdir -p "${REPLAY_DIR}"

if command -v cygpath >/dev/null 2>&1; then
  readonly DOCKER_REPLAY_DIR="$(cygpath --absolute --windows "${REPLAY_DIR}")"
  readonly DOCKER_ARCHIVE="$(cygpath --absolute --windows "${ARCHIVE}")"
else
  readonly DOCKER_REPLAY_DIR="${REPLAY_DIR}"
  readonly DOCKER_ARCHIVE="${ARCHIVE}"
fi

MSYS_NO_PATHCONV=1 docker run --rm \
  -v "${DOCKER_ARCHIVE}:/archive.tar.gz:ro" \
  -v "${DOCKER_REPLAY_DIR}:/replay" \
  alpine:3.20 \
  tar -xzf /archive.tar.gz -C /replay

docker compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" up -d

printf 'Replay Grafana: http://localhost:%s\n' "${REPLAY_GRAFANA_PORT:-3001}"
printf 'Immich dashboard: http://localhost:%s/d/immich-overview/immich-overview\n' \
  "${REPLAY_GRAFANA_PORT:-3001}"
printf 'k6 dashboard: http://localhost:%s/d/k6-prometheus/k6-prometheus\n' \
  "${REPLAY_GRAFANA_PORT:-3001}"
printf 'Replay Prometheus: http://localhost:%s\n' "${REPLAY_PROMETHEUS_PORT:-9091}"
printf 'Prometheus k6 query: http://localhost:%s/graph?g0.expr=k6_http_reqs_total&g0.tab=1&g0.range_input=1h\n' \
  "${REPLAY_PROMETHEUS_PORT:-9091}"
