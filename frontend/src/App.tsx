import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  Activity,
  AlertCircle,
  ArrowDownToLine,
  ChevronDown,
  CircleCheck,
  CircleDashed,
  Clock3,
  Copy,
  Cpu,
  Eye,
  FileAudio,
  FileSpreadsheet,
  FileText,
  HardDrive,
  Link2,
  ListChecks,
  Loader2,
  Plus,
  RefreshCcw,
  Search,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Upload,
  UserRound,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { ApiError, apiRequest, downloadFile, downloadFileFromRequest } from "@/lib/api"
import { cn } from "@/lib/utils"
import type {
  BatchDeleteResponse,
  BatchExportArtifactType,
  CapabilitiesResponse,
  CreatorPreviewResponse,
  CreatorSubmitResponse,
  CreatorWorkItem,
  ErrorInfo,
  JobListResponse,
  JobOptions,
  JobRecord,
  JobResult,
  JobStatus,
  MetricsJob,
  MetricsJobsResponse,
  MetricsOverview,
  Term,
  TermsPayload,
} from "@/types"

type Route =
  | { name: "dashboard" }
  | { name: "metrics" }
  | { name: "settings" }

type Notice = {
  tone: "success" | "error" | "info"
  text: string
}

type ServiceStatus = "checking" | "online" | "offline"

const terminalStatuses: JobStatus[] = ["completed", "failed"]
const singleJobExportTypes = ["document_md", "document_pdf"]
const batchExportTypes = [
  { type: "document_md", label: "导出 MD", icon: ArrowDownToLine },
  { type: "document_pdf", label: "导出 PDF", icon: ArrowDownToLine },
  { type: "spreadsheet_xlsx", label: "导出 Excel", icon: FileSpreadsheet },
] satisfies Array<{ type: BatchExportArtifactType; label: string; icon: typeof ArrowDownToLine }>
const NOTICE_AUTO_DISMISS_MS = 4000

const statusMeta: Record<
  JobStatus,
  { label: string; className: string; icon: typeof CircleDashed }
> = {
  queued: {
    label: "queued",
    className: "border-stone-300 bg-stone-100 text-stone-700",
    icon: Clock3,
  },
  downloading: {
    label: "downloading",
    className: "border-sky-200 bg-sky-50 text-sky-700",
    icon: Loader2,
  },
  normalizing: {
    label: "normalizing",
    className: "border-sky-200 bg-sky-50 text-sky-700",
    icon: Loader2,
  },
  transcribing: {
    label: "transcribing",
    className: "border-amber-200 bg-amber-50 text-amber-800",
    icon: Loader2,
  },
  llm_processing: {
    label: "llm_processing",
    className: "border-amber-200 bg-amber-50 text-amber-800",
    icon: Sparkles,
  },
  completed: {
    label: "completed",
    className: "border-emerald-200 bg-emerald-50 text-emerald-800",
    icon: CircleCheck,
  },
  failed: {
    label: "failed",
    className: "border-red-200 bg-red-50 text-red-700",
    icon: AlertCircle,
  },
}

