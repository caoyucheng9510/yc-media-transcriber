# syntax=docker/dockerfile:1.7
FROM node:22-slim AS frontend-build

WORKDIR /frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend ./
RUN npm run build

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_DATA_DIR=/app/data \
    MODELSCOPE_CACHE=/app/data \
    DEBIAN_FRONTEND=noninteractive \
    UV_TORCH_BACKEND=cpu

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    set -eux; \
    rm -f /etc/apt/apt.conf.d/docker-clean; \
    rm -f /var/cache/apt/archives/lock /var/lib/apt/lists/lock; \
    apt-get update -o Acquire::Retries=5; \
    for attempt in 1 2 3 4 5; do \
      if apt-get install -y --download-only --no-install-recommends -o Acquire::Retries=5 \
          ffmpeg \
          build-essential; then \
        break; \
      fi; \
      if [ "$attempt" = "5" ]; then exit 1; fi; \
      apt-get update -o Acquire::Retries=5; \
      sleep $((attempt * 10)); \
    done; \
    apt-get install -y --no-install-recommends \
      ffmpeg \
      build-essential; \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app
COPY --from=frontend-build /frontend/dist ./frontend/dist

RUN pip install --no-cache-dir --upgrade pip uv \
    && uv pip install --system --no-cache --torch-backend cpu '.[asr]'

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
