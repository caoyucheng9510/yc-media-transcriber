from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


JobStatus = Literal[
    "queued",
    "downloading",
    "normalizing",
    "transcribing",
    "llm_processing",
    "completed",
    "failed",
]

CreatorPreviewStopReason = Literal[
    "target_reached",
    "no_more",
    "page_limit",
    "scan_limit",
    "cursor_stalled",
]


class ErrorInfo(BaseModel):
    code: str
    message: str
    stage: str


class SourceInput(BaseModel):
    type: Literal["url", "text"] = "url"
    value: str = Field(min_length=1)


class JobOptions(BaseModel):
    asr_engine: str | None = None
    speaker_diarization: bool = False
    llm_polish: bool = True
    summary: bool = True


class CreateJobRequest(BaseModel):
    source: SourceInput
    options: JobOptions = Field(default_factory=JobOptions)


class CreateJobResponse(BaseModel):
    job_id: str
    status: JobStatus
    view_url: str


class BatchJobsRequest(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=200)


class BatchJobSkipped(BaseModel):
    job_id: str
    code: str
    message: str


class BatchDeleteResponse(BaseModel):
    deleted: list[str] = Field(default_factory=list)
    skipped: list[BatchJobSkipped] = Field(default_factory=list)


class BatchExportRequest(BatchJobsRequest):
    artifact_type: Literal["document_md", "document_pdf", "spreadsheet_xlsx"]


class CreatorPreviewRequest(BaseModel):
    platform: Literal["auto", "douyin", "xiaohongshu"] = "auto"
    input: str = Field(min_length=1)
    cursor: str | None = None
    page_size: int = Field(default=20, ge=1, le=20)
    max_pages: int = Field(default=3, ge=1, le=5)
    max_items: int = Field(default=20, ge=1, le=200)
    sort: Literal["latest", "hot"] = "latest"


class CreatorInfo(BaseModel):
    id: str | None = None
    name: str | None = None
    avatar_url: str | None = None
    profile_url: str | None = None
    description: str | None = None


class CreatorWorkItem(BaseModel):
    id: str
    platform: Literal["douyin", "xiaohongshu"]
    work_id: str
    type: str
    transcribable: bool
    title: str
    cover_url: str | None = None
    published_at: str | None = None
    duration_seconds: float | None = None
    stats: dict[str, int | None] = Field(default_factory=dict)
    source_url: str


class CreatorPagination(BaseModel):
    has_more: bool = False
    next_cursor: str | None = None
    fetched_pages: int = 0
    fetched_count: int = 0
    scanned_count: int = 0
    filtered_count: int = 0
    stop_reason: CreatorPreviewStopReason | None = None


class CreatorPreviewResponse(BaseModel):
    preview_id: str
    platform: Literal["douyin", "xiaohongshu"]
    creator: CreatorInfo
    items: list[CreatorWorkItem] = Field(default_factory=list)
    pagination: CreatorPagination


class CreatorSubmitRequest(BaseModel):
    preview_id: str = Field(min_length=1)
    selected_item_ids: list[str] = Field(min_length=1, max_length=200)
    options: JobOptions = Field(default_factory=JobOptions)


class CreatorSubmitCreated(BaseModel):
    item_id: str
    job_id: str
    source_url: str


class CreatorSubmitSkipped(BaseModel):
    item_id: str
    reason: str


class CreatorSubmitResponse(BaseModel):
    submission_id: str
    created: list[CreatorSubmitCreated] = Field(default_factory=list)
    skipped: list[CreatorSubmitSkipped] = Field(default_factory=list)


class Segment(BaseModel):
    start: float = 0.0
    end: float = 0.0
    speaker: str | None = None
    text: str


class ArtifactInfo(BaseModel):
    type: str
    path: str
    mime_type: str = "text/plain"


class JobRecord(BaseModel):
    id: str
    status: JobStatus
    source_type: str
    source_value: str
    options: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: ErrorInfo | None = None
    result: dict[str, Any] | None = None
    progress: int = 0
    title: str | None = None
    created_at: str
    updated_at: str


class StructuredTranscriptItem(BaseModel):
    start: float = 0.0
    end: float = 0.0
    speaker_label: str = ""
    speaker_name: str | None = None
    text: str = ""
    original_text: str | None = None


class LLMCalibrationChunk(BaseModel):
    index: int
    status: Literal["success", "fallback", "failed"]
    attempts: int = 0
    input_count: int = 0
    output_count: int = 0
    warning_codes: list[str] = Field(default_factory=list)
    validation_score: float | None = None


class LLMCalibrationDetail(BaseModel):
    mode: Literal["none", "plain_text", "structured_dialog"] = "none"
    total_chunks: int = 0
    success_count: int = 0
    fallback_count: int = 0
    failed_count: int = 0
    chunks: list[LLMCalibrationChunk] = Field(default_factory=list)


class LLMValidationDetail(BaseModel):
    enabled: bool = False
    validated_chunks: int = 0
    failed_chunks: int = 0
    warning_codes: list[str] = Field(default_factory=list)


class LLMKeyInfoDetail(BaseModel):
    names: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    technical_terms: list[str] = Field(default_factory=list)
    brands: list[str] = Field(default_factory=list)
    abbreviations: list[str] = Field(default_factory=list)
    foreign_terms: list[str] = Field(default_factory=list)
    other_entities: list[str] = Field(default_factory=list)


class LLMSpeakerInferenceDetail(BaseModel):
    speaker_mapping: dict[str, str] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)
    source_labels: list[str] = Field(default_factory=list)
    applied_mapping: dict[str, str] = Field(default_factory=dict)


class LLMDetail(BaseModel):
    enabled: bool = False
    prompt_version: str | None = None
    key_info: LLMKeyInfoDetail = Field(default_factory=LLMKeyInfoDetail)
    speaker_inference: LLMSpeakerInferenceDetail = Field(default_factory=LLMSpeakerInferenceDetail)
    calibration: LLMCalibrationDetail = Field(default_factory=LLMCalibrationDetail)
    validation: LLMValidationDetail = Field(default_factory=LLMValidationDetail)
    models: dict[str, str] = Field(default_factory=dict)


class JobResult(BaseModel):
    job_id: str
    status: JobStatus
    metadata: dict[str, Any] = Field(default_factory=dict)
    segments: list[Segment] = Field(default_factory=list)
    raw_transcript: str = ""
    polished_text: str | None = None
    summary: str | None = None
    key_points: list[str] = Field(default_factory=list)
    speaker_mapping: dict[str, str] = Field(default_factory=dict)
    quality_warnings: list[str] = Field(default_factory=list)
    structured_transcript: list[StructuredTranscriptItem] = Field(default_factory=list)
    llm_detail: LLMDetail = Field(default_factory=LLMDetail)
    artifacts: dict[str, str] = Field(default_factory=dict)


class JobListResponse(BaseModel):
    items: list[JobRecord] = Field(default_factory=list)


class CapabilitiesResponse(BaseModel):
    inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    platforms: dict[str, dict[str, Any]] = Field(default_factory=dict)
    asr: dict[str, Any] = Field(default_factory=dict)
    llm: dict[str, Any] = Field(default_factory=dict)
    exports: list[str] = Field(default_factory=list)
    batch_exports: list[str] = Field(default_factory=list)
    auth: dict[str, Any] = Field(default_factory=dict)


class Term(BaseModel):
    incorrect: str = ""
    correct: str = Field(min_length=1)
    context: str = ""


class TermsPayload(BaseModel):
    terms: list[Term] = Field(default_factory=list)
