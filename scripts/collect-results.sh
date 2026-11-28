#!/usr/bin/env bash

set -Eeuo pipefail

readonly ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly RESULTS_DIR="${1:-${ROOT_DIR}/data/results}"
readonly PROJECT_NAME="${COMPOSE_PROJECT_NAME:-immich-performance}"

mkdir -p "${RESULTS_DIR}"
if command -v cygpath >/dev/null 2>&1; then
  readonly DOCKER_RESULTS_DIR="$(cygpath --absolute --windows "${RESULTS_DIR}")"
else
  readonly DOCKER_RESULTS_DIR="${RESULTS_DIR}"
fi
docker compose ps > "${RESULTS_DIR}/compose-ps.txt"
docker compose logs --no-color > "${RESULTS_DIR}/compose.log"
cp "${ROOT_DIR}/monitoring/grafana/dashboards/immich-overview.json" \
  "${RESULTS_DIR}/grafana-dashboard.json"
docker compose stop prometheus
trap 'docker compose start prometheus >/dev/null 2>&1 || true' EXIT

prometheus_volume="$(
  docker volume ls \
    --filter "label=com.docker.compose.project=${PROJECT_NAME}" \
    --format '{{.Name}}' | grep 'prometheus-data' | head -n 1 || true
)"
if [[ -n "${prometheus_volume}" ]]; then
  MSYS_NO_PATHCONV=1 docker run --rm \
    -v "${prometheus_volume}:/data:ro" \
    -v "${DOCKER_RESULTS_DIR}:/results" \
    alpine:3.20 \
    tar -czf /results/prometheus-tsdb.tar.gz -C /data .
  [[ -s "${RESULTS_DIR}/prometheus-tsdb.tar.gz" ]] ||
    { printf 'Error: Prometheus TSDB archive was not created.\n' >&2; exit 1; }
else
  printf 'Error: Prometheus data volume was not found for project %s.\n' "${PROJECT_NAME}" >&2
  exit 1
fi

# One row per asset. Immich writes asset_file rows once all of an asset's
# transforms finish, so preview_at is when the asset became viewable.
docker compose exec -T database sh -c \
  'psql --quiet --no-psqlrc -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  > "${RESULTS_DIR}/asset-timeline.csv" <<'SQL'
SET TIME ZONE 'UTC';
COPY (
  SELECT a.id, a.type,
    a."createdAt" AS uploaded_at,
    s."metadataExtractedAt" AS metadata_at,
    p."createdAt" AS preview_at,
    t."createdAt" AS thumbnail_at,
    e."exifImageWidth" AS width,
    e."exifImageHeight" AS height,
    e."fileSizeInByte" AS file_size_bytes
  FROM asset a
  LEFT JOIN asset_job_status s ON s."assetId" = a.id
  LEFT JOIN asset_exif e ON e."assetId" = a.id
  LEFT JOIN asset_file p ON p."assetId" = a.id AND p.type = 'preview' AND NOT p."isEdited"
  LEFT JOIN asset_file t ON t."assetId" = a.id AND t.type = 'thumbnail' AND NOT t."isEdited"
  ORDER BY a."createdAt"
) TO STDOUT WITH (FORMAT csv, HEADER);
SQL
