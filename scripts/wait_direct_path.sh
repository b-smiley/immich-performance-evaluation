#!/usr/bin/env bash
# Print a Tailscale peer's IPv4 address once there is a direct path to it.
# The load test must not run over a relayed path, so exit 1 if the peer never
# appears or no direct path forms in time; the batch then retries the row.

set -Euo pipefail

readonly PEER_NAME="$1"
readonly APPEAR_SECONDS="${APPEAR_SECONDS:-600}"
readonly DIRECT_SECONDS="${DIRECT_SECONDS:-120}"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly STATUS_FILE="$(mktemp)"
trap 'rm -f "${STATUS_FILE}"' EXIT

peer_ip() {
  tailscale status --json > "${STATUS_FILE}" &&
    python3 "${SCRIPT_DIR}/find_peer_ip.py" "${STATUS_FILE}" "${PEER_NAME}" 2>/dev/null ||
    getent ahostsv4 "${PEER_NAME}" | awk 'NR == 1 {print $1}'
}

appear_deadline=$((SECONDS + APPEAR_SECONDS))
direct_deadline=""
while :; do
  peer_address="$(peer_ip)"
  if [[ -n "${peer_address}" ]]; then
    direct_deadline="${direct_deadline:-$((SECONDS + DIRECT_SECONDS))}"
    # Exits 0 only for a pong over a direct path, not one through a relay.
    if tailscale ping -c 1 --timeout=5s "${peer_address}" >/dev/null 2>&1; then
      printf '%s\n' "${peer_address}"
      exit 0
    fi
  fi
  # Once the peer has appeared, its deadline holds even if it leaves the tailnet.
  if [[ -n "${direct_deadline}" ]] && (( SECONDS >= direct_deadline )); then
    printf '::error::No direct Tailscale path to %s within %ss of it appearing.\n' \
      "${PEER_NAME}" "${DIRECT_SECONDS}" >&2
    exit 1
  elif [[ -z "${direct_deadline}" ]] && (( SECONDS >= appear_deadline )); then
    printf '::error::%s did not join the tailnet within %ss.\n' "${PEER_NAME}" "${APPEAR_SECONDS}" >&2
    exit 1
  fi
  sleep 5
done
