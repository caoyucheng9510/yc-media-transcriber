# 配置说明

本文档面向需要修改运行配置的人。只想启动和使用项目时，先看仓库根目录的 `README.md`。

## 配置文件位置

本地默认配置文件是：

```text
~/.yc-media-transcriber/.env
```

`./scripts/dev-server.sh` 和 `./scripts/deploy.sh` 会在文件不存在时基于 `.env.example` 创建它。

配置来源优先级：

1. 运行命令时直接传入的环境变量。
2. `APP_ENV_FILE` 指向的文件。
3. 当前目录下的 `.env`。
4. `~/.yc-media-transcriber/.env`。
5. 程序默认值。

## 本地数据目录

Mac 本地默认数据目录是：

```text
~/.yc-media-transcriber/data
```

常见子目录：

| 目录 | 用途 |
|---|---|
| `uploads` | 用户上传文件 |
| `temp` | 临时处理文件 |
| `jobs` | 任务产物 |
| `cache` | 缓存 |
| `db` | SQLite 数据库 |
| `models` | FunASR 模型 |
| `logs` | 日志 |

Docker 内的数据目录是 `/app/data`，启动脚本会把它挂载到 Mac 上的 `~/.yc-media-transcriber/data`。

## 基础配置

```env
APP_HOST=127.0.0.1
APP_PORT=8000
APP_DATA_DIR=/app/data
APP_MAX_UPLOAD_MB=2048
APP_PROCESS_JOBS_INLINE=false
TASK_QUEUE_MAX_CONCURRENCY=1
APP_TEMP_RETENTION_HOURS=24
API_AUTH_TOKEN=
```

- `APP_HOST` 和 `APP_PORT` 控制监听地址。
- `APP_DATA_DIR` 控制数据目录。Mac 本地脚本会覆盖为 `~/.yc-media-transcriber/data`。
- `APP_MAX_UPLOAD_MB` 控制上传文件大小上限。
- `APP_PROCESS_JOBS_INLINE=true` 时任务会在请求流程内同步处理，主要用于自动化测试。
- `TASK_QUEUE_MAX_CONCURRENCY` 控制同时处理的完整任务数。默认 `1`，会同时限制下载、ASR、TikHub CDN 下载和 LLM 任务阶段。
- `API_AUTH_TOKEN` 为空时不要求 API token；设置后所有 `/api/*` 请求都需要 `Authorization: Bearer <token>`。

## ASR 配置

默认真实转录引擎是 FunASR：

```env
ASR_ENGINE=funasr_paraformer
ASR_LANGUAGE=auto
ASR_DEVICE=cpu
ASR_MODEL=paraformer-zh
ASR_MODEL_REVISION=v2.0.4
ASR_VAD_MODEL=fsmn-vad
ASR_VAD_MODEL_REVISION=v2.0.4
ASR_PUNC_MODEL=ct-punc-c
ASR_PUNC_MODEL_REVISION=v2.0.4
ASR_SPK_MODEL=cam++
ASR_SPK_MODEL_REVISION=v2.0.2
ASR_MODEL_DIR=/app/data/models
MODELSCOPE_CACHE=/app/data
ASR_MOCK_TEXT=这是一段用于测试的本地转录文本。
```

Mac 本地调试时，`dev-server.sh` 会把模型目录固定到：

```text
~/.yc-media-transcriber/data/models
```

只调试界面或任务流程时，可以用：

```bash
ASR_ENGINE=mock ./scripts/dev-server.sh
```

如果要跳过 ASR 依赖自动安装：

```bash
INSTALL_ASR=0 ./scripts/dev-server.sh
```

注意：`MODELSCOPE_CACHE` 应指向 data root，例如 `/app/data`，不要指向 `/app/data/models`，否则部分依赖模型可能被放到多一层的 `models/models` 目录。

## Bilibili 下载配置

```env
BILIBILI_BACKEND=yt-dlp
BILIBILI_BBDOWN_PATH=
```

当前代码路径中，Bilibili 下载实际由 `yt-dlp` downloader 处理。以上配置项存在于 `.env.example` 和 `Settings` 中，但当前下载器尚未用它们切换后端；不要依赖 `BILIBILI_BACKEND` 把运行时切到其他下载实现。

## LLM 配置

默认 provider 是 DeepSeek：

```env
LLM_PROVIDER=deepseek
LLM_API_KEY=
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
LLM_STRUCTURED_OUTPUT_MODE=auto
LLM_PROMPT_VERSION=reference_style_v1
LLM_SEGMENT_ENABLE_THRESHOLD=5000
LLM_SEGMENT_SIZE=3000
LLM_SEGMENT_OVERLAP=0
LLM_CALIBRATION_MAX_RETRIES=2
LLM_CHUNK_TIME_BUDGET_SECONDS=300
LLM_CHAT_TIMEOUT_SECONDS=60
LLM_DIALOG_MIN_CHUNK_CHARS=300
LLM_DIALOG_PREFERRED_CHUNK_CHARS=800
LLM_DIALOG_MAX_CHUNK_CHARS=1500
LLM_VALIDATION_ENABLED=false
LLM_SUMMARY_MIN_CHARS=500
LLM_SUMMARY_CHUNK_THRESHOLD=8000
LLM_QUALITY_MIN_RATIO=0.5
LLM_QUALITY_MAX_RATIO=1.8
```

