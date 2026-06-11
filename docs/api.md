# API 说明

本文档面向需要通过程序或 Agent 调用服务的人。普通网页使用不需要阅读这里。

## 认证

如果 `API_AUTH_TOKEN` 为空，API 不需要认证。

如果配置了 `API_AUTH_TOKEN`，所有 `/api/*` 请求都需要：

```text
Authorization: Bearer <API_AUTH_TOKEN>
```

`GET /health` 不在 `/api/*` 下，用于基础健康检查。

## 任务接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/health` | 健康检查 |
| `GET` | `/api/capabilities` | 查看平台、依赖和 provider 可用性 |
| `POST` | `/api/jobs/upload` | 上传本地文件并创建任务 |
| `POST` | `/api/jobs` | 用链接创建任务 |
| `GET` | `/api/jobs` | 查询任务列表 |
| `GET` | `/api/jobs/{job_id}` | 查询单个任务状态 |
| `GET` | `/api/jobs/{job_id}/result` | 查询任务结果 |
| `POST` | `/api/jobs/{job_id}/retry` | 重试失败任务 |
| `DELETE` | `/api/jobs/{job_id}` | 删除任务 |
| `GET` | `/api/jobs/{job_id}/artifacts/{artifact_type}` | 下载任务产物 |
| `POST` | `/api/jobs/batch-delete` | 批量删除已结束任务 |
| `POST` | `/api/jobs/batch-export` | 批量导出任务 |

当前面向用户下载的产物类型：

| `artifact_type` | 内容 |
|---|---|
| `document_md` | Markdown 文稿 |
| `document_pdf` | PDF 文稿 |

`GET /api/capabilities` 中，`exports` 表示单任务导出类型，当前为：

```json
["document_md", "document_pdf"]
```

`batch_exports` 表示批量导出类型，当前为：

```json
["document_md", "document_pdf", "spreadsheet_xlsx"]
```

批量导出请求：

```http
POST /api/jobs/batch-export
Content-Type: application/json
```

```json
{
  "job_ids": ["job_xxx", "job_yyy"],
  "artifact_type": "spreadsheet_xlsx"
}
```

批量导出规则：

| `artifact_type` | 响应 |
|---|---|
| `document_md` | `.zip`，包含 Markdown 文件和 `_manifest.json` |
| `document_pdf` | `.zip`，包含 PDF 文件和 `_manifest.json` |
| `spreadsheet_xlsx` | 单个 `.xlsx` 工作簿，每行对应一条已完成任务 |

`spreadsheet_xlsx` 只导出已完成且存在结果的任务，不要求任务已生成 Markdown/PDF artifact。未完成、缺失或没有结果的任务会被跳过；如果没有任何可导出的任务，返回 `batch_export_empty`。

批量删除请求：

```http
POST /api/jobs/batch-delete
Content-Type: application/json
```

```json
{
  "job_ids": ["job_xxx", "job_yyy"]
}
```

批量删除只删除 `completed` 和 `failed` 任务。仍在排队或处理中的任务会出现在 `skipped` 中，不会被删除。

## 创作者主页接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/creator/preview` | 预览创作者主页下可转录的视频 |
| `POST` | `/api/creator/submit` | 根据预览结果批量创建任务 |

创作者主页导入依赖 TikHub。未配置 `TIKHUB_API_KEY` 时会返回配置缺失错误。

## 术语表接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/settings/terms` | 读取术语表 |
| `PUT` | `/api/settings/terms` | 保存术语表 |

术语表用于提高专有名词、人名、产品名等内容在转录和后处理中的一致性。

## 监控接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/metrics/overview` | 查看运行状态、资源快照、队列和最近任务概览 |
| `GET` | `/api/metrics/jobs` | 查询任务 metrics 列表 |

如果 `METRICS_ENABLED=false`，metrics API 会返回 disabled 状态。

## 错误结构

失败场景尽量返回稳定结构：

```json
{
  "code": "llm_provider_not_configured",
  "message": "当前任务需要 LLM provider，但未配置 API key。",
  "stage": "llm_processing"
}
```

常见错误码：

| 错误码 | 含义 |
|---|---|
| `llm_provider_not_configured` | 启用了 AI 校对或总结，但缺少 LLM key |
| `platform_provider_not_configured` | 提交的平台需要外部 provider，但缺少 key |
| `unsupported_platform` | 链接不是当前支持的平台 |
| `asr_failed` | ASR 转录失败 |
| `artifact_not_found` | 请求的产物不存在或文件丢失 |
| `job_not_found` | 任务不存在 |
| `job_not_retryable` | 当前任务状态不能重试 |
| `job_not_deletable` | 当前任务还未结束，不能删除 |
| `batch_export_empty` | 批量导出时没有任何可导出的任务 |
| `creator_profile_input` | 创作者主页链接被提交到了普通任务入口 |

具体请求体和响应字段以 `app/schemas.py` 中的 Pydantic schema 为准。
