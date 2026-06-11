# yc-media-transcriber

本地音视频转录助手。它把音频、视频和常见平台链接转成可阅读的文稿，并可以继续生成 AI 校对稿、总结、Markdown、PDF 和 Excel。

这个项目面向想直接处理素材的人，而不是只给开发者看的后端服务。你不需要先理解代码结构；能打开终端、愿意按几条命令操作，就可以使用。

![YC 音视频转录界面](docs/images/overview.jpg)

## 你可以用它做什么

- 把会议录音、课程视频、访谈、播客转成文字。
- 把 YouTube、Bilibili、小宇宙、公开媒体直链等内容转成文稿。
- 配置 TikHub 后处理抖音、小红书链接和创作者主页。
- 用术语表减少人名、产品名、专有名词被识别错的概率。
- 让 AI 对转录稿做校对、总结和结构化整理。
- 单个任务导出 Markdown 或 PDF；多个已完成任务批量导出 Markdown、PDF 或 Excel。

它默认是给你在自己的 Mac 上本地使用的工具，不是多人云服务，也不负责团队权限、计费、通知和跨平台安装体验。

## 你需要准备什么

| 你想做的事 | 需要准备 |
|---|---|
| 只转写本地音视频文件 | Docker Desktop、本项目代码 |
| 处理 YouTube、Bilibili、小宇宙或媒体直链 | 本机网络能访问目标内容 |
| 使用 AI 校对、总结、结构化整理 | DeepSeek 或其他兼容 OpenAI 接口的服务 key |
| 处理抖音、小红书或创作者主页 | TikHub key |
| 只试网页和任务流程 | 不需要外部 API key，可用 mock 模式 |

常用第三方服务入口：

