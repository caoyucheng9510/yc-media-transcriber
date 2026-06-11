# AGENTS.md

本文件适用于仓库根目录及所有子目录。除非用户另有明确要求，后续在本项目内工作时遵守以下约定。

## 项目定位与边界

- 本项目是本地单用户音视频转录服务，核心形态是本地 Web UI + Agent 可调用 API。
- 支持本地文件、媒体直链、YouTube、Bilibili、小宇宙；抖音和小红书通过 TikHub provider 支持。
- 默认技术栈是 Python 3.11+、FastAPI、SQLite、文件系统、ffmpeg/ffprobe、yt-dlp、FunASR、OpenAI-compatible API、Vite + React + Tailwind CSS v4 + shadcn/ui。
- Web 页面是本地工具界面，优先清晰、直接、可操作；不要做营销式落版或装饰性页面。

## 项目结构与模块组织

- 核心代码位于 `app/`，当前仓库不使用 `src/` 包布局。
- `app/main.py` 负责 `create_app()`、生命周期初始化和路由挂载；测试应优先通过 `create_app(settings)` 注入配置。
- `app/config.py` 是配置入口；新增配置项时同步更新 `Settings`、`load_settings()`、`.env.example`、`README.md` 或相关文档。
- `app/dependencies.py` 放应用依赖装配逻辑，避免把 store、queue、settings 的创建散落到路由中。
- `app/api/` 负责 JSON API 路由、请求校验、认证检查和错误响应映射。
- `app/web/` 负责本地 Web UI 路由和 SPA 入口，不在这里混入前端页面实现。
- `frontend/` 负责 Vite React 本地 Web UI；生产模式由 FastAPI 托管 `frontend/dist`，不要手改生成后的 `dist` 文件。
- `app/source_resolver/` 负责识别输入来源、平台类型、URL 安全校验和 source fingerprint。
- `app/downloaders/` 存放多平台下载适配器；平台选择通过 `DownloaderFactory` 处理。
- `app/media/` 负责 ffmpeg/ffprobe 音频抽取、规范化和媒体有效性检查。
- `app/asr/` 负责 ASR 引擎抽象、mock 引擎和 FunASR 实现；mock ASR 只允许用于自动化测试，不得用于日常开发、手动验收或用户可见运行。
- `app/llm/` 负责 LLM provider 调用、转录润色、摘要和结构化文本处理。
- `app/jobs/` 负责任务队列、任务状态流转、主处理流程和产物写入。
- `app/storage/` 管理 SQLite 持久化；运行期数据、SQLite 文件、缓存和转录产物不应进入补丁。
- `app/exporters/` 负责用户可下载产物和批量导出；当前单任务产物为 `document_md`、`document_pdf`，批量表格导出为即时生成的 `spreadsheet_xlsx`。
- `app/terminology/` 负责术语表存储、读取和匹配相关逻辑。
- `app/capabilities.py` 负责对外暴露平台、依赖和 provider 可用性；外部依赖变化时需要同步更新。
- `app/schemas.py` 放 API 输入输出 schema 和任务状态类型；新增用户可见字段时同步更新 API/Web 展示和测试。
- `app/errors.py` 维护结构化错误；新增失败场景优先使用 `AppError`，保持 `code`、`message`、`stage` 结构稳定。
- `tests/` 统一放自动化测试，当前按 `unit/`、`api/`、`source_resolver/`、`downloaders/`、`llm/` 等范围组织。
- `docs/` 放需求、技术方案和开发计划；架构或验收口径变化时同步更新相关文档。
- `scripts/` 放本地启动和运维辅助脚本；脚本输出保持英文和 ASCII。
- `docker/` 放容器构建配置；Mac 本地容器运行统一通过 `scripts/deploy.sh`。
- `cases/`、`.tmp/`、`logs/`、`data/`、`.venv/`、`*.egg-info/`、`__pycache__/` 等为本地产物或运行数据，不应提交。

## 架构与流程约定

- 主流程保持为：`SourceResolver` -> `Downloader` 或本地上传 -> `normalize_audio` -> `Transcriber` -> `LLMProcessor` -> `write_job_artifacts` -> `SQLiteStore`。
- 任务状态使用固定集合：`queued`、`downloading`、`normalizing`、`transcribing`、`llm_processing`、`completed`、`failed`。
- 错误结构保持为 `code`、`message`、`stage`；不要只抛普通异常并丢失阶段信息。
- `SQLiteStore` 保存任务、产物索引、缓存和设置；实际文件保存在 `APP_DATA_DIR` 下的 `uploads`、`temp`、`jobs`、`cache`、`models`、`logs` 等目录。
- 容器内默认数据目录是 `/app/data`；Mac 本地默认使用 `~/.yc-media-transcriber/data`。
- 优先沿用当前模块边界，不为小改动引入 Celery、Redis、ORM、前端框架或新的配置系统。
- 新增平台解析器时，至少同步更新 `SourceResolver`、`DownloaderFactory`、`build_capabilities`、结构化错误和相关测试。
- 新增任务结果字段时，同步更新 `schemas`、`write_job_artifacts`、API/Web 展示和测试。

