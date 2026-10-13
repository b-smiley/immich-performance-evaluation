#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly INSTALL_DIR="${IMMICH_INSTALL_DIR:-${SCRIPT_DIR}/immich-app}"

command -v docker >/dev/null 2>&1 ||
  { printf 'Error: Docker is not available. Run ./provision-windows.sh first.\n' >&2; exit 1; }

[[ -f "${INSTALL_DIR}/docker-compose.yml" ]] ||
  { printf 'Error: %s/docker-compose.yml was not found. Run ./provision-windows.sh first.\n' "${INSTALL_DIR}" >&2; exit 1; }

[[ -f "${INSTALL_DIR}/.env" ]] ||
  { printf 'Error: %s/.env was not found. Run ./provision-windows.sh first.\n' "${INSTALL_DIR}" >&2; exit 1; }

cd -- "${INSTALL_DIR}"
exec docker compose up -d
