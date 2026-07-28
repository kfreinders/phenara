#!/usr/bin/env bash

set -Eeuo pipefail

ENABLE_DEVELOPMENT_MODE=false
while (($#)); do
  case "$1" in
    --enable-development-mode) ENABLE_DEVELOPMENT_MODE=true ;;
    -h|--help)
      echo "Usage: deploy/run-phenopi.sh [--enable-development-mode]"
      exit 0
      ;;
    *) echo "[deploy] Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/gui/frontend"
export PHENOPI_ROOT="${PHENOPI_ROOT:-$PROJECT_ROOT}"
export PHENOPI_RUNTIME_DIR="${PHENOPI_RUNTIME_DIR:-$PHENOPI_ROOT/runtime}"
export PHENOPI_CAPTURE_DIR="${PHENOPI_CAPTURE_DIR:-$PHENOPI_ROOT/captures}"
export PHENOPI_DEVELOPMENT_IMAGE_DIR="${PHENOPI_DEVELOPMENT_IMAGE_DIR:-$PHENOPI_ROOT/development/sample-images}"
export PHENOPI_DEVELOPMENT_AVAILABLE="$ENABLE_DEVELOPMENT_MODE"
export PHENOPI_VENV_DIR="${PHENOPI_VENV_DIR:-$PHENOPI_ROOT/.venv}"
export PHENOPI_PYTHON="${PHENOPI_PYTHON:-$PHENOPI_VENV_DIR/bin/python}"
export PHENOPI_TIMEZONE="${PHENOPI_TIMEZONE:-Europe/Amsterdam}"
export PHENOPI_GUI_HOST="${PHENOPI_GUI_HOST:-0.0.0.0}"
export PHENOPI_GUI_PORT="${PHENOPI_GUI_PORT:-8000}"
PYTHON_BIN="$PHENOPI_PYTHON"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PHENOPI_FALLBACK_PYTHON:-python3}"
  export PHENOPI_PYTHON="$PYTHON_BIN"
fi

GUI_PID=""
SCHEDULER_PID=""

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM

  if [[ -n "$GUI_PID" ]] && kill -0 "$GUI_PID" 2>/dev/null; then
    kill "$GUI_PID" 2>/dev/null || true
  fi
  if [[ -n "$SCHEDULER_PID" ]] && kill -0 "$SCHEDULER_PID" 2>/dev/null; then
    kill "$SCHEDULER_PID" 2>/dev/null || true
  fi

  [[ -z "$GUI_PID" ]] || wait "$GUI_PID" 2>/dev/null || true
  [[ -z "$SCHEDULER_PID" ]] || wait "$SCHEDULER_PID" 2>/dev/null || true
  exit "$exit_code"
}

trap cleanup EXIT INT TERM

command -v npm >/dev/null || {
  echo "[deploy] npm is required to build the React frontend." >&2
  exit 1
}
command -v "$PYTHON_BIN" >/dev/null || {
  echo "[deploy] Python executable not found: $PYTHON_BIN" >&2
  exit 1
}
"$PYTHON_BIN" -c 'import cv2; from plantcv import plantcv' >/dev/null 2>&1 || {
  echo "[deploy] The selected Python environment is missing the image-analysis dependencies." >&2
  echo "[deploy] Interpreter: $PYTHON_BIN" >&2
  echo "[deploy] Install requirements with: $PYTHON_BIN -m pip install -r $PROJECT_ROOT/requirements.txt" >&2
  exit 1
}

mkdir -p "$PHENOPI_RUNTIME_DIR" "$PHENOPI_CAPTURE_DIR"

echo "[deploy] Building React frontend"
if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "[deploy] Installing frontend dependencies"
  npm --prefix "$FRONTEND_DIR" ci
fi
npm --prefix "$FRONTEND_DIR" run build

export PYTHONUNBUFFERED=1

echo "[deploy] Starting GUI at http://$PHENOPI_GUI_HOST:$PHENOPI_GUI_PORT"
(
  cd "$PROJECT_ROOT"
  exec "$PYTHON_BIN" -m gui.app
) &
GUI_PID=$!

echo "[deploy] Starting scheduler"
(
  cd "$PROJECT_ROOT"
  exec "$PYTHON_BIN" -m scripts.scheduling.scheduler
) &
SCHEDULER_PID=$!

echo "[deploy] Phenopi is running. Press Ctrl+C to stop both processes."

set +e
wait -n "$GUI_PID" "$SCHEDULER_PID"
EXIT_CODE=$?
set -e

echo "[deploy] A Phenopi process exited; stopping the remaining process."
exit "$EXIT_CODE"
