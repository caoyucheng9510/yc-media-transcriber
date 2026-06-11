# V1 Excel 批量导出方案

状态：已实现。本文保留为实现背景、行为边界和回归验收口径，不是待办清单。

## 结论

当前已经提供 `spreadsheet_xlsx` 批量导出类型，由后端直接生成一份 `.xlsx` 表格。用户在任务列表中选择一批已完成任务后，可以导出为一个工作簿；每行对应一条内容，前四列固定为 `链接`、`标题`、`总结`、`校对稿`。

作者作品不单独建导出模型。创作者主页提交后已经生成普通任务，并在任务 metadata 中保留 `creator_import` 信息，因此第一版复用任务多选导出即可。

## 用户行为

- 用户在任务列表勾选多个任务。
- 点击 `导出 Excel`。
- 后端跳过未完成、缺失或不可导出的任务。
- 如果至少有一条已完成任务可导出，返回一个 `.xlsx` 文件。
- 如果没有任何可导出的已完成任务，沿用现有 `batch_export_empty` 结构化错误。
- 用户打开 `.xlsx` 后复制整张表到飞书表格，行列应保持一致。

## 表格结构

工作簿只需要一个 sheet，建议命名为 `内容`。

固定列：

| 列名 | 取值 |
|---|---|
| `链接` | URL 任务写内容链接；本地上传任务固定写 `本地上传` |
| `标题` | 优先任务标题，其次 result metadata 标题，再其次 job id |
| `总结` | `result.summary`，为空写空字符串 |
| `校对稿` | 优先 `result.polished_text`；为空时按现有文稿导出逻辑从 `structured_transcript` 生成展示文本 |

链接取值优先级：

1. `result.metadata.creator_import.source_url`
2. `result.metadata.source_url`
3. `result.metadata.display_url`
4. 非上传任务的 `job.source_value`
5. 上传任务固定为 `本地上传`

校对稿续列：

- Excel 单元格最大字符数为 32767，校对稿可能超过这个限制。
- 实现时按安全阈值拆分校对稿，建议每段最多 30000 字符。
- 第一段写入 `校对稿`。
- 后续段按顺序写入 `校对稿_2`、`校对稿_3`、`校对稿_4` 等动态续列。
- 表头应按本次导出的最长校对稿段数动态生成，保证每一行列数一致。
- 拆分只处理 `校对稿` 字段；`总结` 第一版不拆列。

其他单元格长度规则：

- `链接`、`标题`、`总结` 不生成续列。
- 如果清理后的非校对稿字段超过 Excel 单元格限制，截断到 32767 字符以内，并在末尾追加 `[truncated]` 标记；截断后的最终字符串长度也必须不超过 32767。
- 非校对稿字段过长不返回错误，也不阻断整批导出。

示例：

| 链接 | 标题 | 总结 | 校对稿 | 校对稿_2 |
|---|---|---|---|---|
| `https://example.com/a` | `标题 A` | `摘要` | `前 30000 字` | `剩余文本` |
| `本地上传` | `sample.wav` | `摘要` | `完整校对稿` |  |

## 后端实现

### 依赖

`pyproject.toml` 的基础依赖包含：

```toml
"openpyxl>=3.1.0",
```

不放入 optional dependency。Excel 导出是用户可见基础功能，服务启动环境应默认具备。

### exporter

`app/exporters/spreadsheet.py` 的职责只包含表格导出相关逻辑：

- 从 `JobRecord` 提取一行导出数据。
- 提供统一的 `sanitize_cell_text()`，所有单元格字段都必须经过它处理。
- `sanitize_cell_text()` 负责清理 Excel 不接受的控制字符、把 `\r\n` / `\r` 归一为 `\n`、移除 tab。
- `sanitize_cell_text()` 负责防止公式注入：当单元格文本以 `=`、`+`、`-`、`@` 开头时，前置单引号，让表格软件按文本处理。
- `sanitize_cell_text()` 负责非校对稿字段截断，返回值必须不超过 Excel 单元格限制。
- `sanitize_cell_text()` 的处理顺序固定为：先归一换行并清理非法字符，再做公式注入保护，最后按最终字符串长度截断。
- 保留单元格内换行，避免复制到飞书表格时被拆成额外列。
- 拆分超长校对稿并生成 `校对稿_N` 续列。
- 使用 `openpyxl.Workbook` 写入 `BytesIO`。
- workbook 保存到 `BytesIO` 后先 `seek(0)` 再返回。
- 设置基础样式：冻结首行、首行加粗、自动筛选、文本换行、顶部对齐、合理列宽。

当前暴露函数：

```python
def build_batch_xlsx(jobs: list[JobRecord]) -> BytesIO:
    ...
```

exporter 只接收已经筛选后的 completed jobs，不负责 job 状态判断和跳过逻辑。

`app/exporters/formats.py` 里的校对稿兜底逻辑已抽成公共 helper：

```python
def document_polished_text(result: dict[str, Any]) -> str:
    ...
```

Markdown/PDF 和 Excel 共同使用这个 helper，确保 `polished_text` 为空但 `structured_transcript` 存在时，导出的展示文稿一致。

### schema

`BatchExportRequest.artifact_type` 已扩展为：

```python
Literal["document_md", "document_pdf", "spreadsheet_xlsx"]
```

`CapabilitiesResponse` 已新增 `batch_exports: list[str]`；`exports` 保持单任务产物语义。

前端类型同步扩展。

### API

复用现有 `POST /api/jobs/batch-export`。

