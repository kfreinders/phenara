#!/usr/bin/env bash

set -Eeuo pipefail

CONNECTION="Wired connection 1"
ADDRESS="192.168.50.2/24"
DELAY_SECONDS=10
MODE="schedule"

usage() {
  cat <<'EOF'
Usage: deploy/configure-direct-ethernet.sh [options]

Configure a NetworkManager wired connection for direct, DHCP-enabled access to
Phenopi. The reconnect is scheduled through systemd so it survives loss of SSH.

Options:
  --connection NAME  NetworkManager connection name (default: Wired connection 1)
  --address CIDR     Pi address on the direct link (default: 192.168.50.2/24)
  --delay SECONDS    Delay before reconnecting Ethernet (default: 10)
  -h, --help         Show this help
EOF
}

while (($#)); do
  case "$1" in
    --connection) CONNECTION="${2:?--connection requires a value}"; shift ;;
    --address) ADDRESS="${2:?--address requires a value}"; shift ;;
    --delay) DELAY_SECONDS="${2:?--delay requires a value}"; shift ;;
    --apply) MODE="apply" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[ethernet] Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

command -v nmcli >/dev/null || {
  echo "[ethernet] NetworkManager's nmcli command is required." >&2
  exit 1
}

if [[ "$MODE" == "apply" ]]; then
  if ((EUID != 0)); then
    echo "[ethernet] Internal --apply mode must run as root." >&2
    exit 1
  fi

  echo "[ethernet] Reconnecting '$CONNECTION' in shared mode."
  nmcli connection down "$CONNECTION" || true
  if nmcli connection up "$CONNECTION"; then
    echo "[ethernet] Direct Ethernet is active at $ADDRESS."
    exit 0
  fi

  echo "[ethernet] Shared-mode activation failed; restoring manual mode." >&2
  nmcli connection modify "$CONNECTION" \
    ipv4.method manual \
    ipv4.addresses "$ADDRESS" \
    ipv4.gateway "" \
    ipv4.dns ""
  nmcli connection up "$CONNECTION"
  exit 1
fi

[[ "$DELAY_SECONDS" =~ ^[1-9][0-9]*$ ]] || {
  echo "[ethernet] --delay must be a positive integer." >&2
  exit 2
}

nmcli connection show "$CONNECTION" >/dev/null || {
  echo "[ethernet] NetworkManager connection not found: $CONNECTION" >&2
  echo "[ethernet] Available connections:" >&2
  nmcli -f NAME,TYPE,DEVICE connection show >&2
  exit 1
}

SCRIPT_PATH="$(realpath -- "$0")"
UNIT_NAME="phenopi-ethernet-reconfigure-$(date +%Y%m%d%H%M%S)-$$"

echo "[ethernet] Updating '$CONNECTION' without interrupting the current link."
sudo nmcli connection modify "$CONNECTION" \
  ipv4.method shared \
  ipv4.addresses "$ADDRESS" \
  ipv4.gateway "" \
  ipv4.dns ""

echo "[ethernet] Scheduling the reconnect in ${DELAY_SECONDS}s as $UNIT_NAME."
sudo systemd-run \
  --unit="$UNIT_NAME" \
  --on-active="${DELAY_SECONDS}s" \
  --collect \
  "$SCRIPT_PATH" \
  --apply \
  --connection "$CONNECTION" \
  --address "$ADDRESS"

cat <<EOF

[ethernet] Configuration is scheduled and will continue if SSH disconnects.
[ethernet] This SSH session should drop in about ${DELAY_SECONDS} seconds.
[ethernet] Set the laptop's Ethernet adapter to automatic/DHCP, then browse:
[ethernet]   http://${ADDRESS%/*}:8000/
[ethernet]
[ethernet] If the laptop does not renew promptly, unplug and reconnect its cable.
[ethernet] After reconnecting, inspect the job with:
[ethernet]   sudo journalctl -u $UNIT_NAME --no-pager
EOF
