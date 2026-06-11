# 排障说明

本文档记录常见现象、原因和处理方式。

## 端口被占用

现象：

```text
Port 8000 is already in use.
```

处理：

```bash
APP_PORT=8001 ./scripts/dev-server.sh
```

或者停止正在占用 8000 端口的进程。

## 网页打不开

先看终端输出的 URL，默认是：

```text
http://127.0.0.1:8000
```

如果你修改了 `APP_PORT`，浏览器里的端口也要同步修改。

## 第一次真实转录很慢

真实 FunASR 首次运行可能需要安装依赖和下载模型。模型默认保存在：

```text
~/.yc-media-transcriber/data/models
```

后续任务会复用已下载模型。相同媒体、相同 ASR 配置再次提交时，也可能命中 ASR 转录缓存。

## 只想验证服务能启动

使用 mock ASR：

```bash
ASR_ENGINE=mock ./scripts/dev-server.sh
```

mock 模式不会做真实转录，适合检查网页、任务创建、任务列表和导出流程。

## AI 校对或总结失败

常见错误码：

```text
llm_provider_not_configured
```

原因是启用了 AI 校对或总结，但没有配置 LLM key。

处理：编辑 `~/.yc-media-transcriber/.env`，配置：

```env
LLM_API_KEY=
```

使用非 DeepSeek 服务时，还需要检查：

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://your-compatible-endpoint
```

## 抖音或小红书失败

常见错误码：

```text
platform_provider_not_configured
```

原因是这些平台依赖 TikHub，但没有配置 key。

处理：

```env
TIKHUB_API_KEY=
```

中国大陆网络可尝试：

```env
TIKHUB_BASE_URL=https://api.tikhub.dev
```

## YouTube 或 Bilibili 下载失败

YouTube 和 Bilibili 默认使用本地下载路径。请先确认本机网络可访问目标内容，并确认依赖已安装。

如果配置了 TikHub，部分失败场景会尝试 fallback：

```env
TIKHUB_ENABLE_YOUTUBE_FALLBACK=true
TIKHUB_ENABLE_BILIBILI_FALLBACK=true
```

未配置 TikHub 时，YouTube 和 Bilibili 仍会走默认路径，不会因为没有 TikHub key 直接失败。

## 媒体直链被拒绝

服务默认禁止下载本机、内网、链路本地、云元数据和保留地址，避免 SSRF 风险。

不要为普通公网媒体开启：

```env
APP_ALLOW_PRIVATE_URLS=true
```

只有在你明确知道目标是可信内网媒体源时，才考虑临时开启。普通平台 CDN 问题应优先通过 `APP_TRUSTED_MEDIA_HOST_SUFFIXES` 和 `APP_MEDIA_FAKE_IP_CIDRS` 调整。

## 模型目录出现 models/models

`MODELSCOPE_CACHE` 应指向 data root：

```env
MODELSCOPE_CACHE=/app/data
```

不要设置成：

```env
MODELSCOPE_CACHE=/app/data/models
```

否则部分依赖模型可能被放到多一层的 `models/models` 目录。

## 前端修改后页面没变化

生产模式由 FastAPI 托管 `frontend/dist`。修改前端后需要重新构建：

```bash
npm --prefix frontend run build
```

本地开发前端时可单独启动：

```bash
npm --prefix frontend run dev
```

## 上次中断的任务变成 failed

服务启动时会把上次中断的非终态任务标记为 `failed`，并清理过期 temp 目录。这是为了避免旧任务永久停留在运行中状态。