## 实现原则

### YAGNI：用不到的不做

- 只实现当前明确需求，不为未来可能扩展提前增加抽象、接口、配置开关或占位逻辑。
- 当前只有一种实现时，优先写直接代码；只有出现真实重复需求或多实现需求时，才提取抽象。
- 不添加“未来支持某功能”的 TODO、预留参数或未接入的空逻辑。

### KISS：保持简单直白

- 优先使用现有模块、现有 helper 和平铺直叙的代码。
- 能用普通函数清楚表达的逻辑，不新增类；只有需要保存状态、表达数据模型或对接既有生命周期时，才使用类。
- 小改动不引入 Celery、Redis、ORM、前端框架、新配置系统或新的设计模式。
- 复杂逻辑优先拆成职责清楚的小函数，避免深层嵌套和难以解释的通用封装。

### 命名即设计

- 命名应准确表达业务边界和行为意图。
- 函数名优先使用明确的动词加对象；变量名避免在较大作用域中使用 `data`、`info`、`process`、`manager` 等泛名。
- 如果一个函数或变量很难命名，优先检查是否承担了过多职责。

### 快速失败

- 在入口处尽早校验参数、配置、依赖和外部 provider 状态。
- 配置缺失、参数非法、依赖不可用时，应返回结构化错误或抛出 `AppError`。
- 报错信息应包含导致失败的关键值或上下文；但不得泄露 API key、token、cookie、完整用户媒体路径或大段隐私内容。
- 不吞掉异常；捕获异常时必须保留原因，并转换为稳定的 `code`、`message`、`stage` 结构，不能静默跳过后标记成功。

## 构建、测试与开发命令

默认使用项目本地 `.venv`，不要向全局 Python 或 user-site 安装依赖。