function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute())
  const [jobs, setJobs] = useState<JobRecord[]>([])
  const [capabilities, setCapabilities] = useState<CapabilitiesResponse | null>(null)
  const [apiToken, setApiToken] = useState(() => sessionStorage.getItem("apiToken") || "")
  const [authInput, setAuthInput] = useState(apiToken)
  const [authRequired, setAuthRequired] = useState(false)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [serviceStatus, setServiceStatus] = useState<ServiceStatus>("checking")
  const [dashboardSelectedJobId, setDashboardSelectedJobId] = useState<string | undefined>()
  const [detailJob, setDetailJob] = useState<JobRecord | null>(null)
  const [detailResult, setDetailResult] = useState<JobResult | null>(null)
  const [detailError, setDetailError] = useState<ErrorInfo | null>(null)
  const [retryingJobIds, setRetryingJobIds] = useState<Set<string>>(() => new Set())
  const [batchDeleteJobIds, setBatchDeleteJobIds] = useState<string[] | null>(null)
  const [batchDeleting, setBatchDeleting] = useState(false)

  useEffect(() => {
    const onPopState = () => setRoute(parseRoute())
    window.addEventListener("popstate", onPopState)
    return () => window.removeEventListener("popstate", onPopState)
  }, [])

  const navigate = useCallback((path: string) => {
    window.history.pushState({}, "", path)
    setRoute(parseRoute())
  }, [])

  const request = useCallback(
    <T,>(path: string, options?: RequestInit) =>
      apiRequest<T>(path, {
        ...options,
        token: apiToken,
      }),
    [apiToken],
  )

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [jobPayload, capabilityPayload] = await Promise.all([
        request<JobListResponse>("/api/jobs?limit=100"),
        request<CapabilitiesResponse>("/api/capabilities"),
      ])
      setJobs(jobPayload.items)
      setCapabilities(capabilityPayload)
      setAuthRequired(false)
      setServiceStatus("online")
    } catch (error) {
      if (isNetworkError(error)) {
        setServiceStatus("offline")
      }
      handleRequestError(error, setAuthRequired, setNotice)
    } finally {
      setLoading(false)
    }
  }, [request])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    if (!notice) {
      return
    }
    const timer = window.setTimeout(() => setNotice(null), NOTICE_AUTO_DISMISS_MS)
    return () => window.clearTimeout(timer)
  }, [notice])

  useEffect(() => {
    if (serviceStatus === "offline" || !jobs.some((job) => !terminalStatuses.includes(job.status))) {
      return
    }
    const timer = window.setInterval(() => {
      void refresh()
    }, 3000)
    return () => window.clearInterval(timer)
  }, [jobs, refresh, serviceStatus])

  useEffect(() => {
    if (route.name !== "dashboard") {
      return
    }
    if (dashboardSelectedJobId && jobs.some((job) => job.id === dashboardSelectedJobId)) {
      return
    }
    setDashboardSelectedJobId(jobs[0]?.id)
  }, [dashboardSelectedJobId, jobs, route.name])

  const selectedJobId = dashboardSelectedJobId
  const selectedFromList = useMemo(
    () => jobs.find((job) => job.id === selectedJobId) || null,
    [jobs, selectedJobId],
  )
  const selectedListVersion = selectedFromList
    ? `${selectedFromList.status}:${selectedFromList.updated_at}`
    : "not-in-list"

  const fetchJobDetail = useCallback(
    async (jobId: string) => {
      const job = await request<JobRecord>(`/api/jobs/${jobId}`)
      const resultPayload = await request<JobResult | { status: JobStatus; error?: ErrorInfo | null }>(
        `/api/jobs/${jobId}/result`,
      )
      if ("raw_transcript" in resultPayload) {
        return { job, result: resultPayload, error: null }
      }
      return { job, result: null, error: resultPayload.error || job.error || null }
    },
    [request],
  )

  const applyJobDetail = useCallback(
    ({ job, result, error }: { job: JobRecord; result: JobResult | null; error: ErrorInfo | null }) => {
      setDetailJob(job)
      setDetailResult(result)
      setDetailError(error)
    },
    [],
  )

  useEffect(() => {
    if (!selectedJobId) {
      setDetailJob(null)
      setDetailResult(null)
      setDetailError(null)
      return
    }

    const jobId = selectedJobId
    let active = true
    async function loadDetail() {
      try {
        const detail = await fetchJobDetail(jobId)
        if (!active) {
          return
        }
        applyJobDetail(detail)
      } catch (error) {
        if (active) {
          handleRequestError(error, setAuthRequired, setNotice)
        }
      }
    }

    void loadDetail()
    return () => {
      active = false
    }
  }, [applyJobDetail, fetchJobDetail, selectedJobId, selectedListVersion])

  const saveToken = () => {
    const nextToken = authInput.trim()
    if (nextToken) {
      sessionStorage.setItem("apiToken", nextToken)
    } else {
      sessionStorage.removeItem("apiToken")
    }
    setApiToken(nextToken)
    setNotice({ tone: "info", text: nextToken ? "API token 已保存到当前浏览器会话。" : "API token 已清除。" })
  }

  const createUploadJob = async (file: File, options: JobOptions) => {
    const form = new FormData()
    form.append("file", file)
    form.append("options", JSON.stringify(options))
    const response = await request<{ job_id: string; view_url: string }>("/api/jobs/upload", {
      method: "POST",
      body: form,
    })
    await refresh()
    setDashboardSelectedJobId(response.job_id)
    navigate("/")
    setNotice({ tone: "success", text: `已创建任务 ${response.job_id}。` })
  }

  const createUrlJob = async (value: string, options: JobOptions) => {
    const response = await request<{ job_id: string; view_url: string }>("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: { type: "text", value },
        options,
      }),
    })
    await refresh()
    setDashboardSelectedJobId(response.job_id)
    navigate("/")
    setNotice({ tone: "success", text: `已创建任务 ${response.job_id}。` })
  }

  const previewCreator = async (value: string, maxItems: number) => {
    return request<CreatorPreviewResponse>("/api/creator/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        platform: "auto",
        input: value,
        max_items: maxItems,
        max_pages: 3,
        page_size: 20,
      }),
    })
  }

  const submitCreator = async (previewId: string, selectedItemIds: string[], options: JobOptions) => {
    const response = await request<CreatorSubmitResponse>("/api/creator/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        preview_id: previewId,
        selected_item_ids: selectedItemIds,
        options,
      }),
    })
    await refresh()
    const firstJobId = response.created[0]?.job_id
    if (firstJobId) {
      setDashboardSelectedJobId(firstJobId)
      navigate("/")
    }
    const skippedText = response.skipped.length ? `，跳过 ${response.skipped.length} 个` : ""
    setNotice({ tone: "success", text: `已创建 ${response.created.length} 个任务${skippedText}。` })
  }

  const onDownload = async (jobId: string, artifactType: string) => {
    try {
      await downloadFile(`/api/jobs/${jobId}/artifacts/${artifactType}`, apiToken)
    } catch (error) {
      handleRequestError(error, setAuthRequired, setNotice)
    }
  }

  const batchDownload = async (jobIds: string[], artifactType: BatchExportArtifactType) => {
    try {
      await downloadFileFromRequest(
        "/api/jobs/batch-export",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_ids: jobIds, artifact_type: artifactType }),
        },
        apiToken,
      )
      const noticeText =
        artifactType === "spreadsheet_xlsx"
          ? "已下载 Excel 表格；未完成或不可导出的任务会被自动跳过。"
          : `已下载 ${artifactShortLabel(artifactType)} 导出包；跳过明细见包内 _manifest.json。`
      setNotice({
        tone: "success",
        text: noticeText,
      })
    } catch (error) {
      handleRequestError(error, setAuthRequired, setNotice)
    }
  }

  const batchDeleteSummary = useMemo(() => {
    if (!batchDeleteJobIds) {
      return { totalCount: 0, deletableCount: 0, skippedCount: 0 }
    }
    const selectedJobs = jobs.filter((job) => batchDeleteJobIds.includes(job.id))
    const deletableCount = selectedJobs.filter((job) => terminalStatuses.includes(job.status)).length
    return {
      totalCount: batchDeleteJobIds.length,
      deletableCount,
      skippedCount: batchDeleteJobIds.length - deletableCount,
    }
  }, [batchDeleteJobIds, jobs])

  const requestBatchDeleteJobs = async (jobIds: string[]) => {
    const uniqueJobIds = [...new Set(jobIds)]
    if (uniqueJobIds.length === 0) {
      return
    }
    setBatchDeleteJobIds(uniqueJobIds)
  }

  const confirmBatchDeleteJobs = async () => {
    if (!batchDeleteJobIds) {
      return
    }
    setBatchDeleting(true)
    try {
      const response = await request<BatchDeleteResponse>("/api/jobs/batch-delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_ids: batchDeleteJobIds }),
      })
      if (selectedJobId && response.deleted.includes(selectedJobId)) {
        setDashboardSelectedJobId(undefined)
        setDetailJob(null)
        setDetailResult(null)
        setDetailError(null)
      }
      await refresh()
      const skippedResponseText = response.skipped.length ? `，跳过 ${response.skipped.length} 个` : ""
      setNotice({ tone: "success", text: `已删除 ${response.deleted.length} 个任务${skippedResponseText}。` })
      setBatchDeleteJobIds(null)
    } catch (error) {
      handleRequestError(error, setAuthRequired, setNotice)
    } finally {
      setBatchDeleting(false)
    }
  }

  const selectJob = useCallback(
    (jobId: string) => {
      setDashboardSelectedJobId(jobId)
      if (route.name === "settings") {
        navigate("/")
      }
    },
    [navigate, route.name],
  )

  const retryJob = async (jobId: string) => {
    setRetryingJobIds((current) => new Set(current).add(jobId))
    setJobs((current) =>
      current.map((job) =>
        job.id === jobId
          ? { ...job, status: "queued", progress: 0, error: null, result: null }
          : job,
      ),
    )
    if (selectedJobId === jobId) {
      setDetailJob((current) =>
        current?.id === jobId
          ? { ...current, status: "queued", progress: 0, error: null, result: null }
          : current,
      )
      setDetailResult(null)
      setDetailError(null)
    }
    setNotice({ tone: "info", text: `正在重试任务 ${jobId}。` })
    try {
      await request<{ job_id: string; view_url: string }>(`/api/jobs/${jobId}/retry`, {
        method: "POST",
      })
      await refresh()
      const detail = await fetchJobDetail(jobId)
      applyJobDetail(detail)
      selectJob(jobId)
      if (detail.job.status === "failed") {
        setNotice({
          tone: "error",
          text: `重试已执行，但任务仍失败：${shortErrorMessage(detail.error?.message || "任务处理失败。")}`,
        })
      } else {
        setNotice({ tone: "success", text: `已重新提交任务 ${jobId}。` })
      }
    } catch (error) {
      handleRequestError(error, setAuthRequired, setNotice)
    } finally {
      setRetryingJobIds((current) => {
        const next = new Set(current)
        next.delete(jobId)
        return next
      })
    }
  }

  const deleteJob = async (jobId: string) => {
    const job = jobs.find((item) => item.id === jobId)
    const label = job?.title || (job ? filename(job.source_value) : jobId)
    if (!window.confirm(`删除任务 ${label}？此操作会移除任务记录和本地产物。`)) {
      return
    }
    try {
      await request<void>(`/api/jobs/${jobId}`, { method: "DELETE" })
      if (dashboardSelectedJobId === jobId) {
        setDashboardSelectedJobId(undefined)
      }
      setDetailJob(null)
      setDetailResult(null)
      setDetailError(null)
      await refresh()
      setNotice({ tone: "success", text: `已删除任务 ${jobId}。` })
    } catch (error) {
      handleRequestError(error, setAuthRequired, setNotice)
    }
  }

  const detailMatchesSelection = detailJob?.id === selectedJobId
  const detailMatchesListVersion =
    detailMatchesSelection && (!selectedFromList || detailJob?.updated_at === selectedFromList.updated_at)
  const currentJob = selectedFromList || (detailMatchesSelection ? detailJob : null)
  const currentResult = detailMatchesListVersion ? detailResult : currentJob?.result || null
  const currentError =
    currentJob?.status === "failed"
      ? (detailMatchesListVersion ? detailError : null) || currentJob.error || null
      : null

  return (
    <div className="min-h-screen">
      <AppHeader
        route={route}
        capabilities={capabilities}
        serviceStatus={serviceStatus}
        authRequired={authRequired}
        onNavigate={navigate}
      />

      <main className="mx-auto flex w-full max-w-[1520px] flex-col gap-4 px-4 py-5 md:px-6 lg:px-8">
        {(authRequired || capabilities?.auth.enabled) && (
          <AuthPanel
            authRequired={authRequired}
            value={authInput}
            onChange={setAuthInput}
            onSave={saveToken}
          />
        )}

        {notice && <NoticeBanner notice={notice} onDismiss={() => setNotice(null)} />}

        {route.name === "settings" ? (
          <SettingsView
            capabilities={capabilities}
            token={apiToken}
            onAuthError={() => setAuthRequired(true)}
            onNotice={setNotice}
          />
        ) : route.name === "metrics" ? (
          <MetricsView
            token={apiToken}
            onAuthError={() => setAuthRequired(true)}
            onNotice={setNotice}
            onServiceStatusChange={setServiceStatus}
          />
        ) : (
          <>
            <section className="grid gap-4">
              <NewJobPanel
                onCreateUpload={createUploadJob}
                onCreateUrl={createUrlJob}
                onPreviewCreator={previewCreator}
                onSubmitCreator={submitCreator}
                onError={(error) => handleRequestError(error, setAuthRequired, setNotice)}
              />
            </section>

            <section className="grid gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(420px,0.75fr)]">
              <JobsTable
                jobs={jobs}
                selectedJobId={selectedJobId}
                loading={loading}
                onRefresh={refresh}
                onSelectJob={selectJob}
                onDownload={onDownload}
                onBatchDownload={batchDownload}
                onRetry={retryJob}
                onDelete={deleteJob}
                onBatchDelete={requestBatchDeleteJobs}
                retryingJobIds={retryingJobIds}
              />
              <JobDetailPanel
                job={currentJob}
                result={currentResult}
                error={currentError}
                onDownload={onDownload}
                onCopy={(text) => void navigator.clipboard.writeText(text)}
              />
            </section>
          </>
        )}
      </main>
      <BatchDeleteDialog
        open={batchDeleteJobIds !== null}
        totalCount={batchDeleteSummary.totalCount}
        deletableCount={batchDeleteSummary.deletableCount}
        skippedCount={batchDeleteSummary.skippedCount}
        deleting={batchDeleting}
        onCancel={() => {
          if (!batchDeleting) {
            setBatchDeleteJobIds(null)
          }
        }}
        onConfirm={confirmBatchDeleteJobs}
      />
    </div>
  )
}