当 `artifact_type == "spreadsheet_xlsx"`：

- 遍历去重后的 `job_ids`，保持请求体中的 job id 顺序。
- 只导出 `status == "completed"` 且 `job.result` 存在的任务。
- 不要求存在 `document_md` 或 `document_pdf` artifact。
- 返回单个 `.xlsx` 文件，不返回 zip。
- 文件名建议为 `transcripts-spreadsheet-YYYYMMDD-HHMMSS.xlsx`。
- `media_type` 使用：

```text
application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
```

内部跳过场景：

| 场景 | 处理 |
|---|---|
| job 不存在 | 跳过 |
| job 未完成 | 跳过 |
| completed 但缺少 result | 跳过 |

Excel 导出不返回跳过明细：如果只有部分任务被跳过，返回的 `.xlsx` 只包含可导出的行，不额外写 `_manifest` sheet，也不在响应体里返回 skipped 列表。跳过明细只在服务端分支内部用于判断是否还有可导出任务；如果全部跳过，仍返回 `batch_export_empty`。

现有 MD/PDF 批量导出继续返回 zip，并保留 `_manifest.json`。

### capabilities

`GET /api/capabilities` 中，`exports` 继续表示单任务产物类型，不加入 Excel：

```json
["document_md", "document_pdf"]
```

新增 `batch_exports` 表示批量导出类型：

```json
{
  "exports": ["document_md", "document_pdf"],
  "batch_exports": ["document_md", "document_pdf", "spreadsheet_xlsx"]
}
```

## 前端实现

单任务导出和批量导出使用不同的类型集合：

```ts
const singleJobExportTypes = ["document_md", "document_pdf"]
const batchExportTypes = ["document_md", "document_pdf", "spreadsheet_xlsx"]
```

任务详情和单任务导出菜单仍只显示 Markdown/PDF。

任务列表多选工具条提供：

- `导出 MD`
- `导出 PDF`
- `导出 Excel`

`导出 Excel` 调用同一个 `/api/jobs/batch-export`，请求体：

```json
{
  "job_ids": ["job_xxx"],
  "artifact_type": "spreadsheet_xlsx"
}
```

下载成功提示：

```text
已下载 Excel 表格；未完成或不可导出的任务会被自动跳过。
```

## 已同步文档

实现时已同步：

- `README.md`：说明单任务仍导出 Markdown/PDF，批量导出增加 Excel。
- `docs/api.md`：补充 `batch_exports` 和 `spreadsheet_xlsx` 批量导出说明。
- 如新增测试命令或依赖安装说明，继续更新 `docs/development.md`。

## 回归计划

后端单测：

- `tests/unit/test_exporters.py`
  - 生成的 workbook 包含固定表头。
  - URL 任务链接取 `creator_import.source_url` 优先。
  - 本地上传任务链接列写 `本地上传`。
  - `polished_text` 为空时能从 `structured_transcript` 兜底生成校对稿。
  - 校对稿超过阈值时生成 `校对稿_2`、`校对稿_3` 等续列。
  - 以 `=`、`+`、`-`、`@` 开头的文本不会被作为公式。
  - `sanitize_cell_text()` 会归一换行、移除 tab、移除 Excel 不接受的控制字符。
  - 非校对稿字段超过 Excel 单元格限制时被截断，并包含 `[truncated]` 标记。

API 测试：

- `tests/api/test_api.py`
  - `spreadsheet_xlsx` 返回 `.xlsx` MIME type。
  - 用 `openpyxl.load_workbook(BytesIO(response.content))` 回读，断言行列内容。
  - 保持请求体中的 job id 顺序。
  - 跳过 failed / queued / missing job / completed 但缺少 result 的任务。
  - 部分跳过时，`.xlsx` 只包含可导出的行，不包含 `_manifest` sheet 或 skipped 列表。
  - 如果全部跳过，返回 `batch_export_empty`。
  - `GET /api/capabilities` 中 `exports` 仍为单任务 Markdown/PDF，`batch_exports` 包含 `spreadsheet_xlsx`。

前端验证：

- `npm --prefix frontend run build`
- 在任务列表多选已完成任务，点击 `导出 Excel`，确认浏览器下载 `.xlsx`。
- 打开表格，复制整张 sheet 到飞书表格，确认：
  - 行数一致。
  - 列数一致。
  - 单元格内换行不会拆成新行或新列。
  - 超长校对稿被拆到 `校对稿_N` 续列。

回归命令：

```bash
.venv/bin/python -m pytest tests/unit/test_exporters.py tests/api/test_api.py
npm --prefix frontend run build
```

完整回归：

```bash
.venv/bin/python -m pytest
```

## 不做范围

- 不新增独立的作者作品导出 API。
- 不给每个单任务生成独立 `.xlsx` artifact。
- 不把 Excel 导出写入 `result["artifacts"]`。
- 不引入前端表格生成逻辑。
- 不为 Excel 导出新增异步任务或缓存。
- 不改变现有 Markdown/PDF 单任务产物生成流程。

## 验收标准

- 选择一批 completed 任务可以下载 `.xlsx`。
- `.xlsx` 每行对应一条内容。
- 表格至少包含 `链接`、`标题`、`总结`、`校对稿` 四列。
- 本地上传任务的 `链接` 列显示 `本地上传`。
- 超长校对稿不会被截断，按 `校对稿_2`、`校对稿_3` 等续列保存。
- 复制整张表到飞书表格后行列保持一致。
- 未完成任务不会导致整个导出失败。
- 没有任何可导出任务时返回结构化错误。
