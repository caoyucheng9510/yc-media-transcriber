# 开发与测试

本文档面向要修改代码、调试前端或运行测试的人。普通使用先看仓库根目录的 `README.md`。

## 技术栈

- Python 3.11+
- FastAPI
- SQLite
- 文件系统存储
- ffmpeg / ffprobe
- yt-dlp
- FunASR
- DeepSeek 或其他兼容 OpenAI 接口的 LLM
- Vite + React + Tailwind CSS v4 + shadcn/ui

## 本地启动

唯一推荐的本地启动入口：

```bash
./scripts/dev-server.sh
```

脚本会自动处理：

- 创建项目内 `.venv`。
- 安装 Python 基础依赖。
- 创建 `~/.yc-media-transcriber/.env`。
- 创建 `~/.yc-media-transcriber/data` 及必要子目录。
- 缺失或过期时构建 `frontend/dist`。
- 根据当前 ASR 配置安装 FunASR 依赖。
- 启动 `uvicorn app.main:app`。

常用参数：

```bash
APP_PORT=8001 ./scripts/dev-server.sh
ASR_ENGINE=mock ./scripts/dev-server.sh
INSTALL_ASR=0 ./scripts/dev-server.sh
BUILD_FRONTEND=0 ./scripts/dev-server.sh
```

## 手动维护依赖

默认使用项目内 `.venv`，不要向全局 Python 或 user-site 安装依赖。

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
```

安装真实 ASR 依赖：

```bash
uv pip install --python .venv/bin/python -e '.[asr]'
```

## 前端开发

单独启动前端开发服务：

```bash
npm --prefix frontend run dev
```

构建前端：

```bash
npm --prefix frontend install
npm --prefix frontend run build
```

生产模式由 FastAPI 托管 `frontend/dist`。修改前端后需要重新构建。

## 测试

最小回归：

```bash
.venv/bin/python -m pytest
```

分范围验收：

```bash
.venv/bin/python -m pytest tests/unit tests/api
.venv/bin/python -m pytest tests/unit tests/api tests/llm
.venv/bin/python -m pytest tests/source_resolver tests/downloaders tests/api
.venv/bin/python -m pytest tests/unit/test_exporters.py tests/api/test_api.py
```

构建 Docker 镜像：

```bash
docker build -t yc-media-transcriber:latest -f docker/Dockerfile .
```

默认测试不得依赖真实 FunASR、DeepSeek、TikHub key、YouTube/Bilibili 网络下载或用户私有媒体。需要外部凭据、真实音视频、大文件或网络环境的验证，应明确标为手动验证。

## Docker

构建并启动：

```bash
docker build -t yc-media-transcriber:latest -f docker/Dockerfile .
./scripts/deploy.sh
```

Docker 使用 Mac 上的：

```text
~/.yc-media-transcriber/.env
~/.yc-media-transcriber/data
```

容器内数据目录固定为 `/app/data`。

## 本地产物边界

不要提交以下内容：

- `.venv/`
- `frontend/dist/`
- `frontend/node_modules/`
- `.tmp/`
- `logs/`
- `cases/`
- `*.egg-info/`
- `__pycache__/`
- 真实 API key、cookie、token
- 用户媒体、转录产物、SQLite 数据库、模型缓存

提交前建议检查：

```bash
git status --short --ignored
git diff --check
```