初始化开发环境：

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
```

启动本地开发服务：

```bash
./scripts/dev-server.sh
```

`dev-server.sh` 是本地调试的唯一脚本入口。它会自动创建项目内 `.venv`、安装缺失依赖、创建 `~/.yc-media-transcriber/.env` 和 `data` 目录，并真实启动服务。模型目录默认使用 `~/.yc-media-transcriber/data/models`，不要把 FunASR 模型缓存放进仓库。

日常开发和验收必须直接使用真实 ASR 配置启动，不要为了避免依赖安装、模型下载或缩短等待时间而设置 `ASR_ENGINE=mock`。如果真实 ASR 依赖或模型缺失，应如实安装、下载或说明阻塞。

安装真实 FunASR 依赖：

```bash
uv pip install --python .venv/bin/python -e '.[asr]'
```

运行最小回归：

```bash
.venv/bin/python -m pytest
```

分阶段验收：

```bash
.venv/bin/python -m pytest tests/unit tests/api
.venv/bin/python -m pytest tests/unit tests/api tests/llm
.venv/bin/python -m pytest tests/source_resolver tests/downloaders tests/api
docker build -t yc-media-transcriber:latest -f docker/Dockerfile .
```

Docker 验证：

```bash
docker build -t yc-media-transcriber:latest -f docker/Dockerfile .
./scripts/deploy.sh
```

依赖维护：

```bash
uv pip install --python .venv/bin/python -e '.[dev]'
uv pip install --python .venv/bin/python -e '.[asr]'
```

新增 Python 依赖时，更新 `pyproject.toml` 的 `dependencies` 或 `optional-dependencies`，再用项目本地 `.venv` 验证安装和测试。

## 编码风格与命名约定

- 目标 Python 版本为 3.11+。
- 遵循 PEP 8，使用 4 空格缩进。
- 模块、函数、变量使用 `snake_case`；类名使用 `PascalCase`；常量使用 `UPPER_SNAKE_CASE`。
- 跨模块接口、配置对象、API schema、任务状态和返回结构优先添加类型标注。
- API 输入输出模型放在 `app/schemas.py`，优先使用 Pydantic `BaseModel` 和明确的 `Literal`/字段默认值。
- 内部简单值对象可使用 `dataclass`；涉及 API 边界时优先使用 Pydantic schema。
- 配置读取集中在 `app/config.py`，不要在业务模块里散落新的环境变量解析逻辑。
- 失败场景优先使用 `AppError`，错误码应稳定、可测试、能被 API 和 Web 共同消费。
- 服务代码避免随意 `print`；如需日志，使用标准 logging，并避免输出 API key、token、cookie、用户媒体路径和完整隐私内容。
- console、测试、脚本输出使用英文和 ASCII，避免中文、emoji 和不稳定装饰字符。
- 文件路径优先使用 `pathlib.Path`，文本读写明确 UTF-8。
- 新功能优先复用相关子包内已有 helper，避免把下载、转录、LLM、缓存、术语表和 Web 展示逻辑互相耦合。

## 测试规范

- 优先使用 pytest，测试文件命名为 `test_*.py`。
- 默认测试不得依赖真实 FunASR、DeepSeek、TikHub key、YouTube/Bilibili 网络下载或用户私有媒体。
- API/Web 测试优先使用 `Settings(app_process_jobs_inline=True, asr_engine="mock")`，避免异步后台线程和真实外部依赖影响断言。
- 手动验收、日常开发服务和交付给用户查看的运行界面不得使用 mock ASR；只有自动化测试可以使用 `asr_engine="mock"` 或 fake/mock provider。
- 涉及媒体文件的测试可以使用 `ffmpeg` 生成短样本；不要引入参考项目或用户私有媒体作为测试夹具。
- 临时媒体、下载产物和缓存应写入 `tmp_path`、`.tmp/`、`cases/` 或其他已忽略目录，避免污染 `APP_DATA_DIR` 和仓库根目录。
- 修改共享逻辑、跨模块协议、API 输出结构、任务状态、导出格式或用户可见页面时，应补充或更新对应测试。
- 新增平台解析器时，至少覆盖平台识别、能力展示、下载器选择、配置缺失、错误结构和成功路径的 mock 测试。
- 新增 LLM 或 ASR 行为的自动化测试时，默认通过 fake/mock provider 验证，不把真实外部服务作为单测前提。
- 需要外部凭据、真实音视频、大文件或网络环境的验证，应明确标为手动验证，不纳入默认最小回归。
- 添加新的测试目录、运行前置条件或命令时，同步更新 `README.md`、`docs/` 或本文件。

## 配置与安全

- 配置来源包括 `~/.yc-media-transcriber/.env`、当前目录 `.env`、`APP_ENV_FILE` 和运行时环境变量；运行时环境变量优先级最高。
- 不要提交真实 API key、cookie、token、用户配置、模型缓存、转录产物、日志、SQLite 数据库或用户媒体文件。
- 未配置有效 LLM key 时，如果任务启用 `llm_polish` 或 `summary`，应返回 `llm_provider_not_configured`，不能静默跳过并标记成功。`LLM_PROVIDER=deepseek` 时使用 `LLM_API_KEY`。
- 未配置 `TIKHUB_API_KEY` 时，抖音和小红书任务应返回 `platform_provider_not_configured`；`GET /api/capabilities` 也应标记不可用。
- YouTube 和 Bilibili 依赖 `yt-dlp`；能力接口要如实反映依赖是否可用。
- 直链下载必须经过 SSRF 校验，默认阻止私网、回环和本机地址。
- 平台链接可跳过 DNS 解析式校验，但仍需识别为受支持平台；未知平台返回 `unsupported_platform`。
- 下载器处理重定向时必须重新校验目标 URL。
- 除非用户明确要求并理解风险，不要默认开启 `APP_ALLOW_PRIVATE_URLS`。
- 修改配置结构时，同步更新 `Settings`、`load_settings()`、`.env.example`、`README.md` 或相关文档。
- 提交前检查 `git status --short --ignored`，确认 `.tmp/`、`logs/`、`cases/`、`.venv/`、`__pycache__/`、`*.egg-info/` 等只作为 ignored 本地产物存在。

## 提交与 PR 规范

- 每次提交聚焦一组相关改动，避免混入无关格式化、临时文件、运行数据或调试输出。
- 提交信息采用 Angular 风格：`type(scope): 中文描述`。
- 推荐示例：`fix(downloaders): 校验重定向目标地址`、`test(api): 补充任务导出测试`、`docs(agents): 重构项目规范文档`。
- 涉及破坏性变更时，在提交正文或 footer 中明确写 `BREAKING CHANGE:`，后面用中文说明影响和迁移方式。
- 提交前至少运行与改动范围匹配的测试；如果没有运行测试，在交付说明中明确说明原因。
- 涉及配置、schema、任务状态、导出格式、外部依赖或数据目录变化时，需要在提交说明、PR 描述或交付说明中明确标出。
- PR 描述应说明改动范围、配置或 schema 变更、关联 issue、验证证据和后续注意事项。
