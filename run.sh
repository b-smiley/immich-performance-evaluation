#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
command -v docker >/dev/null 2>&1 ||
  { printf 'Error: Docker is not available.\n' >&2; exit 1; }

[[ -f "${SCRIPT_DIR}/docker-compose.yml" ]] ||
  { printf 'Error: docker-compose.yml was not found.\n' >&2; exit 1; }

[[ -f "${SCRIPT_DIR}/.env" ]] ||
  { printf 'Error: .env was not found. Copy .env.example to .env and configure it.\n' >&2; exit 1; }

cd -- "${SCRIPT_DIR}"
exec docker compose up -d
