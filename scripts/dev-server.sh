#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_HOME="${APP_HOME:-${HOME}/.yc-media-transcriber}"
ENV_FILE="${APP_ENV_FILE:-${APP_HOME}/.env}"
DATA_DIR="${APP_DATA_DIR:-${APP_HOME}/data}"
HOST="${APP_HOST:-127.0.0.1}"
PORT="${APP_PORT:-8000}"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
INSTALL_ASR="${INSTALL_ASR:-auto}"

cd "${ROOT_DIR}"

log() {
  echo "[dev-server] $*"
}

create_local_env_file() {
  if [[ -f "${ENV_FILE}" ]]; then
    return
  fi

  log "Creating local env file: ${ENV_FILE}"
  if [[ -f ".env.example" ]]; then
    cp ".env.example" "${ENV_FILE}"
  else
    : > "${ENV_FILE}"
  fi

  set_env_value "APP_DATA_DIR" "${DATA_DIR}"
  set_env_value "TASK_QUEUE_MAX_CONCURRENCY" "2"
  set_env_value "ASR_ENGINE" "funasr_paraformer"
  set_env_value "ASR_MODEL_DIR" "${DATA_DIR}/models"
  set_env_value "MODELSCOPE_CACHE" "${DATA_DIR}"
}

set_env_value() {
  local key="$1"
  local value="$2"
  local tmp_file

  tmp_file="$(mktemp)"
  if grep -q "^${key}=" "${ENV_FILE}"; then
    awk -v key="${key}" -v value="${value}" '
      BEGIN { replaced = 0 }
      $0 ~ "^" key "=" {
        print key "=" value
        replaced = 1
        next
      }
      { print }
      END {
        if (replaced == 0) {
          print key "=" value
        }
      }
    ' "${ENV_FILE}" > "${tmp_file}"
  else
    cp "${ENV_FILE}" "${tmp_file}"
    printf "%s=%s\n" "${key}" "${value}" >> "${tmp_file}"
  fi
  mv "${tmp_file}" "${ENV_FILE}"
}

ensure_python_version() {
  "${VENV_DIR}/bin/python" - <<'PY'
import sys

if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11+ is required.")
PY
}

ensure_venv() {
  if [[ -x "${VENV_DIR}/bin/python" ]]; then
    ensure_python_version
    return
  fi

  log "Creating virtual environment: ${VENV_DIR}"
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.11 "${VENV_DIR}"
  else
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  fi
  ensure_python_version
}

install_editable() {
  local extras="$1"

  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "${VENV_DIR}/bin/python" -e "${extras}"
  else
    "${VENV_DIR}/bin/python" -m pip install --upgrade pip
    "${VENV_DIR}/bin/python" -m pip install -e "${extras}"
  fi
}

ensure_app_dependencies() {
  if "${VENV_DIR}/bin/python" - <<'PY'
import importlib.util
import sys

required = ("fastapi", "httpx", "uvicorn", "pytest")
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    print("Missing Python packages: " + ", ".join(missing))
    sys.exit(1)
PY
  then
    return
  fi

  log "Installing Python dependencies: .[dev]"
  install_editable ".[dev]"
}

asr_engine() {
  APP_ENV_FILE="${ENV_FILE}" \
  APP_DATA_DIR="${DATA_DIR}" \
  ASR_MODEL_DIR="${DATA_DIR}/models" \
  MODELSCOPE_CACHE="${DATA_DIR}" \
  "${VENV_DIR}/bin/python" - <<'PY'
from app.config import load_settings

print(load_settings().asr_engine)
PY
}

ensure_asr_dependencies() {
  local engine="$1"

  if [[ "${INSTALL_ASR}" == "0" ]]; then
    return
  fi
  if [[ "${INSTALL_ASR}" == "auto" && "${engine}" == "mock" ]]; then
    return
  fi
  if "${VENV_DIR}/bin/python" - <<'PY'
import importlib.util
import sys

required = ("funasr", "modelscope", "torch", "torchaudio")
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    print("Missing ASR packages: " + ", ".join(missing))
    sys.exit(1)
PY
  then
    return
  fi

  log "Installing ASR dependencies: .[asr]"
  install_editable ".[asr]"
}

ensure_frontend() {
  if [[ "${BUILD_FRONTEND:-auto}" == "0" || ! -f "frontend/package.json" ]]; then
    return
  fi
  if command -v npm >/dev/null 2>&1; then
    if [[ ! -f "frontend/dist/index.html" ]] || find frontend/src -type f -newer frontend/dist/index.html | grep -q .; then
      log "Building frontend"
      npm --prefix frontend install
      npm --prefix frontend run build
    fi
  else
    echo "npm is not available; serving existing frontend/dist if present." >&2
  fi
}

ensure_port_available() {
  if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port ${PORT} is already in use. Stop that process or run with APP_PORT=<port>." >&2
    exit 1
  fi
}

mkdir -p \
  "${APP_HOME}" \
  "$(dirname "${ENV_FILE}")" \
  "${DATA_DIR}" \
  "${DATA_DIR}/cache" \
  "${DATA_DIR}/db" \
  "${DATA_DIR}/jobs" \
  "${DATA_DIR}/logs" \
  "${DATA_DIR}/models" \
  "${DATA_DIR}/temp" \
  "${DATA_DIR}/uploads"

create_local_env_file
ensure_venv
ensure_app_dependencies
CURRENT_ASR_ENGINE="$(asr_engine)"
ensure_asr_dependencies "${CURRENT_ASR_ENGINE}"
ensure_frontend
ensure_port_available

# Runtime env wins over values copied from .env.example and keeps local debug
# paths on the host, even when the env file contains Docker paths.
export APP_ENV_FILE="${ENV_FILE}"
export APP_DATA_DIR="${DATA_DIR}"
export ASR_MODEL_DIR="${ASR_MODEL_DIR:-${DATA_DIR}/models}"
export MODELSCOPE_CACHE="${MODELSCOPE_CACHE:-${DATA_DIR}}"
export APP_HOST="${HOST}"
export APP_PORT="${PORT}"

log "Starting server"
echo "  URL: http://${HOST}:${PORT}"
echo "  APP_ENV_FILE: ${APP_ENV_FILE}"
echo "  APP_DATA_DIR: ${APP_DATA_DIR}"
echo "  ASR_ENGINE: ${CURRENT_ASR_ENGINE}"
echo "  ASR_MODEL_DIR: ${ASR_MODEL_DIR}"
echo "  MODELSCOPE_CACHE: ${MODELSCOPE_CACHE}"

exec "${VENV_DIR}/bin/python" -m uvicorn app.main:app --host "${HOST}" --port "${PORT}"
