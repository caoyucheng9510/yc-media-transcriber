export type JobStatus =
  | "queued"
  | "downloading"
  | "normalizing"
  | "transcribing"
  | "llm_processing"
  | "completed"
  | "failed"

export type ErrorInfo = {
  code: string
  message: string
  stage: string
}

export type JobOptions = {
  asr_engine?: string | null
  speaker_diarization: boolean
  llm_polish: boolean
  summary: boolean
}

export type JobRecord = {
  id: string
  status: JobStatus
  source_type: string
  source_value: string
  options: Record<string, unknown>
  metadata: Record<string, unknown>
  error: ErrorInfo | null
  result: JobResult | null
  progress: number
  title: string | null
  created_at: string
  updated_at: string
}

export type JobResult = {
  job_id: string
  status: JobStatus
  metadata: Record<string, unknown>
  segments: Array<{
    start: number
    end: number
    speaker?: string | null
    text: string
  }>
  raw_transcript: string
  polished_text: string | null
  summary: string | null
  key_points: string[]
  speaker_mapping: Record<string, string>
  quality_warnings: string[]
  structured_transcript: Array<{
    start: number
    end: number
    speaker_label: string
    speaker_name?: string | null
    text: string
    original_text?: string | null
  }>
  llm_detail: {
    enabled: boolean
    prompt_version?: string | null
    key_info?: {
      names: string[]
      places: string[]
      technical_terms: string[]
      brands: string[]
      abbreviations: string[]
      foreign_terms: string[]
      other_entities: string[]
    }
    speaker_inference?: {
      speaker_mapping: Record<string, string>
      confidence: Record<string, number>
      source_labels: string[]
      applied_mapping: Record<string, string>
    }
    calibration: {
      mode: "none" | "plain_text" | "structured_dialog"
      total_chunks: number
      success_count: number
      fallback_count: number
      failed_count: number
      chunks?: Array<{
        index: number
        status: "success" | "fallback" | "failed"
        attempts: number
        input_count: number
        output_count: number
        warning_codes: string[]
        validation_score?: number | null
      }>
    }
    validation: {
      enabled: boolean
      validated_chunks: number
      failed_chunks: number
      warning_codes: string[]
    }
    models: Record<string, string>
  }
  artifacts: Record<string, string>
}

export type JobListResponse = {
  items: JobRecord[]
}

export type BatchExportArtifactType = "document_md" | "document_pdf" | "spreadsheet_xlsx"

export type BatchDeleteResponse = {
  deleted: string[]
  skipped: Array<{
    job_id: string
    code: string
    message: string
  }>
}

export type CreatorInfo = {
  id?: string | null
  name?: string | null
  avatar_url?: string | null
  profile_url?: string | null
  description?: string | null
}

export type CreatorWorkItem = {
  id: string
  platform: "douyin" | "xiaohongshu"
  work_id: string
  type: string
  transcribable: boolean
  title: string
  cover_url?: string | null
  published_at?: string | null
  duration_seconds?: number | null
  stats: Record<string, number | null>
  source_url: string
}

export type CreatorPreviewResponse = {
  preview_id: string
  platform: "douyin" | "xiaohongshu"
  creator: CreatorInfo
  items: CreatorWorkItem[]
  pagination: {
    has_more: boolean
    next_cursor?: string | null
    fetched_pages: number
    fetched_count: number
    scanned_count: number
    filtered_count: number
    stop_reason?: "target_reached" | "no_more" | "page_limit" | "scan_limit" | "cursor_stalled" | null
  }
}

export type CreatorSubmitResponse = {
  submission_id: string
  created: Array<{
    item_id: string
    job_id: string
    source_url: string
  }>
  skipped: Array<{
    item_id: string
    reason: string
  }>
}

export type CapabilityEntry = {
  available?: boolean
  reason?: string | null
  [key: string]: unknown
}

export type CapabilitiesResponse = {
  inputs: Record<string, CapabilityEntry>
  platforms: Record<string, CapabilityEntry>
  asr: CapabilityEntry
  llm: CapabilityEntry
  exports: string[]
  batch_exports: string[]
  auth: {
    enabled?: boolean
  }
}

export type Term = {
  incorrect: string
  correct: string
  context: string
}

export type TermsPayload = {
  terms: Term[]
}

export type MetricsOverview = {
  enabled: boolean
  runtime: {
    mode: string
    uptime_seconds: number
  }
  resources: {
    available: boolean
    sampled_at?: string
    runtime_mode?: string
    reason?: string
    active_job_count?: number
    queue_depth?: number
    process_cpu_percent?: number | null
    process_rss_mb?: number | null
    process_children_count?: number | null
    system_cpu_percent?: number | null
    system_memory_used_mb?: number | null
    system_memory_total_mb?: number | null
    container_memory_current_mb?: number | null
    container_memory_limit_mb?: number | null
    memory_headroom_mb?: number | null
  }
  queue: {
    active_job_count: number
    queued_job_count: number
  }
  recent: {
    completed_24h: number
    failed_24h: number
    avg_asr_rtf_24h: number | null
    avg_llm_tokens_24h: number | null
  }
}

export type MetricsJob = {
  job_id: string
  title: string | null
  source_value: string
  status: JobStatus
  source_type: string
  platform: string | null
  created_at: string
  updated_at: string
  queue_wait_ms: number | null
  total_duration_ms: number | null
  media_duration_seconds: number | null
  media_size_bytes: number | null
  download_seconds: number | null
  download_bytes: number | null
  download_mb_per_second: number | null
  normalizing_seconds: number | null
  normalizing_rtf: number | null
  transcribing_seconds: number | null
  asr_rtf: number | null
  llm_seconds: number | null
  llm_calls_total: number
  llm_prompt_tokens: number
  llm_completion_tokens: number
  llm_total_tokens: number
  llm_tokens_per_second: number | null
  http_requests_total: number
  tikhub_calls_total: number
  tikhub_http_attempts_total: number
  yt_dlp_invocations: number
  cache_hit: boolean | null
}

export type MetricsJobsResponse = {
  enabled: boolean
  items: MetricsJob[]
}