`LLM_PROVIDER=deepseek` 时读取 `LLM_API_KEY`。

使用其他兼容 OpenAI 接口的网关时：

```env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=<your-key>
LLM_BASE_URL=https://your-compatible-endpoint
```

未配置 provider 所需 key，却启用 AI 校对或总结时，任务会失败并返回 `llm_provider_not_configured`。

- `LLM_MODEL` 是当前所有 LLM 环节共用的模型，包括关键信息提取、说话人推断、校对、总结和可选质量检查。
- `LLM_STRUCTURED_OUTPUT_MODE` 控制结构化输出请求方式，支持 `auto`、`json_object`、`plain`。
- `LLM_SEGMENT_*` 控制长文本校对分块。
- `LLM_DIALOG_*` 控制带说话人结构的对话分块大小。
- `LLM_SUMMARY_MIN_CHARS` 控制短文本是否跳过总结，`LLM_SUMMARY_CHUNK_THRESHOLD` 控制长文本总结是否分块。
- `LLM_VALIDATION_ENABLED=true` 会开启额外质量检查调用，默认关闭。
- 长文本校对会在单个任务内部使用固定的小并发处理分块，不再通过 `.env` 暴露单独 worker 配置。

## 术语表配置

```env
TERMS_PATH=/app/data/terms.json
```

术语表通过 `/api/settings/terms` 读写。Mac 本地运行时，如果 `TERMS_PATH` 仍是默认 `/app/data/terms.json`，程序会自动映射到当前 `APP_DATA_DIR` 下的 `terms.json`。

## TikHub 配置

抖音、小红书和创作者主页导入依赖 TikHub：

```env
TIKHUB_API_KEY=
TIKHUB_ALTERNATE_API_KEY=
TIKHUB_BASE_URL=https://api.tikhub.io
TIKHUB_MAX_RETRIES=3
TIKHUB_RETRY_DELAY=5
TIKHUB_TIMEOUT=30
TIKHUB_REQUEST_MIN_INTERVAL_SECONDS=2
TIKHUB_REQUEST_MAX_INTERVAL_SECONDS=7
TIKHUB_ENABLE_YOUTUBE_FALLBACK=true
TIKHUB_ENABLE_BILIBILI_FALLBACK=true
CREATOR_PREVIEW_TTL_SECONDS=3600
CREATOR_PREVIEW_MAX_ITEMS=50
```

中国大陆网络可尝试把 `TIKHUB_BASE_URL` 改为：

```env
TIKHUB_BASE_URL=https://api.tikhub.dev
```

未配置 `TIKHUB_API_KEY` 时，抖音和小红书任务会失败并返回 `platform_provider_not_configured`。YouTube 和 Bilibili 默认仍使用本地下载路径；只有配置 TikHub 后才会在特定失败场景尝试 fallback。

## 监控配置

`/metrics` 页面用于查看资源压力和最近任务效率：

```env
METRICS_ENABLED=true
METRICS_RESOURCE_SNAPSHOT_ENABLED=true
METRICS_SAMPLE_INTERVAL_SECONDS=5
METRICS_RECORD_HTTP_DETAILS=false
```

- `METRICS_ENABLED=false` 时不写任务 metrics，也不启动资源采样。
- `METRICS_RESOURCE_SNAPSHOT_ENABLED=false` 时仍记录任务 metrics，但不采样 CPU 和内存。
- `METRICS_RECORD_HTTP_DETAILS=false` 时只保留聚合计数。
- metrics 不保存 API key、Authorization header、完整临时下载 URL、完整 prompt、完整 LLM 响应或响应 body。

## 下载安全配置

直链下载会做 SSRF 防护，默认禁止本机、内网、链路本地、云元数据和保留地址。

平台 CDN 在代理 Fake-IP 环境下可能解析到 `198.18.0.0/15`。服务只在域名属于可信媒体 CDN 后缀时放行该网段。

```env
APP_ALLOW_PRIVATE_URLS=false
APP_PRIVATE_URL_ALLOWLIST=
APP_TRUSTED_MEDIA_HOST_SUFFIXES=acgvideo.com,bilivideo.com,bytecdn.cn,bytefcdn.com,byteimg.com,douyinpic.com,douyinvod.com,douyinstatic.com,ggpht.com,googlevideo.com,hdslb.com,pstatp.com,rednotecdn.com,snssdk.com,xhscdn.com,xyzcdn.net,youtube.com,ytimg.com,zjcdn.com
APP_MEDIA_FAKE_IP_CIDRS=198.18.0.0/15
```

不要用 `APP_ALLOW_PRIVATE_URLS=true` 解决普通平台 CDN 下载问题。它会放开所有私网地址，只适合明确需要访问可信内网媒体源的手动调试。