| 服务 | 用途 | 地址 |
|---|---|---|
| DeepSeek API 平台 | 注册、充值、创建 LLM API key | [platform.deepseek.com](https://platform.deepseek.com/) |
| DeepSeek API 文档与价格 | 查看模型、接口和计费方式 | [api-docs.deepseek.com](https://api-docs.deepseek.com/) |
| TikHub 用户中心 | 注册、充值、创建 TikHub API token | [user.tikhub.io/login](https://user.tikhub.io/login) |
| TikHub API 文档 | 查看支持平台、Token 用法和国内外 API 地址 | [docs.tikhub.io](https://docs.tikhub.io/) |

未配置 key 时，相关任务会明确失败并提示原因，不会静默跳过后假装完成。

## 快速开始

进入项目目录后运行：

```bash
./scripts/deploy.sh
```

脚本会创建配置文件和数据目录，构建 Docker 镜像，并用默认 `2 CPU / 4 GB memory`、单任务并发启动本地容器。启动成功后，在浏览器打开：

```text
http://127.0.0.1:8000
```

如果 8000 端口被占用，可以换一个端口：

```bash
APP_PORT=8001 ./scripts/deploy.sh
```

第一次构建镜像和使用真实本地转录时，依赖安装和 FunASR 模型下载会比后续使用更久。请确认 Docker Desktop 至少分配了 2 核 CPU 和 4 GB 内存。

## 第一次使用

1. 打开 `http://127.0.0.1:8000`。
2. 上传本地音视频文件，或粘贴支持的平台链接。
3. 按需要开启“区分说话人”“LLM 校对”“内容总结”。
4. 提交任务并等待完成。
5. 在任务详情中查看结果，下载 Markdown 或 PDF 文稿。
6. 如果要整理多个任务，在任务列表中多选已完成任务，再批量导出 Excel。

## 支持的内容来源

| 内容来源 | 默认是否需要 API key | 说明 |
|---|---:|---|
| 本地音视频文件 | 否 | 适合录音、视频、会议素材 |
| 媒体直链 | 否 | 需要是可公开访问的音视频地址 |
| YouTube | 否 | 依赖本地下载工具；配置 TikHub 后可在部分失败场景兜底 |
| Bilibili | 否 | 默认走本地下载工具；配置 TikHub 后可在部分失败场景兜底 |
| 小宇宙 | 否 | 用于公开播客内容 |
| 抖音 | 是 | 需要配置 TikHub |
| 小红书 | 是 | 需要配置 TikHub |
| 创作者主页批量导入 | 是 | 目前通过 TikHub 预览和提交 |

## 文件保存在哪里

本地配置文件默认在：

```text
~/.yc-media-transcriber/.env
```

转录产物、缓存、上传文件、日志和模型默认在：

```text
~/.yc-media-transcriber/data
```

这些文件不会写进仓库目录。不要把真实 API key、用户媒体、转录结果、模型缓存或日志提交到 git。

## 常见问题

**启动后网页打不开**

先看终端里输出的 URL。如果提示端口被占用，用 `APP_PORT=8001 ./scripts/deploy.sh` 换端口。

**第一次转写很慢**

真实 ASR 首次运行可能需要安装依赖和下载模型。模型默认保存在 `~/.yc-media-transcriber/data/models`，后续任务会复用已下载模型。

**AI 校对或总结失败**

检查 `~/.yc-media-transcriber/.env` 里是否配置了 `LLM_API_KEY`。更多 LLM 选项见 [配置说明](docs/configuration.md)。

**抖音或小红书链接失败**

检查是否配置了 `TIKHUB_API_KEY`。在中国大陆网络下，也可以按 [配置说明](docs/configuration.md) 调整 TikHub 地址。

**我只想确认服务能不能跑**

使用 mock 模式启动：

```bash
ASR_ENGINE=mock ./scripts/deploy.sh
```

mock 模式不会做真实转录，适合检查网页、任务创建、任务列表和导出流程。

更多问题见 [排障说明](docs/troubleshooting.md)。

## Docker 运行参数

本地默认通过 Docker 运行。`deploy.sh` 会先构建镜像，再启动本地容器：

```bash
./scripts/deploy.sh
```

默认资源限制是 `2 CPU / 4 GB memory`，默认任务并发是 `1`。如果你确认机器资源足够，可以临时调整：

```bash
DOCKER_CPUS=4 DOCKER_MEMORY=8g TASK_QUEUE_MAX_CONCURRENCY=2 ./scripts/deploy.sh
```

Docker 会使用 `~/.yc-media-transcriber/.env` 和 `~/.yc-media-transcriber/data`。容器内的数据目录固定为 `/app/data`。

## 让 Agent 帮你部署

如果你要让 Codex、Claude Code、Cursor 这类工具帮你配置，可以把下面这段话交给它：

```text
请帮我在这台电脑上部署并启动 yc-media-transcriber。

请按这个顺序执行：

1. 先检查本机环境是否具备 Docker Desktop，并确认 Docker Desktop 至少分配了 2 核 CPU 和 4 GB 内存。如果缺少 Docker 或资源不足，先告诉我。
2. 创建或检查本地配置目录 ~/.yc-media-transcriber/，确认 ~/.yc-media-transcriber/.env 和 ~/.yc-media-transcriber/data 存在。
3. 引导我配置第三方服务 key：
   - DeepSeek：去 https://platform.deepseek.com/ 注册、充值并创建 API key，写入 LLM_API_KEY。
   - TikHub：去 https://user.tikhub.io/login 注册、充值并创建 API token，写入 TIKHUB_API_KEY。
   不要把我的 API key 打印到终端输出、聊天记录或 git diff 里。
4. 配置完成后，使用 ./scripts/deploy.sh 构建 Docker 镜像并启动服务。默认保持 TASK_QUEUE_MAX_CONCURRENCY=1。
5. 启动后用 curl 检查 http://127.0.0.1:8000 是否可访问，再帮我打开浏览器界面。
6. 不要提交 .env、.venv、frontend/dist、cases、logs、.tmp、~/.yc-media-transcriber/data、模型缓存、转录产物或任何 API key。

如果启动失败，请先根据 docs/troubleshooting.md 排查，并把失败原因、已尝试步骤和下一步建议用中文告诉我。
```

更多文档：

- [配置说明](docs/configuration.md)
- [API 说明](docs/api.md)
- [开发与测试](docs/development.md)
- [排障说明](docs/troubleshooting.md)
- [Excel 批量导出方案](docs/v1-excel-batch-export-plan.md)
