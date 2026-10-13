#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly DEFAULT_INSTALL_DIR="${SCRIPT_DIR}/immich-app"
readonly COMPOSE_URL="https://github.com/immich-app/immich/releases/latest/download/docker-compose.yml"
readonly ENV_URL="https://github.com/immich-app/immich/releases/latest/download/example.env"
readonly MIN_DOCKER_ENGINE_VERSION="25.0.0"

install_dir="${IMMICH_INSTALL_DIR:-${DEFAULT_INSTALL_DIR}}"
assume_yes=false
dry_run=false

usage() {
  cat <<'EOF'
Usage: ./provision-windows.sh [options]

Prepare an Immich Docker Compose environment from Git Bash on Windows.

Options:
  -y, --assume-yes       Confirm installation and download actions automatically
      --dry-run          Show actions without changing the system or files
  -d, --directory PATH   Directory for docker-compose.yml and .env
  -h, --help             Show this help
EOF
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '%s\n' "$*"
}

confirm() {
  local prompt="$1"

  if [[ "${assume_yes}" == true ]]; then
    return 0
  fi

  [[ -t 0 ]] || die "Confirmation is required. Re-run with --assume-yes only if these actions are approved."
  read -r -p "${prompt} [y/N] " answer
  [[ "${answer}" =~ ^[Yy]([Ee][Ss])?$ ]]
}

version_at_least() {
  local actual="${1#v}"
  local required="${2#v}"
  local actual_major actual_minor actual_patch
  local required_major required_minor required_patch

  IFS=. read -r actual_major actual_minor actual_patch <<< "${actual%%-*}"
  IFS=. read -r required_major required_minor required_patch <<< "${required%%-*}"
  actual_major="${actual_major:-0}"
  actual_minor="${actual_minor:-0}"
  actual_patch="${actual_patch:-0}"
  required_major="${required_major:-0}"
  required_minor="${required_minor:-0}"
  required_patch="${required_patch:-0}"

  (( actual_major > required_major )) ||
    (( actual_major == required_major && actual_minor > required_minor )) ||
    (( actual_major == required_major && actual_minor == required_minor && actual_patch >= required_patch ))
}

docker_engine_version() {
  docker version --format '{{.Server.Version}}' 2>/dev/null || true
}

docker_compose_version() {
  docker compose version --short 2>/dev/null || true
}

offer_docker_desktop_install() {
  local install_command

  command -v winget >/dev/null 2>&1 ||
    die "Docker is unavailable and winget was not found. Install Docker Desktop manually, then rerun this script."

  install_command="winget install --id Docker.DockerDesktop --exact --accept-source-agreements --accept-package-agreements"
  log "Docker Desktop is not available. The following Windows package will be installed:"
  log "  ${install_command}"
  confirm "Install Docker Desktop now?" ||
    die "Docker Desktop installation was not approved."

  if [[ "${dry_run}" == true ]]; then
    log "Dry run: Docker Desktop installation skipped."
    return 0
  fi

  winget install --id Docker.DockerDesktop --exact \
    --accept-source-agreements --accept-package-agreements
  log "Docker Desktop was installed. Start Docker Desktop, wait for it to become ready, and rerun this script."
  exit 0
}

check_docker() {
  local engine_version compose_version

  if ! command -v docker >/dev/null 2>&1; then
    offer_docker_desktop_install
    return
  fi

  engine_version="$(docker_engine_version)"
  if [[ -z "${engine_version}" ]]; then
    if [[ "${dry_run}" == true ]]; then
      log "Dry run: Docker is installed, but its engine is not reachable."
      return
    fi
    die "Docker is installed but the engine is not reachable. Start Docker Desktop and rerun this script."
  fi

  if ! version_at_least "${engine_version}" "${MIN_DOCKER_ENGINE_VERSION}"; then
    log "Docker Engine ${engine_version} is below the required ${MIN_DOCKER_ENGINE_VERSION}."
    offer_docker_desktop_install
    return
  fi

  compose_version="$(docker_compose_version)"
  [[ -n "${compose_version}" ]] ||
    die "Docker Compose v2 is unavailable. Update Docker Desktop and rerun this script."
  version_at_least "${compose_version}" "2.0.0" ||
    die "Docker Compose ${compose_version} is below the required v2. Update Docker Desktop and rerun this script."

  log "Docker Engine ${engine_version} and Docker Compose ${compose_version} meet the requirements."
}

download_if_missing() {
  local url="$1"
  local destination="$2"

  if [[ -e "${destination}" ]]; then
    log "Keeping existing ${destination}; it will not be overwritten."
    return
  fi

  log "Planned download: ${url}"
  if [[ "${dry_run}" == true ]]; then
    log "Dry run: ${destination} would be created."
    return
  fi

  curl --fail --location --silent --show-error --output "${destination}" "${url}"
  log "Created ${destination}."
}

parse_args() {
  while (($# > 0)); do
    case "$1" in
      -y|--assume-yes)
        assume_yes=true
        ;;
      --dry-run)
        dry_run=true
        ;;
      -d|--directory)
        (($# >= 2)) || die "Missing value for --directory."
        install_dir="$2"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown option: $1"
        ;;
    esac
    shift
  done
}

main() {
  parse_args "$@"

  log "Immich provisioning target: ${install_dir}"
  log "This script prepares files only; use ./run.sh to start Immich."
  check_docker

  command -v curl >/dev/null 2>&1 ||
    die "curl is required to download Immich's Compose files."

  confirm "Download missing Immich Compose files into ${install_dir}?" ||
    die "Download was not approved."

  if [[ "${dry_run}" == false ]]; then
    mkdir -p "${install_dir}"
  fi

  download_if_missing "${COMPOSE_URL}" "${install_dir}/docker-compose.yml"
  download_if_missing "${ENV_URL}" "${install_dir}/.env"
  log "Provisioning complete. Review ${install_dir}/.env before running ./run.sh."
}

main "$@"
