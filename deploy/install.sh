#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="${PHENOPI_VENV_DIR:-$PROJECT_ROOT/.venv}"
RUNTIME_DIR="${PHENOPI_RUNTIME_DIR:-$PROJECT_ROOT/runtime}"
CAPTURE_DIR="${PHENOPI_CAPTURE_DIR:-$PROJECT_ROOT/captures}"
DEVELOPMENT_IMAGE_DIR="${PHENOPI_DEVELOPMENT_IMAGE_DIR:-$PROJECT_ROOT/development/sample-images}"
TIMEZONE="${PHENOPI_TIMEZONE:-Europe/Amsterdam}"
GUI_HOST="${PHENOPI_GUI_HOST:-0.0.0.0}"
GUI_PORT="${PHENOPI_GUI_PORT:-8000}"
ENV_DIR="/etc/phenopi"
ENV_FILE="$ENV_DIR/phenopi.env"
SYSTEMD_DIR="/etc/systemd/system"
SKIP_SYSTEM_PACKAGES=false
START_SERVICES=true
ENABLE_DEVELOPMENT_MODE=false

usage() {
  cat <<'EOF'
Usage: deploy/install.sh [options]

Options:
  --skip-system-packages  Do not install apt packages.
  --no-start              Install and enable services without starting them.
  --enable-development-mode
                          Make sample-image development mode available.
  -h, --help              Show this help.

Path and network settings can be overridden with PHENOPI_* environment
variables. The repository location itself becomes PHENOPI_ROOT.
EOF
}

while (($#)); do
  case "$1" in
    --skip-system-packages) SKIP_SYSTEM_PACKAGES=true ;;
    --no-start) START_SERVICES=false ;;
    --enable-development-mode) ENABLE_DEVELOPMENT_MODE=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[install] Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if ((EUID == 0)); then
  INSTALL_USER="${SUDO_USER:-}"
  if [[ -z "$INSTALL_USER" || "$INSTALL_USER" == "root" ]]; then
    echo "[install] Run this as the user who should own Phenopi, not directly as root." >&2
    exit 1
  fi
else
  INSTALL_USER="${USER:-$(id -un)}"
fi

INSTALL_GROUP="$(id -gn "$INSTALL_USER")"
INSTALL_HOME="$(getent passwd "$INSTALL_USER" | cut -d: -f6)"
PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"

run_as_install_user() {
  if [[ "$(id -un)" == "$INSTALL_USER" ]]; then
    "$@"
  else
    sudo -H -u "$INSTALL_USER" "$@"
  fi
}

require_command() {
  command -v "$1" >/dev/null || {
    echo "[install] Required command not found: $1" >&2
    exit 1
  }
}

render_unit() {
  local template="$1"
  local destination="$2"
  local temporary
  temporary="$(mktemp)"
  python3 - "$template" "$temporary" \
    "$INSTALL_USER" "$INSTALL_GROUP" "$PROJECT_ROOT" "$PYTHON_BIN" \
    "$RUNTIME_DIR" "$CAPTURE_DIR" <<'PY'
from pathlib import Path
import sys

source, destination, user, group, root, python, runtime, captures = sys.argv[1:]
replacements = {
    "@PHENOPI_USER@": user,
    "@PHENOPI_GROUP@": group,
    "@PHENOPI_ROOT@": root,
    "@PHENOPI_PYTHON@": python,
    "@PHENOPI_RUNTIME_DIR@": runtime,
    "@PHENOPI_CAPTURE_DIR@": captures,
}
contents = Path(source).read_text()
for marker, value in replacements.items():
    contents = contents.replace(marker, value)
Path(destination).write_text(contents)
PY
  sudo install -o root -g root -m 0644 "$temporary" "$destination"
  rm -f -- "$temporary"
}

write_environment_value() {
  local name="$1"
  local value="$2"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '%s="%s"\n' "$name" "$value"
}

require_command sudo
sudo -v

