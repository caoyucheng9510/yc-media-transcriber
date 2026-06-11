#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_HOME="${APP_HOME:-${HOME}/.yc-media-transcriber}"
ENV_FILE="${APP_ENV_FILE:-${APP_HOME}/.env}"
DATA_DIR="${HOST_DATA_DIR:-${APP_DATA_DIR:-${APP_HOME}/data}}"
IMAGE_NAME="${IMAGE_NAME:-yc-media-transcriber:latest}"
HOST_PORT="${APP_PORT:-8000}"
HOST_BIND="${APP_HOST:-127.0.0.1}"
DOCKER_CPUS="${DOCKER_CPUS:-2}"
DOCKER_MEMORY="${DOCKER_MEMORY:-4g}"
TASK_QUEUE_MAX_CONCURRENCY="${TASK_QUEUE_MAX_CONCURRENCY:-1}"

cd "${ROOT_DIR}"

log() {
  echo "[deploy] $*"
}

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required." >&2
  exit 1
fi

mkdir -p "${DATA_DIR}" "$(dirname "${ENV_FILE}")"

if [[ ! -f "${ENV_FILE}" ]]; then
  log "Creating env file: ${ENV_FILE}"
  cp ".env.example" "${ENV_FILE}"
fi

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  log "Building image: ${IMAGE_NAME}"
  docker build -t "${IMAGE_NAME}" -f docker/Dockerfile .
elif ! docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1; then
  echo "Image ${IMAGE_NAME} does not exist. Run without SKIP_BUILD=1 first." >&2
  exit 1
fi

docker_env_args=(
  --env-file "${ENV_FILE}"
  -e "APP_HOST=0.0.0.0"
  -e "APP_PORT=8000"
  -e "APP_DATA_DIR=/app/data"
  -e "ASR_MODEL_DIR=/app/data/models"
  -e "MODELSCOPE_CACHE=/app/data"
  -e "TERMS_PATH=/app/data/terms.json"
  -e "TASK_QUEUE_MAX_CONCURRENCY=${TASK_QUEUE_MAX_CONCURRENCY}"
)

if [[ -n "${ASR_ENGINE:-}" ]]; then
  docker_env_args+=(-e "ASR_ENGINE=${ASR_ENGINE}")
fi

log "Starting container"
echo "  URL: http://${HOST_BIND}:${HOST_PORT}"
echo "  ENV_FILE: ${ENV_FILE}"
echo "  DATA_DIR: ${DATA_DIR}"
echo "  IMAGE_NAME: ${IMAGE_NAME}"
echo "  DOCKER_CPUS: ${DOCKER_CPUS}"
echo "  DOCKER_MEMORY: ${DOCKER_MEMORY}"
echo "  TASK_QUEUE_MAX_CONCURRENCY: ${TASK_QUEUE_MAX_CONCURRENCY}"

docker run --rm \
  "${docker_env_args[@]}" \
  --cpus "${DOCKER_CPUS}" \
  --memory "${DOCKER_MEMORY}" \
  -p "${HOST_BIND}:${HOST_PORT}:8000" \
  -v "${DATA_DIR}:/app/data" \
  "${IMAGE_NAME}"