function BatchDeleteDialog({
  open,
  totalCount,
  deletableCount,
  skippedCount,
  deleting,
  onCancel,
  onConfirm,
}: {
  open: boolean
  totalCount: number
  deletableCount: number
  skippedCount: number
  deleting: boolean
  onCancel: () => void
  onConfirm: () => Promise<void>
}) {
  const skippedText = skippedCount > 0 ? `，${skippedCount} 个未结束任务会跳过` : ""

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !deleting) {
          onCancel()
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>删除所选任务</DialogTitle>
          <DialogDescription>
            已选择 {totalCount} 个任务，将删除 {deletableCount} 个已结束任务{skippedText}。
          </DialogDescription>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          此操作会移除任务记录和本地产物，已删除的数据无法从页面恢复。
        </p>
        <DialogFooter>
          <Button variant="outline" disabled={deleting} onClick={onCancel}>
            取消
          </Button>
          <Button
            variant="destructive"
            disabled={deleting || deletableCount === 0}
            onClick={() => void onConfirm()}
          >
            {deleting && <Loader2 className="animate-spin" />}
            删除任务
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function AppHeader({
  route,
  capabilities,
  serviceStatus,
  authRequired,
  onNavigate,
}: {
  route: Route
  capabilities: CapabilitiesResponse | null
  serviceStatus: ServiceStatus
  authRequired: boolean
  onNavigate: (path: string) => void
}) {
  const serviceTone = authRequired
    ? "border-amber-200 bg-amber-50 text-amber-800"
    : serviceStatus === "offline"
      ? "border-red-200 bg-red-50 text-red-700"
      : serviceStatus === "online" || capabilities
      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
      : "border-stone-300 bg-stone-100 text-stone-700"
  const serviceLabel = authRequired
    ? "需要 token"
    : serviceStatus === "offline"
      ? "本地服务：已断开"
      : serviceStatus === "online" || capabilities
        ? "本地服务：运行中"
        : "检查中"

  return (
    <header className="sticky top-0 z-20 border-b bg-background/88 backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-[1520px] items-center justify-between px-4 md:px-6 lg:px-8">
        <div className="flex items-center gap-3">
          <img
            src="/static/favicon.svg"
            alt=""
            aria-hidden="true"
            className="size-8 rounded-lg"
          />
          <button
            type="button"
            className="text-left text-base font-semibold tracking-normal"
            onClick={() => onNavigate("/")}
          >
            YC 音视频转录
          </button>
          <nav className="ml-3 hidden items-center gap-1 md:flex">
            <NavButton active={route.name === "dashboard"} onClick={() => onNavigate("/")}>
              工作台
            </NavButton>
            <NavButton active={route.name === "metrics"} onClick={() => onNavigate("/metrics")}>
              监控
            </NavButton>
            <NavButton active={route.name === "settings"} onClick={() => onNavigate("/settings")}>
              设置
            </NavButton>
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className={cn("gap-1.5 rounded-md", serviceTone)}>
            <span className="size-1.5 rounded-full bg-current" />
            {serviceLabel}
          </Badge>
        </div>
      </div>
    </header>
  )
}

function NavButton({
  active,
  children,
  onClick,
}: {
  active: boolean
  children: React.ReactNode
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className={cn(
        "rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
        active && "bg-accent text-accent-foreground",
      )}
      onClick={onClick}
    >
      {children}
    </button>
  )
}

function AuthPanel({
  authRequired,
  value,
  onChange,
  onSave,
}: {
  authRequired: boolean
  value: string
  onChange: (value: string) => void
  onSave: () => void
}) {
  return (
    <Card className="rounded-lg border-amber-200 bg-amber-50/75 py-3">
      <CardContent className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-2 text-sm text-amber-900">
          <AlertCircle className="size-4" />
          {authRequired ? "API 已启用鉴权，输入 token 后继续使用。" : "当前 API 已启用鉴权。"}
        </div>
        <div className="flex w-full gap-2 md:w-[440px]">
          <Input
            value={value}
            type="password"
            placeholder="API_AUTH_TOKEN"
            className="h-8 bg-card"
            onChange={(event) => onChange(event.target.value)}
          />
          <Button size="sm" onClick={onSave}>
            保存
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function NoticeBanner({
  notice,
  onDismiss,
}: {
  notice: Notice
  onDismiss: () => void
}) {
  const tone = {
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
    error: "border-red-200 bg-red-50 text-red-700",
    info: "border-stone-200 bg-card text-foreground",
  }[notice.tone]

  return (
    <div className={cn("flex items-center justify-between rounded-lg border px-3 py-2 text-sm", tone)}>
      <span>{notice.text}</span>
      <Button variant="ghost" size="xs" onClick={onDismiss}>
        关闭
      </Button>
    </div>
  )
}

function NewJobPanel({
  onCreateUpload,
  onCreateUrl,
  onPreviewCreator,
  onSubmitCreator,
  onError,
}: {
  onCreateUpload: (file: File, options: JobOptions) => Promise<void>
  onCreateUrl: (value: string, options: JobOptions) => Promise<void>
  onPreviewCreator: (value: string, maxItems: number) => Promise<CreatorPreviewResponse>
  onSubmitCreator: (previewId: string, selectedItemIds: string[], options: JobOptions) => Promise<void>
  onError: (error: unknown) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [sourceText, setSourceText] = useState("")
  const [creatorText, setCreatorText] = useState("")
  const [creatorMaxItems, setCreatorMaxItems] = useState("20")
  const [creatorPreview, setCreatorPreview] = useState<CreatorPreviewResponse | null>(null)
  const [selectedCreatorItemIds, setSelectedCreatorItemIds] = useState<Set<string>>(() => new Set<string>())
  const [activeTab, setActiveTab] = useState("url")
  const [speakerDiarization, setSpeakerDiarization] = useState(false)
  const [llmPolish, setLlmPolish] = useState(true)
  const [summary, setSummary] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [previewingCreator, setPreviewingCreator] = useState(false)
  const creatorVideoLimit = Math.min(50, Math.max(1, Number(creatorMaxItems) || 20))

  const options = (): JobOptions => ({
    asr_engine: null,
    speaker_diarization: speakerDiarization,
    llm_polish: llmPolish,
    summary,
  })

  const clearFileSelection = () => {
    setFile(null)
    if (fileInputRef.current) {
      fileInputRef.current.value = ""
    }
  }

  const submitUpload = async () => {
    if (!file) {
      return
    }
    setSubmitting(true)
    try {
      await onCreateUpload(file, options())
      clearFileSelection()
    } catch (error) {
      onError(error)
    } finally {
      setSubmitting(false)
    }
  }

  const submitUrl = async () => {
    const value = sourceText.trim()
    if (!value) {
      return
    }
    if (detectCreatorProfileInput(value)) {
      setCreatorText(value)
      setSourceText("")
      setCreatorPreview(null)
      setSelectedCreatorItemIds(new Set<string>())
      setActiveTab("creator")
      return
    }
    setSubmitting(true)
    try {
      await onCreateUrl(value, options())
      setSourceText("")
    } catch (error) {
      onError(error)
    } finally {
      setSubmitting(false)
    }
  }

  const previewCreator = async () => {
    if (!creatorText.trim()) {
      return
    }
    setPreviewingCreator(true)
    try {
      const preview = await onPreviewCreator(creatorText.trim(), creatorVideoLimit)
      setCreatorPreview(preview)
      setSelectedCreatorItemIds(new Set<string>())
    } catch (error) {
      onError(error)
    } finally {
      setPreviewingCreator(false)
    }
  }

  const submitCreator = async () => {
    if (!creatorPreview || selectedCreatorItemIds.size === 0) {
      return
    }
    setSubmitting(true)
    try {
      await onSubmitCreator(creatorPreview.preview_id, Array.from(selectedCreatorItemIds), options())
    } catch (error) {
      onError(error)
    } finally {
      setSubmitting(false)
    }
  }

  const toggleCreatorItem = (itemId: string, checked: boolean) => {
    setSelectedCreatorItemIds((current) => {
      const next = new Set(current)
      if (checked) {
        next.add(itemId)
      } else {
        next.delete(itemId)
      }
      return next
    })
  }

  const selectAllCreatorVideos = () => {
    if (!creatorPreview) {
      return
    }
    setSelectedCreatorItemIds(new Set(creatorPreview.items.filter((item) => item.transcribable).map((item) => item.id)))
  }

  return (
    <Card className="rounded-lg">
      <CardHeader className="border-b pb-4">
        <div>
          <CardTitle className="text-lg">新建转录</CardTitle>
          <CardDescription>提交本地文件、媒体直链或平台分享文案。</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <Tabs value={activeTab} onValueChange={setActiveTab} className="gap-4">
          <TabsList className="h-9 rounded-lg bg-muted">
            <TabsTrigger value="url" className="px-4">
              <Link2 className="size-3.5" />
              粘贴链接
            </TabsTrigger>
            <TabsTrigger value="upload" className="px-4">
              <Upload className="size-3.5" />
              上传文件
            </TabsTrigger>
            <TabsTrigger value="creator" className="px-4">
              <UserRound className="size-3.5" />
              创作者主页
            </TabsTrigger>
          </TabsList>
          <TabsContent value="url" className="space-y-4">
            <Textarea
              value={sourceText}
              rows={6}
              placeholder="粘贴 YouTube、Bilibili、小宇宙、抖音、小红书链接或分享文案"
              className="resize-none bg-background/70"
              onChange={(event) => setSourceText(event.target.value)}
            />
            <JobOptionsBar
              speakerDiarization={speakerDiarization}
              llmPolish={llmPolish}
              summary={summary}
              onSpeakerDiarization={setSpeakerDiarization}
              onLlmPolish={setLlmPolish}
              onSummary={setSummary}
            />
            <div className="flex justify-end">
              <Button onClick={submitUrl} disabled={!sourceText.trim() || submitting}>
                {submitting ? <Loader2 className="animate-spin" /> : <Link2 />}
                提交链接任务
              </Button>
            </div>
          </TabsContent>
          <TabsContent value="upload" className="space-y-4">
            <label className="flex min-h-36 cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border border-dashed bg-background/70 px-4 text-center transition-colors hover:border-primary/50 hover:bg-accent/30">
              <div className="flex size-10 items-center justify-center rounded-lg border bg-card text-primary">
                <FileAudio className="size-5" />
              </div>
              <div>
                <p className="font-medium">{file ? file.name : "选择音视频文件"}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  mp4、mov、mkv、mp3、m4a、wav、flac
                </p>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                className="sr-only"
                onChange={(event) => setFile(event.target.files?.[0] || null)}
              />
            </label>
            <JobOptionsBar
              speakerDiarization={speakerDiarization}
              llmPolish={llmPolish}
              summary={summary}
              onSpeakerDiarization={setSpeakerDiarization}
              onLlmPolish={setLlmPolish}
              onSummary={setSummary}
            />
            <div className="flex justify-end">
              <Button onClick={submitUpload} disabled={!file || submitting}>
                {submitting ? <Loader2 className="animate-spin" /> : <Upload />}
                开始转录
              </Button>
            </div>
          </TabsContent>
          <TabsContent value="creator" className="space-y-4">
            <div className="rounded-lg border bg-background/70 p-2">
              <div className="flex flex-col gap-2 lg:flex-row lg:items-stretch">
                <div className="flex min-w-0 flex-1 gap-2 rounded-md border bg-card px-3 py-2 transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50">
                  <Link2 className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                  <Textarea
                    value={creatorText}
                    rows={2}
                    placeholder="粘贴抖音或小红书博主主页链接、分享文案"
                    className="min-h-11 resize-none border-0 bg-transparent px-0 py-0 text-sm shadow-none focus-visible:border-transparent focus-visible:ring-0"
                    onChange={(event) => {
                      setCreatorText(event.target.value)
                      setCreatorPreview(null)
                      setSelectedCreatorItemIds(new Set<string>())
                    }}
                  />
                </div>
                <div className="flex min-h-11 items-center justify-between gap-2 rounded-md border bg-card px-3 py-2 lg:w-[190px]">
                  <span className="shrink-0 text-xs text-muted-foreground">最多获取</span>
                  <Input
                    value={creatorMaxItems}
                    inputMode="numeric"
                    className="h-8 w-14 text-center"
                    onChange={(event) => {
                      setCreatorMaxItems(event.target.value.replace(/\D/g, "").slice(0, 3))
                      setCreatorPreview(null)
                      setSelectedCreatorItemIds(new Set<string>())
                    }}
                  />
                  <span className="shrink-0 text-xs text-muted-foreground">个视频</span>
                </div>
                <Button
                  className="min-h-11 px-4 lg:h-auto lg:min-w-[112px]"
                  onClick={previewCreator}
                  disabled={!creatorText.trim() || previewingCreator}
                >
                  {previewingCreator ? <Loader2 className="animate-spin" /> : <Search />}
                  开始解析
                </Button>
              </div>
            </div>

            {creatorPreview && (
              <div className="space-y-3">
                <div className="flex flex-col gap-3 rounded-lg border bg-card px-3 py-3 md:flex-row md:items-center md:justify-between">
                  <div className="min-w-0">
                    <div className="truncate font-medium">
                      {creatorPreview.creator.name || platformName(creatorPreview.platform)}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <Badge variant="outline">{platformName(creatorPreview.platform)}</Badge>
                      <span>{creatorPreview.items.length} / {creatorVideoLimit} 个视频</span>
                      {creatorPreview.pagination.filtered_count > 0 && (
                        <span>已过滤 {creatorPreview.pagination.filtered_count} 条不可转录作品</span>
                      )}
                    </div>
                    <div className="mt-1 truncate text-xs text-muted-foreground">
                      {creatorPreviewStatus(creatorPreview, creatorVideoLimit)}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button variant="outline" onClick={selectAllCreatorVideos}>
                      <ListChecks />
                      全选视频
                    </Button>
                    <Button
                      onClick={submitCreator}
                      disabled={!creatorPreview || selectedCreatorItemIds.size === 0 || submitting}
                    >
                      {submitting ? <Loader2 className="animate-spin" /> : <Plus />}
                      创建 {selectedCreatorItemIds.size} 个任务
                    </Button>
                  </div>
                </div>

                <JobOptionsBar
                  speakerDiarization={speakerDiarization}
                  llmPolish={llmPolish}
                  summary={summary}
                  onSpeakerDiarization={setSpeakerDiarization}
                  onLlmPolish={setLlmPolish}
                  onSummary={setSummary}
                />

                <CreatorItemsTable
                  items={creatorPreview.items}
                  selectedItemIds={selectedCreatorItemIds}
                  onToggle={toggleCreatorItem}
                />
              </div>
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}

function JobOptionsBar({
  speakerDiarization,
  llmPolish,
  summary,
  onSpeakerDiarization,
  onLlmPolish,
  onSummary,
}: {
  speakerDiarization: boolean
  llmPolish: boolean
  summary: boolean
  onSpeakerDiarization: (value: boolean) => void
  onLlmPolish: (value: boolean) => void
  onSummary: (value: boolean) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-3 rounded-lg border bg-card px-3 py-3">
      <CheckboxField
        checked={speakerDiarization}
        label="区分说话人"
        onChange={onSpeakerDiarization}
      />
      <CheckboxField checked={llmPolish} label="LLM 校对" onChange={onLlmPolish} />
      <CheckboxField checked={summary} label="内容总结" onChange={onSummary} />
    </div>
  )
}

function CreatorItemsTable({
  items,
  selectedItemIds,
  onToggle,
}: {
  items: CreatorWorkItem[]
  selectedItemIds: Set<string>
  onToggle: (itemId: string, checked: boolean) => void
}) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="overflow-x-auto">
        <Table className="table-fixed min-w-[720px]">
          <TableHeader>
            <TableRow className="bg-muted/60">
              <TableHead className="w-[54px]"></TableHead>
              <TableHead>作品</TableHead>
              <TableHead className="w-[112px]">互动</TableHead>
              <TableHead className="w-[132px]">发布时间</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="h-24 text-center text-muted-foreground">
                  暂无视频作品
                </TableCell>
              </TableRow>
            ) : (
              items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell>
                    <Checkbox
                      checked={selectedItemIds.has(item.id)}
                      disabled={!item.transcribable}
                      onCheckedChange={(value) => onToggle(item.id, value === true)}
                    />
                  </TableCell>
                  <TableCell className="whitespace-normal">
                    <div className="line-clamp-2 break-words font-medium leading-snug" title={item.title}>
                      {item.title}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    <div className="mono">赞 {formatCompactNumber(item.stats.like)}</div>
                    <div className="mono">评 {formatCompactNumber(item.stats.comment)}</div>
                  </TableCell>
                  <TableCell className="mono text-xs text-muted-foreground">
                    {item.published_at ? formatDate(item.published_at) : "-"}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

function CheckboxField({
  checked,
  label,
  onChange,
}: {
  checked: boolean
  label: string
  onChange: (value: boolean) => void
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <Checkbox checked={checked} onCheckedChange={(value) => onChange(value === true)} />
      {label}
    </label>
  )
}

function JobsTable({
  jobs,
  selectedJobId,
  loading,
  onRefresh,
  onSelectJob,
  onDownload,
  onBatchDownload,
  onRetry,
  onDelete,
  onBatchDelete,
  retryingJobIds,
}: {
  jobs: JobRecord[]
  selectedJobId?: string
  loading: boolean
  onRefresh: () => Promise<void>
  onSelectJob: (jobId: string) => void
  onDownload: (jobId: string, artifactType: string) => Promise<void>
  onBatchDownload: (jobIds: string[], artifactType: BatchExportArtifactType) => Promise<void>
  onRetry: (jobId: string) => Promise<void>
  onDelete: (jobId: string) => Promise<void>
  onBatchDelete: (jobIds: string[]) => Promise<void>
  retryingJobIds: Set<string>
}) {
  const [keyword, setKeyword] = useState("")
  const [status, setStatus] = useState("all")
  const [selectedJobIds, setSelectedJobIds] = useState<Set<string>>(() => new Set())

  const filteredJobs = useMemo(() => {
    const normalized = keyword.trim().toLowerCase()
    return jobs.filter((job) => {
      const statusMatch = status === "all" || job.status === status
      const keywordMatch =
        !normalized ||
        [job.id, job.title || "", job.source_value, sourceLabel(job), job.status]
          .join(" ")
          .toLowerCase()
          .includes(normalized)
      return statusMatch && keywordMatch
    })
  }, [jobs, keyword, status])
  const selectedJobs = useMemo(
    () => jobs.filter((job) => selectedJobIds.has(job.id)),
    [jobs, selectedJobIds],
  )
  const selectedIds = useMemo(() => selectedJobs.map((job) => job.id), [selectedJobs])
  const selectedCompletedCount = selectedJobs.filter((job) => job.status === "completed").length
  const selectedDeletableCount = selectedJobs.filter((job) => terminalStatuses.includes(job.status)).length
  const filteredJobIds = useMemo(() => filteredJobs.map((job) => job.id), [filteredJobs])
  const allFilteredSelected =
    filteredJobIds.length > 0 && filteredJobIds.every((jobId) => selectedJobIds.has(jobId))

  useEffect(() => {
    setSelectedJobIds((current) => {
      const availableIds = new Set(jobs.map((job) => job.id))
      const next = new Set([...current].filter((jobId) => availableIds.has(jobId)))
      return next.size === current.size ? current : next
    })
  }, [jobs])

  const toggleJobSelection = (jobId: string, checked: boolean) => {
    setSelectedJobIds((current) => {
      const next = new Set(current)
      if (checked) {
        next.add(jobId)
      } else {
        next.delete(jobId)
      }
      return next
    })
  }

  const toggleFilteredSelection = (checked: boolean) => {
    setSelectedJobIds((current) => {
      const next = new Set(current)
      for (const jobId of filteredJobIds) {
        if (checked) {
          next.add(jobId)
        } else {
          next.delete(jobId)
        }
      }
      return next
    })
  }

  return (
    <Card className="rounded-lg">
      <CardHeader className="border-b pb-4">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            任务队列
            <Badge variant="secondary" className="rounded-md">
              {jobs.length}
            </Badge>
          </CardTitle>
          <CardDescription>按时间查看本地任务。</CardDescription>
        </div>
        <CardAction>
          <Button variant="outline" size="sm" onClick={() => void onRefresh()}>
            <RefreshCcw className={cn(loading && "animate-spin")} />
            刷新
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3">
        {selectedIds.length > 0 && (
          <div className="flex flex-col gap-2 rounded-lg border bg-background px-3 py-2 md:flex-row md:items-center md:justify-between">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge variant="secondary" className="rounded-md">
                已选 {selectedIds.length}
              </Badge>
              <span className="text-xs text-muted-foreground">
                {selectedCompletedCount} 个已完成，{selectedDeletableCount} 个可删除
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {batchExportTypes.map((item) => {
                const Icon = item.icon
                return (
                  <Button
                    key={item.type}
                    variant="outline"
                    size="sm"
                    disabled={selectedCompletedCount === 0}
                    onClick={() => void onBatchDownload(selectedIds, item.type)}
                  >
                    <Icon />
                    {item.label}
                  </Button>
                )
              })}
              <Button
                variant="destructive"
                size="sm"
                disabled={selectedDeletableCount === 0}
                onClick={() => void onBatchDelete(selectedIds)}
              >
                <Trash2 />
                删除
              </Button>
            </div>
          </div>
        )}

        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="relative md:w-[360px]">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
            <Input
              value={keyword}
              placeholder="搜索任务、来源"
              className="h-8 bg-background pl-8"
              onChange={(event) => setKeyword(event.target.value)}
            />
          </div>
          <div className="flex items-center gap-2">
            <Select value={status} onValueChange={setStatus}>
              <SelectTrigger className="h-8 w-[150px] bg-background">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">状态：全部</SelectItem>
                <SelectItem value="queued">queued</SelectItem>
                <SelectItem value="transcribing">transcribing</SelectItem>
                <SelectItem value="llm_processing">llm_processing</SelectItem>
                <SelectItem value="completed">completed</SelectItem>
                <SelectItem value="failed">failed</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="outline" size="icon-sm">
              <SlidersHorizontal />
            </Button>
          </div>
        </div>

        <div className="overflow-hidden rounded-lg border bg-card">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/60">
                  <TableHead className="w-[44px]">
                    <Checkbox
                      checked={allFilteredSelected}
                      disabled={filteredJobs.length === 0}
                      onCheckedChange={(value) => toggleFilteredSelection(value === true)}
                    />
                  </TableHead>
                  <TableHead>标题</TableHead>
                  <TableHead className="w-[110px]">来源</TableHead>
                  <TableHead className="w-[132px]">状态</TableHead>
                  <TableHead className="w-[150px]">进度</TableHead>
                  <TableHead className="w-[155px]">创建时间</TableHead>
                  <TableHead className="w-[110px]">导出</TableHead>
                  <TableHead className="w-[116px] text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredJobs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="h-28 text-center text-muted-foreground">
                      暂无任务
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredJobs.map((job) => (
                    <TableRow
                      key={job.id}
                      className={cn(
                        "cursor-pointer",
                        selectedJobId === job.id && "bg-accent/40",
                      )}
                      onClick={() => onSelectJob(job.id)}
                    >
                      <TableCell onClick={(event) => event.stopPropagation()}>
                        <Checkbox
                          checked={selectedJobIds.has(job.id)}
                          onCheckedChange={(value) => toggleJobSelection(job.id, value === true)}
                        />
                      </TableCell>
                      <TableCell>
                        <div className="max-w-[460px] truncate font-medium">
                          {job.title || filename(job.source_value)}
                        </div>
                        <div className="mt-0.5 max-w-[460px] truncate text-xs text-muted-foreground">
                          {job.source_type === "upload" ? "本地上传" : job.source_value}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="rounded-md">
                          {sourceLabel(job)}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={job.status} />
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Progress value={job.progress} className="h-1.5 w-20" />
                          <span className="mono text-xs text-muted-foreground">{job.progress}%</span>
                        </div>
                      </TableCell>
                      <TableCell className="mono text-xs text-muted-foreground">
                        {formatDate(job.created_at)}
                      </TableCell>
                      <TableCell onClick={(event) => event.stopPropagation()}>
                        <ExportMenu job={job} onDownload={onDownload} />
                      </TableCell>
                      <TableCell className="text-right">
                        <JobRowActions
                          job={job}
                          onSelect={onSelectJob}
                          onRetry={onRetry}
                          onDelete={onDelete}
                          isRetrying={retryingJobIds.has(job.id)}
                        />
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function JobRowActions({
  job,
  onSelect,
  onRetry,
  onDelete,
  isRetrying,
}: {
  job: JobRecord
  onSelect: (jobId: string) => void
  onRetry: (jobId: string) => Promise<void>
  onDelete: (jobId: string) => Promise<void>
  isRetrying: boolean
}) {
  const canDelete = terminalStatuses.includes(job.status)
  return (
    <div className="flex items-center justify-end gap-1">
      <Button
        variant="ghost"
        size="icon-sm"
        title="查看详情"
        onClick={(event) => {
          event.stopPropagation()
          onSelect(job.id)
        }}
      >
        <Eye />
      </Button>
      {job.status === "failed" && (
        <Button
          variant="ghost"
          size="icon-sm"
          title={isRetrying ? "正在重试" : "重试任务"}
          disabled={isRetrying}
          onClick={(event) => {
            event.stopPropagation()
            void onRetry(job.id)
          }}
        >
          <RefreshCcw className={cn(isRetrying && "animate-spin")} />
        </Button>
      )}
      {canDelete && (
        <Button
          variant="destructive"
          size="icon-sm"
          title="删除任务"
          disabled={isRetrying}
          onClick={(event) => {
            event.stopPropagation()
            void onDelete(job.id)
          }}
        >
          <Trash2 />
        </Button>
      )}
    </div>
  )
}

function ExportMenu({
  job,
  onDownload,
}: {
  job: JobRecord
  onDownload: (jobId: string, artifactType: string) => Promise<void>
}) {
  const artifacts = Object.keys(job.result?.artifacts || {})
  const options = singleJobExportTypes.filter((type) => artifacts.length === 0 || artifacts.includes(type))
  const disabled = job.status !== "completed"

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" disabled={disabled}>
          导出
          <ChevronDown />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44">
        {options.map((type) => (
          <DropdownMenuItem
            key={type}
            onSelect={(event) => {
              event.preventDefault()
              void onDownload(job.id, type)
            }}
          >
            <ArrowDownToLine />
            {artifactLabel(type)}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function JobDetailPanel({
  job,
  result,
  error,
  onDownload,
  onCopy,
}: {
  job: JobRecord | null
  result: JobResult | null
  error: ErrorInfo | null
  onDownload: (jobId: string, artifactType: string) => Promise<void>
  onCopy: (text: string) => void
}) {
  if (!job) {
    return (
      <Card className="rounded-lg">
        <CardHeader>
          <CardTitle className="text-base">任务详情</CardTitle>
          <CardDescription>选择一条任务查看结果。</CardDescription>
        </CardHeader>
        <CardContent className="flex h-64 items-center justify-center rounded-lg border border-dashed bg-background/50 text-sm text-muted-foreground">
          未选择任务
        </CardContent>
      </Card>
    )
  }

  const summary = result?.summary || ""
  const polished = result?.polished_text?.trim() || ""
  const raw = result?.raw_transcript || ""

  return (
    <Card className="rounded-lg">
      <CardHeader className="border-b pb-4">
        <div className="min-w-0">
          <CardTitle className="truncate text-base">{job.title || filename(job.source_value)}</CardTitle>
          <CardDescription className="mono mt-1 truncate">{job.id}</CardDescription>
        </div>
        <CardAction className="flex items-center gap-2">
          <StatusBadge status={job.status} />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>进度</span>
            <span className="mono">{job.progress}%</span>
          </div>
          <Progress value={job.progress} className="h-1.5" />
        </div>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <div className="font-medium">任务失败</div>
            <div className="mt-1">{shortErrorMessage(error.message)}</div>
            <div className="mt-3 grid gap-1 text-xs">
              <div>
                <span className="text-red-700/70">阶段：</span>
                <span>{stageLabel(error.stage)}</span>
              </div>
              <div>
                <span className="text-red-700/70">错误码：</span>
                <span className="mono">{error.code}</span>
              </div>
              <div className="min-w-0">
                <span className="text-red-700/70">原始输入：</span>
                <span className="break-all">{job.source_type === "upload" ? "本地上传" : job.source_value}</span>
              </div>
            </div>
          </div>
        )}

        <Tabs defaultValue="summary" className="gap-3">
          <TabsList className="grid h-9 w-full grid-cols-3 rounded-lg bg-muted">
            <TabsTrigger value="summary">总结</TabsTrigger>
            <TabsTrigger value="polished">校对稿</TabsTrigger>
            <TabsTrigger value="raw">原文</TabsTrigger>
          </TabsList>
          <TabsContent value="summary">
            <TextBlock
              text={summary || "暂无总结"}
              empty={!summary}
              actions={
                result ? (
                  <Button variant="outline" size="sm" onClick={() => onCopy(summary)}>
                    <Copy />
                    复制
                  </Button>
                ) : null
              }
            />
          </TabsContent>
          <TabsContent value="polished">
            <TextBlock
              text={polished || "暂无校对稿"}
              empty={!polished}
              actions={
                polished ? (
                  <Button variant="outline" size="sm" onClick={() => onCopy(polished)}>
                    <Copy />
                    复制
                  </Button>
                ) : null
              }
            />
          </TabsContent>
          <TabsContent value="raw">
            <TextBlock
              text={raw || "暂无原始转录"}
              empty={!raw}
              actions={
                raw ? (
                  <Button variant="outline" size="sm" onClick={() => onCopy(raw)}>
                    <Copy />
                    复制
                  </Button>
                ) : null
              }
            />
          </TabsContent>
        </Tabs>

        <div>
          <p className="mb-2 text-sm font-medium">快速导出</p>
          <div className="grid grid-cols-2 gap-2">
            {singleJobExportTypes.map((type) => (
              <Button
                key={type}
                variant="outline"
                size="sm"
                disabled={job.status !== "completed"}
                onClick={() => void onDownload(job.id, type)}
              >
                <ArrowDownToLine />
                {artifactShortLabel(type)}
              </Button>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function TextBlock({
  text,
  empty,
  mono,
  actions,
}: {
  text: string
  empty?: boolean
  mono?: boolean
  actions?: React.ReactNode
}) {
  return (
    <div className="overflow-hidden rounded-lg border bg-background">
      {actions && <div className="flex justify-end border-b bg-muted/40 px-3 py-2">{actions}</div>}
      <pre
        className={cn(
          "max-h-[420px] overflow-auto whitespace-pre-wrap p-3 text-sm leading-6",
          mono && "mono text-xs",
          empty && "text-muted-foreground",
        )}
      >
        {text}
      </pre>
    </div>
  )
}

function MetricsView({
  token,
  onAuthError,
  onNotice,
  onServiceStatusChange,
}: {
  token: string
  onAuthError: () => void
  onNotice: (notice: Notice) => void
  onServiceStatusChange: (status: ServiceStatus) => void
}) {
  const [overview, setOverview] = useState<MetricsOverview | null>(null)
  const [metricJobs, setMetricJobs] = useState<MetricsJob[]>([])
  const [loading, setLoading] = useState(true)
  const [autoRefreshPaused, setAutoRefreshPaused] = useState(false)

  const loadMetrics = useCallback(async (options: { manual?: boolean } = {}) => {
    setLoading(true)
    try {
      const [overviewPayload, jobsPayload] = await Promise.all([
        apiRequest<MetricsOverview>("/api/metrics/overview", { token }),
        apiRequest<MetricsJobsResponse>("/api/metrics/jobs?limit=100", { token }),
      ])
      setOverview(overviewPayload)
      setMetricJobs(jobsPayload.items)
      setAutoRefreshPaused(false)
      onServiceStatusChange("online")
    } catch (error) {
      if (isNetworkError(error)) {
        setAutoRefreshPaused(true)
        onServiceStatusChange("offline")
        if (!autoRefreshPaused || options.manual) {
          onNotice({
            tone: "error",
            text: "本地服务已断开，已暂停自动刷新。重新启动服务后点击刷新重试。",
          })
        }
        return
      }
      if (error instanceof ApiError && error.status === 401) {
        onAuthError()
      } else {
        onNotice({ tone: "error", text: error instanceof Error ? error.message : "监控数据读取失败。" })
      }
    } finally {
      setLoading(false)
    }
  }, [autoRefreshPaused, onAuthError, onNotice, onServiceStatusChange, token])

  useEffect(() => {
    if (autoRefreshPaused) {
      return
    }
    void loadMetrics()
    const timer = window.setInterval(() => {
      void loadMetrics()
    }, 5000)
    return () => window.clearInterval(timer)
  }, [autoRefreshPaused, loadMetrics])

  const resources = overview?.resources
  const recent = overview?.recent

  return (
    <section className="grid gap-4">
      {overview?.enabled === false && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          Metrics 已关闭，当前不会写入任务指标或采样资源。
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={Cpu}
          label="当前 CPU"
          value={resources?.available ? formatPercent(resources.process_cpu_percent) : "-"}
          meta={resources?.available ? `系统 ${formatPercent(resources.system_cpu_percent)}` : unavailableReason(resources)}
        />
        <MetricCard
          icon={HardDrive}
          label="内存"
          value={resources?.available ? formatMb(resources.process_rss_mb) : "-"}
          meta={
            resources?.available
              ? `余量 ${formatMb(resources.memory_headroom_mb)}`
              : unavailableReason(resources)
          }
        />
        <MetricCard
          icon={ListChecks}
          label="任务压力"
          value={`${overview?.queue.active_job_count ?? 0} / ${overview?.queue.queued_job_count ?? 0}`}
          meta="运行中 / 排队"
        />
        <MetricCard
          icon={Activity}
          label="最近 24 小时"
          value={`${recent?.completed_24h ?? 0} / ${recent?.failed_24h ?? 0}`}
          meta={`完成 / 失败，转录耗时比 ${formatDurationRatio(recent?.avg_asr_rtf_24h)}`}
        />
      </div>

      <section className="grid gap-4">
        <Card className="rounded-lg">
          <CardHeader className="border-b pb-4">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                任务效率
                <Badge variant="secondary" className="rounded-md">
                  {metricJobs.length}
                </Badge>
              </CardTitle>
              <CardDescription>
                {loading
                  ? "刷新中"
                  : autoRefreshPaused
                    ? "本地服务已断开，自动刷新已暂停。"
                    : "按创建时间显示最近任务指标。"}
              </CardDescription>
            </div>
            <CardAction>
              <Button variant="outline" size="sm" onClick={() => void loadMetrics({ manual: true })}>
                <RefreshCcw className={cn(loading && "animate-spin")} />
                {autoRefreshPaused ? "重试" : "刷新"}
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent>
            <div className="overflow-hidden rounded-lg border bg-card">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/60">
                      <TableHead>任务标题</TableHead>
                      <TableHead className="w-[128px]">状态</TableHead>
                      <TableHead className="w-[110px]">平台</TableHead>
                      <TableHead className="w-[100px]">总耗时</TableHead>
                      <TableHead className="w-[100px]">下载</TableHead>
                      <TableHead className="w-[104px]">转录耗时比</TableHead>
                      <TableHead className="w-[124px]">AI 处理消耗</TableHead>
                      <TableHead className="w-[86px]">外部请求</TableHead>
                      <TableHead className="w-[148px]">TikHub API 调用次数</TableHead>
                      <TableHead className="w-[92px]">缓存命中</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {metricJobs.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={10} className="h-28 text-center text-muted-foreground">
                          暂无 metrics
                        </TableCell>
                      </TableRow>
                    ) : (
                      metricJobs.map((job) => (
                        <TableRow key={job.job_id}>
                          <TableCell>
                            <div className="max-w-[420px] truncate font-medium">
                              {job.title || filename(job.source_value)}
                            </div>
                            <div className="mono mt-0.5 truncate text-xs text-muted-foreground">
                              {job.job_id}
                            </div>
                          </TableCell>
                          <TableCell>
                            <StatusBadge status={job.status} />
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline" className="rounded-md">
                              {platformName(job.platform || job.source_type)}
                            </Badge>
                          </TableCell>
                          <TableCell className="mono text-xs">{formatMs(job.total_duration_ms)}</TableCell>
                          <TableCell className="mono text-xs">{formatSeconds(job.download_seconds)}</TableCell>
                          <TableCell className="mono text-xs">{formatDurationRatio(job.asr_rtf)}</TableCell>
                          <TableCell className="mono text-xs">{formatTokenUsage(job.llm_total_tokens)}</TableCell>
                          <TableCell className="mono text-xs">{job.http_requests_total}</TableCell>
                          <TableCell className="mono text-xs">
                            {job.tikhub_calls_total}/{job.tikhub_http_attempts_total}
                          </TableCell>
                          <TableCell>
                            <CacheBadge value={job.cache_hit} />
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </div>
            </div>
          </CardContent>
        </Card>
      </section>
    </section>
  )
}

function MetricCard({
  icon: Icon,
  label,
  value,
  meta,
}: {
  icon: typeof Activity
  label: string
  value: string
  meta: string
}) {
  return (
    <Card className="rounded-lg">
      <CardContent className="flex items-center gap-3 py-4">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-background text-primary">
          <Icon className="size-4" />
        </div>
        <div className="min-w-0">
          <div className="text-xs text-muted-foreground">{label}</div>
          <div className="mono mt-1 truncate text-xl font-semibold">{value}</div>
          <div className="mt-1 truncate text-xs text-muted-foreground">{meta}</div>
        </div>
      </CardContent>
    </Card>
  )
}

function CacheBadge({ value }: { value: boolean | null }) {
  if (value === true) {
    return (
      <Badge variant="outline" className="rounded-md border-emerald-200 bg-emerald-50 text-emerald-800">
        命中
      </Badge>
    )
  }
  if (value === false) {
    return (
      <Badge variant="outline" className="rounded-md border-stone-300 bg-stone-100 text-stone-700">
        未命中
      </Badge>
    )
  }
  return <span className="text-xs text-muted-foreground">-</span>
}

function SettingsView({
  capabilities,
  token,
  onAuthError,
  onNotice,
}: {
  capabilities: CapabilitiesResponse | null
  token: string
  onAuthError: () => void
  onNotice: (notice: Notice) => void
}) {
  const [terms, setTerms] = useState<Term[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let active = true
    async function loadTerms() {
      setLoading(true)
      try {
        const payload = await apiRequest<TermsPayload>("/api/settings/terms", { token })
        if (active) {
          setTerms(payload.terms)
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthError()
        } else {
          onNotice({ tone: "error", text: error instanceof Error ? error.message : "术语表读取失败。" })
        }
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    }
    void loadTerms()
    return () => {
      active = false
    }
  }, [onAuthError, onNotice, token])

  const addTerm = () => {
    setTerms((current) => [...current, emptyTerm()])
  }

  const updateTerm = (index: number, patch: Partial<Term>) => {
    setTerms((current) =>
      current.map((term, currentIndex) =>
        currentIndex === index ? { ...term, ...patch } : term,
      ),
    )
  }

  const removeTerm = (index: number) => {
    setTerms((current) => current.filter((_, currentIndex) => currentIndex !== index))
  }

  const saveTerms = async () => {
    setSaving(true)
    try {
      const normalizedTerms = terms
        .map(normalizeTerm)
        .filter((term) => term.incorrect || term.correct)
      if (normalizedTerms.some((term) => !term.correct)) {
        onNotice({ tone: "error", text: "每条术语都需要填写标准术语。" })
        return
      }
      const saved = await apiRequest<TermsPayload>("/api/settings/terms", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ terms: normalizedTerms }),
        token,
      })
      setTerms(saved.terms)
      onNotice({ tone: "success", text: "术语表已保存。" })
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        onAuthError()
      } else {
        onNotice({ tone: "error", text: error instanceof Error ? error.message : "术语表保存失败。" })
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.2fr)]">
      <Card className="rounded-lg">
        <CardHeader className="border-b pb-4">
          <CardTitle className="text-base">运行配置</CardTitle>
          <CardDescription>只展示当前值，修改请编辑环境变量。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid grid-cols-[130px_minmax(0,1fr)] gap-x-4 gap-y-3 text-sm">
            <MetaLabel>LLM provider</MetaLabel>
            <MetaValue>{capabilities?.llm.provider ? String(capabilities.llm.provider) : "-"}</MetaValue>
            <MetaLabel>LLM 状态</MetaLabel>
            <Availability available={Boolean(capabilities?.llm.available)} reason={capabilities?.llm.reason} />
            <MetaLabel>LLM 模型</MetaLabel>
            <MetaValue>{readCapability(capabilities?.llm, "model")}</MetaValue>
            <MetaLabel>ASR 引擎</MetaLabel>
            <MetaValue>{capabilities?.asr.engine ? String(capabilities.asr.engine) : "-"}</MetaValue>
            <MetaLabel>ASR 状态</MetaLabel>
            <Availability available={Boolean(capabilities?.asr.available)} reason={capabilities?.asr.reason} />
            <MetaLabel>API 鉴权</MetaLabel>
            <MetaValue>{capabilities?.auth.enabled ? "已启用" : "未启用"}</MetaValue>
          </div>
          <div>
            <p className="mb-2 text-sm font-medium">平台能力</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {Object.entries(capabilities?.platforms || {}).map(([name, entry]) => (
                <div
                  key={name}
                  className="flex items-center justify-between rounded-lg border bg-background px-3 py-2 text-sm"
                >
                  <span>{platformName(name)}</span>
                  <Availability available={Boolean(entry.available)} reason={entry.reason} compact />
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="rounded-lg">
        <CardHeader className="border-b pb-4">
          <div>
            <CardTitle className="text-base">术语表</CardTitle>
            <CardDescription>{loading ? "读取中" : `${terms.length} 条术语`}</CardDescription>
          </div>
          <CardAction className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={addTerm} disabled={loading || saving}>
              <Plus />
              添加
            </Button>
            <Button size="sm" onClick={saveTerms} disabled={saving || loading}>
              {saving ? <Loader2 className="animate-spin" /> : <FileText />}
              保存
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="hidden grid-cols-[minmax(0,1fr)_minmax(0,1fr)_150px_32px] gap-2 px-1 text-xs text-muted-foreground md:grid">
            <span>错误写法</span>
            <span>标准术语</span>
            <span>语境</span>
            <span />
          </div>
          {terms.length === 0 ? (
            <div className="flex h-32 items-center justify-center rounded-lg border border-dashed bg-background/50 text-sm text-muted-foreground">
              暂无术语
            </div>
          ) : (
            <div className="space-y-2">
              {terms.map((term, index) => (
                <div
                  key={index}
                  className="grid gap-2 rounded-lg border bg-background p-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_150px_32px] md:border-0 md:bg-transparent md:p-0"
                >
                  <Input
                    value={term.incorrect}
                    placeholder="错误写法"
                    onChange={(event) => updateTerm(index, { incorrect: event.target.value })}
                  />
                  <Input
                    value={term.correct}
                    placeholder="标准术语"
                    aria-invalid={!term.correct.trim()}
                    onChange={(event) => updateTerm(index, { correct: event.target.value })}
                  />
                  <Input
                    value={term.context}
                    placeholder="语境"
                    onChange={(event) => updateTerm(index, { context: event.target.value })}
                  />
                  <Button
                    type="button"
                    variant="destructive"
                    size="icon-sm"
                    title="删除术语"
                    onClick={() => removeTerm(index)}
                  >
                    <Trash2 />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  )
}

function StatusBadge({ status }: { status: JobStatus }) {
  const meta = statusMeta[status]
  const Icon = meta.icon
  return (
    <Badge variant="outline" className={cn("rounded-md", meta.className)}>
      <Icon className={cn(status !== "completed" && status !== "failed" && "animate-pulse")} />
      {meta.label}
    </Badge>
  )
}

function Availability({
  available,
  reason,
  compact,
}: {
  available: boolean
  reason?: unknown
  compact?: boolean
}) {
  if (available) {
    return (
      <Badge variant="outline" className="rounded-md border-emerald-200 bg-emerald-50 text-emerald-800">
        可用
      </Badge>
    )
  }
  return (
    <span
      className={cn(
        "min-w-0 truncate text-sm text-muted-foreground",
        compact && "max-w-[160px] text-right text-xs",
      )}
      title={typeof reason === "string" ? reason : undefined}
    >
      {typeof reason === "string" && reason ? reason : "不可用"}
    </span>
  )
}

function MetaLabel({ children }: { children: React.ReactNode }) {
  return <div className="text-muted-foreground">{children}</div>
}

function MetaValue({ children }: { children: React.ReactNode }) {
  return <div className="mono min-w-0 truncate">{children}</div>
}

function emptyTerm(): Term {
  return { incorrect: "", correct: "", context: "" }
}

function normalizeTerm(term: Term): Term {
  return {
    incorrect: term.incorrect.trim(),
    correct: term.correct.trim(),
    context: term.context.trim(),
  }
}

const stageLabels: Record<string, string> = {
  api: "提交",
  downloading: "下载",
  normalizing: "音频处理",
  transcribing: "转录",
  llm_processing: "内容处理",
  processing: "任务处理",
}

const technicalErrorTailMarkers = [
  "Registered model keys",
  "Set FUNASR_IMPORT_DEBUG",
  "Recorded import failures",
  "Traceback",
]

function stageLabel(stage: string) {
  return stageLabels[stage] || stage || "任务处理"
}

function shortErrorMessage(message: string) {
  let summary = message.replace(/\s+/g, " ").trim() || "任务处理失败。"
  for (const marker of technicalErrorTailMarkers) {
    const index = summary.indexOf(marker)
    if (index > 0) {
      summary = summary.slice(0, index).replace(/[：:，,\s-]+$/, "")
      break
    }
  }
  if (summary.length <= 80) {
    return summary
  }
  return `${summary.slice(0, 80)}...`
}

function detectCreatorProfileInput(value: string) {
  const match = value.match(/https?:\/\/[^\s'"<>]+/i)
  if (!match) {
    return null
  }
  const rawUrl = match[0].replace(/[).,，。]+$/, "")
  try {
    const url = new URL(rawUrl)
    const host = url.hostname.toLowerCase()
    const path = url.pathname.replace(/\/+$/, "")
    if (host === "xhslink.com" && path.startsWith("/m/")) {
      return "xiaohongshu"
    }
    if (host.endsWith("xiaohongshu.com") && path.startsWith("/user/profile/")) {
      return "xiaohongshu"
    }
    if ((host.endsWith("douyin.com") || host.endsWith("iesdouyin.com"))
      && (path.startsWith("/user/") || path.startsWith("/share/user/"))) {
      return "douyin"
    }
  } catch {
    return null
  }
  return null
}

function parseRoute(): Route {
  const path = window.location.pathname
  if (path === "/metrics") {
    return { name: "metrics" }
  }
  if (path === "/settings") {
    return { name: "settings" }
  }
  return { name: "dashboard" }
}

function handleRequestError(
  error: unknown,
  setAuthRequired: (value: boolean) => void,
  setNotice: (notice: Notice) => void,
) {
  if (error instanceof ApiError && error.status === 401) {
    setAuthRequired(true)
    setNotice({ tone: "error", text: "API token 无效或缺失。" })
    return
  }
  if (isNetworkError(error)) {
    setNotice({ tone: "error", text: "本地服务已断开，请重新启动服务后刷新。" })
    return
  }
  setNotice({ tone: "error", text: error instanceof Error ? error.message : "请求失败。" })
}

function isNetworkError(error: unknown) {
  return error instanceof TypeError || (error instanceof Error && error.message === "Failed to fetch")
}

function filename(value: string) {
  try {
    const url = new URL(value)
    return url.pathname.split("/").filter(Boolean).pop() || value
  } catch {
    return value.split("/").filter(Boolean).pop() || value
  }
}

function sourceLabel(job: JobRecord) {
  const platform = job.metadata?.platform
  if (typeof platform === "string" && platform) {
    return platformName(platform)
  }
  if (job.source_type === "upload") {
    return "本地上传"
  }
  if (/youtube\.com|youtu\.be/i.test(job.source_value)) {
    return "YouTube"
  }
  if (/bilibili\.com|b23\.tv/i.test(job.source_value)) {
    return "Bilibili"
  }
  if (/xiaoyuzhoufm\.com/i.test(job.source_value)) {
    return "小宇宙"
  }
  return "链接"
}

function platformName(name: string) {
  const map: Record<string, string> = {
    youtube: "YouTube",
    bilibili: "Bilibili",
    xiaoyuzhou: "小宇宙",
    douyin: "抖音",
    xiaohongshu: "小红书",
    local_file: "本地文件",
    direct_media: "媒体直链",
    direct_media_url: "媒体直链",
    sharing_text: "分享文案",
  }
  return map[name] || name
}

function creatorPreviewStatus(preview: CreatorPreviewResponse, targetCount: number) {
  const scanned = preview.pagination.scanned_count
  const fetched = preview.pagination.fetched_count || preview.items.length
  const filtered = preview.pagination.filtered_count
  const scanText = scanned > 0 ? `已扫描 ${scanned} 条作品` : "已完成扫描"
  const filteredText = filtered > 0 ? `，过滤 ${filtered} 条不可转录作品` : ""
  switch (preview.pagination.stop_reason) {
    case "target_reached":
      return `已找到目标数量，${scanText}${filteredText}。`
    case "no_more":
      return `找到 ${fetched} 个视频，平台没有更多作品，${scanText}${filteredText}。`
    case "page_limit":
    case "scan_limit":
      return `找到 ${fetched} 个视频，已达到本次扫描上限，${scanText}${filteredText}。`
    case "cursor_stalled":
      return `找到 ${fetched} 个视频，分页游标未变化，已停止扫描。`
    default:
      return `找到 ${fetched} / ${targetCount} 个视频，${scanText}${filteredText}。`
  }
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)
}

function formatMs(value: number | null | undefined) {
  if (value == null) {
    return "-"
  }
  return formatSeconds(value / 1000)
}

function formatSeconds(value: number | null | undefined) {
  if (value == null) {
    return "-"
  }
  if (value < 60) {
    return `${value.toFixed(1)}s`
  }
  return `${(value / 60).toFixed(1)}m`
}

function formatDurationRatio(value: number | null | undefined) {
  if (value == null) {
    return "-"
  }
  return `${value.toFixed(2)}x`
}

function formatPercent(value: number | null | undefined) {
  if (value == null) {
    return "-"
  }
  return `${value.toFixed(1)}%`
}

function formatMb(value: number | null | undefined) {
  if (value == null) {
    return "-"
  }
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)}GB`
  }
  return `${value.toFixed(0)}MB`
}

function formatInteger(value: number | null | undefined) {
  if (value == null) {
    return "-"
  }
  return new Intl.NumberFormat("zh-CN").format(Math.round(value))
}

function formatTokenUsage(value: number | null | undefined) {
  if (value == null) {
    return "-"
  }
  return `${formatInteger(value)} tokens`
}

function formatCompactNumber(value: number | null | undefined) {
  if (value == null) {
    return "-"
  }
  return new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(value)
}

function unavailableReason(resources: MetricsOverview["resources"] | undefined) {
  if (!resources) {
    return "等待采样"
  }
  return resources.reason || "资源快照不可用"
}

function artifactLabel(type: string) {
  const map: Record<string, string> = {
    document_md: "Markdown",
    document_pdf: "PDF",
    spreadsheet_xlsx: "Excel",
  }
  return map[type] || type
}

function artifactShortLabel(type: string) {
  const map: Record<string, string> = {
    document_md: "Markdown",
    document_pdf: "PDF",
    spreadsheet_xlsx: "Excel",
  }
  return map[type] || type
}

function readCapability(entry: Record<string, unknown> | undefined, key: string) {
  const value = entry?.[key]
  return typeof value === "string" && value ? value : "-"
}

export default App