if [[ "$SKIP_SYSTEM_PACKAGES" == false ]]; then
  require_command apt-get
  packages=(python3 python3-pip python3-venv nodejs npm)
  if [[ -r /proc/device-tree/model ]] && grep -q "Raspberry Pi" /proc/device-tree/model; then
    packages+=(python3-picamera2)
  fi
  echo "[install] Installing system packages"
  sudo apt-get update
  sudo apt-get install -y "${packages[@]}"
fi

require_command python3
require_command npm
if ! run_as_install_user test -w "$PROJECT_ROOT"; then
  echo "[install] $INSTALL_USER must be able to write to $PROJECT_ROOT." >&2
  exit 1
fi

echo "[install] Creating runtime directories"
run_as_install_user mkdir -p "$RUNTIME_DIR" "$CAPTURE_DIR"

echo "[install] Creating Python virtual environment at $VENV_DIR"
if [[ ! -x "$PYTHON_BIN" ]]; then
  run_as_install_user python3 -m venv --system-site-packages "$VENV_DIR"
fi
run_as_install_user "$PIP_BIN" install --upgrade pip wheel
run_as_install_user "$PIP_BIN" install -r "$PROJECT_ROOT/requirements.txt"

echo "[install] Installing and building frontend dependencies"
run_as_install_user env HOME="$INSTALL_HOME" \
  npm --prefix "$PROJECT_ROOT/gui/frontend" ci
run_as_install_user env HOME="$INSTALL_HOME" \
  npm --prefix "$PROJECT_ROOT/gui/frontend" run build

environment_tmp="$(mktemp)"
trap 'rm -f -- "${environment_tmp:-}"' EXIT
{
  write_environment_value PHENOPI_ROOT "$PROJECT_ROOT"
  write_environment_value PHENOPI_RUNTIME_DIR "$RUNTIME_DIR"
  write_environment_value PHENOPI_CAPTURE_DIR "$CAPTURE_DIR"
  write_environment_value PHENOPI_DEVELOPMENT_IMAGE_DIR "$DEVELOPMENT_IMAGE_DIR"
  write_environment_value PHENOPI_DEVELOPMENT_AVAILABLE "$ENABLE_DEVELOPMENT_MODE"
  write_environment_value PHENOPI_VENV_DIR "$VENV_DIR"
  write_environment_value PHENOPI_PYTHON "$PYTHON_BIN"
  write_environment_value PHENOPI_TIMEZONE "$TIMEZONE"
  write_environment_value PHENOPI_GUI_HOST "$GUI_HOST"
  write_environment_value PHENOPI_GUI_PORT "$GUI_PORT"
  printf 'PYTHONUNBUFFERED=1\n'
} > "$environment_tmp"

echo "[install] Writing shared environment configuration"
sudo install -d -o root -g root -m 0755 "$ENV_DIR"
sudo install -o root -g root -m 0644 "$environment_tmp" "$ENV_FILE"

echo "[install] Installing systemd services"
render_unit \
  "$PROJECT_ROOT/deploy/systemd/phenopi-scheduler.service.in" \
  "$SYSTEMD_DIR/phenopi-scheduler.service"
render_unit \
  "$PROJECT_ROOT/deploy/systemd/phenopi-gui.service.in" \
  "$SYSTEMD_DIR/phenopi-gui.service"

sudo systemctl daemon-reload
sudo systemctl enable phenopi-scheduler.service phenopi-gui.service
if [[ "$START_SERVICES" == true ]]; then
  sudo systemctl restart phenopi-scheduler.service phenopi-gui.service
fi

address="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
echo
echo "[install] Phenopi installation complete"
echo "[install] Project: $PROJECT_ROOT"
echo "[install] User:    $INSTALL_USER"
echo "[install] Web GUI: http://${address:-localhost}:$GUI_PORT"
echo "[install] Status:  sudo systemctl status phenopi-scheduler phenopi-gui"
