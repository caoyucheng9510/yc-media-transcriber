from __future__ import annotations

import json
import time
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response

from app.capabilities import build_capabilities
from app.config import Settings
from app.creator import CreatorService
from app.dependencies import get_settings, get_store, require_api_token
from app.errors import AppError, app_error_to_http_exception, http_error
from app.exporters.formats import USER_ARTIFACT_MIME_TYPES, safe_export_stem
from app.exporters.spreadsheet import XLSX_MIME_TYPE, build_batch_xlsx
from app.jobs.submission import JobSubmissionService
from app.schemas import (
    BatchDeleteResponse,
    BatchExportRequest,
    BatchJobSkipped,
    BatchJobsRequest,
    CapabilitiesResponse,
    CreateJobRequest,
    CreateJobResponse,
    CreatorPreviewRequest,
    CreatorPreviewResponse,
    CreatorSubmitRequest,
    CreatorSubmitResponse,
    JobListResponse,
    JobOptions,
    JobRecord,
    TermsPayload,
)
from app.storage import SQLiteStore


router = APIRouter(prefix="/api", dependencies=[Depends(require_api_token)])


@router.get("/capabilities", response_model=CapabilitiesResponse)
def capabilities(settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    return build_capabilities(settings)


@router.get("/metrics/overview")
def metrics_overview(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[SQLiteStore, Depends(get_store)],
) -> dict:
    queue = request.app.state.queue
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    runtime = {
        "mode": _runtime_mode(request),
        "uptime_seconds": int(time.monotonic() - getattr(request.app.state, "started_monotonic", time.monotonic())),
    }
    queue_payload = {
        "active_job_count": queue.active_job_count(),
        "queued_job_count": queue.queue_size(),
    }
    if not settings.metrics_enabled:
        return {
            "enabled": False,
            "runtime": runtime,
            "resources": {"available": False, "reason": "metrics_disabled"},
            "queue": queue_payload,
            "recent": {
                "completed_24h": 0,
                "failed_24h": 0,
                "avg_asr_rtf_24h": None,
                "avg_llm_tokens_24h": None,
            },
        }
    sampler = getattr(request.app.state, "resource_sampler", None)
    resources = (
        sampler.current_snapshot()
        if sampler is not None
        else {"available": False, "reason": "resource_sampler_missing"}
    )
    recent = store.summarize_recent_metrics(since=since)
    return {
        "enabled": True,
        "runtime": runtime,
        "resources": resources,
        "queue": queue_payload,
        "recent": recent,
    }


@router.get("/metrics/jobs")
def metrics_jobs(
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[SQLiteStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Annotated[str | None, Query()] = None,
    platform: Annotated[str | None, Query()] = None,
) -> dict:
    if not settings.metrics_enabled:
        return {"enabled": False, "items": []}
    return {
        "enabled": True,
        "items": store.list_job_metrics(
            status=status,
            platform=platform,
            limit=limit,
            offset=offset,
        ),
    }


@router.post("/jobs", response_model=CreateJobResponse)
def create_url_job(
    payload: CreateJobRequest,
    request: Request,
    store: Annotated[SQLiteStore, Depends(get_store)],
) -> CreateJobResponse:
    service = _submission_service(request, store)
    try:
        return service.create_url_job(
            source_type=payload.source.type,
            source_value=payload.source.value,
            options=payload.options,
        )
    except AppError as exc:
        raise app_error_to_http_exception(exc) from exc


@router.post("/creator/preview", response_model=CreatorPreviewResponse)
def preview_creator(
    payload: CreatorPreviewRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> CreatorPreviewResponse:
    service = CreatorService(settings=settings, cache=request.app.state.creator_previews)
    try:
        return service.preview(payload)
    except AppError as exc:
        raise app_error_to_http_exception(exc) from exc


@router.post("/creator/submit", response_model=CreatorSubmitResponse)
def submit_creator(
    payload: CreatorSubmitRequest,
    request: Request,
    store: Annotated[SQLiteStore, Depends(get_store)],
) -> CreatorSubmitResponse:
    service = CreatorService(settings=request.app.state.settings, cache=request.app.state.creator_previews)
    submission = _submission_service(request, store)
    try:
        return service.submit(payload, submission)
    except AppError as exc:
        raise app_error_to_http_exception(exc) from exc


@router.post("/jobs/upload", response_model=CreateJobResponse)
async def upload_job(
    request: Request,
    store: Annotated[SQLiteStore, Depends(get_store)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File()],
    options: Annotated[str, Form()] = "{}",
) -> CreateJobResponse:
    try:
        parsed_options = JobOptions.model_validate_json(options)
    except Exception as exc:
        raise http_error(400, "invalid_options", f"options 不是有效 JSON：{exc}") from exc

    try:
        service = _submission_service(request, store, settings)
        return await service.create_upload_job(file=file, options=parsed_options)
    except AppError as exc:
        raise app_error_to_http_exception(exc) from exc


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    store: Annotated[SQLiteStore, Depends(get_store)],
    status: Annotated[str | None, Query()] = None,
    keyword: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobListResponse:
    return JobListResponse(
        items=store.list_jobs(status=status, keyword=keyword, limit=limit, offset=offset)
    )


@router.post("/jobs/batch-delete", response_model=BatchDeleteResponse)
def batch_delete_jobs(
    payload: BatchJobsRequest,
    request: Request,
    store: Annotated[SQLiteStore, Depends(get_store)],
) -> BatchDeleteResponse:
    service = _submission_service(request, store)
    deleted: list[str] = []
    skipped: list[BatchJobSkipped] = []
    for job_id in _unique_job_ids(payload.job_ids):
        try:
            service.delete_job(job_id)
            deleted.append(job_id)
        except AppError as exc:
            skipped.append(BatchJobSkipped(job_id=job_id, code=exc.code, message=exc.to_dict()["message"]))
    return BatchDeleteResponse(deleted=deleted, skipped=skipped)


@router.post("/jobs/batch-export")
def batch_export_jobs(
    payload: BatchExportRequest,
    store: Annotated[SQLiteStore, Depends(get_store)],
) -> Response:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    if payload.artifact_type == "spreadsheet_xlsx":
        workbook, exported_count = _build_batch_export_spreadsheet(payload, store)
        if exported_count == 0:
            raise http_error(409, "batch_export_empty", "没有可导出的已完成任务。")
        filename = f"transcripts-spreadsheet-{timestamp}.xlsx"
        return Response(
            content=workbook.getvalue(),
            media_type=XLSX_MIME_TYPE,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    archive, exported_count = _build_batch_export_archive(payload, store)
    if exported_count == 0:
        raise http_error(409, "batch_export_empty", "没有可导出的已完成任务。")

    export_name = payload.artifact_type.replace("_", "-")
    filename = f"transcripts-{export_name}-{timestamp}.zip"
    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/jobs/{job_id}")
def get_job(job_id: str, store: Annotated[SQLiteStore, Depends(get_store)]) -> dict:
    try:
        return store.get_job(job_id).model_dump()
    except KeyError as exc:
        raise http_error(404, "job_not_found", "任务不存在。") from exc


@router.get("/jobs/{job_id}/result")
def get_job_result(job_id: str, store: Annotated[SQLiteStore, Depends(get_store)]) -> dict:
    try:
        job = store.get_job(job_id)
    except KeyError as exc:
        raise http_error(404, "job_not_found", "任务不存在。") from exc
    if job.status == "failed":
        return {"status": job.status, "error": job.error.model_dump() if job.error else None}
    if not job.result:
        return {"status": job.status, "result": None}
    return job.result


@router.post("/jobs/{job_id}/retry", response_model=CreateJobResponse)
def retry_job(
    job_id: str,
    request: Request,
    store: Annotated[SQLiteStore, Depends(get_store)],
) -> CreateJobResponse:
    service = _submission_service(request, store)
    try:
        return service.retry_job(job_id)
    except AppError as exc:
        raise app_error_to_http_exception(exc) from exc


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(
    job_id: str,
    request: Request,
    store: Annotated[SQLiteStore, Depends(get_store)],
) -> Response:
    service = _submission_service(request, store)
    try:
        service.delete_job(job_id)
    except AppError as exc:
        raise app_error_to_http_exception(exc) from exc
    return Response(status_code=204)


@router.get("/jobs/{job_id}/artifacts/{artifact_type}")
def get_artifact(job_id: str, artifact_type: str, store: Annotated[SQLiteStore, Depends(get_store)]) -> FileResponse:
    if artifact_type not in USER_ARTIFACT_MIME_TYPES:
        raise http_error(404, "artifact_not_found", "产物不存在。")
    artifact = store.get_artifact(job_id, artifact_type)
    if not artifact:
        raise http_error(404, "artifact_not_found", "产物不存在。")
    path = Path(artifact["path"])
    if not path.exists():
        raise http_error(404, "artifact_not_found", "产物文件不存在。")
    return FileResponse(path, media_type=artifact["mime_type"], filename=path.name)


@router.get("/settings/terms", response_model=TermsPayload)
def get_terms(request: Request) -> TermsPayload:
    return request.app.state.terms.load()


@router.put("/settings/terms", response_model=TermsPayload)
def put_terms(payload: TermsPayload, request: Request) -> TermsPayload:
    return request.app.state.terms.save(payload)


def _submission_service(
    request: Request,
    store: SQLiteStore,
    settings: Settings | None = None,
) -> JobSubmissionService:
    return JobSubmissionService(
        settings=settings or request.app.state.settings,
        store=store,
        queue=request.app.state.queue,
    )


def _runtime_mode(request: Request) -> str:
    sampler = getattr(request.app.state, "resource_sampler", None)
    if sampler is not None:
        snapshot = sampler.current_snapshot()
        mode = snapshot.get("runtime_mode")
        if isinstance(mode, str) and mode:
            return mode
    if request.app.state.settings.app_data_dir == Path("/app/data"):
        return "docker"
    return "local"


def _unique_job_ids(job_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for job_id in job_ids:
        if job_id in seen:
            continue
        seen.add(job_id)
        unique.append(job_id)
    return unique


def _build_batch_export_archive(payload: BatchExportRequest, store: SQLiteStore) -> tuple[BytesIO, int]:
    archive = BytesIO()
    manifest: dict[str, list[dict[str, str]]] = {"exported": [], "skipped": []}
    exported_count = 0
    extension = ".pdf" if payload.artifact_type == "document_pdf" else ".md"

    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for job_id in _unique_job_ids(payload.job_ids):
            try:
                job = store.get_job(job_id)
            except KeyError:
                manifest["skipped"].append(
                    {"job_id": job_id, "code": "job_not_found", "message": "任务不存在。"}
                )
                continue

            if job.status != "completed":
                manifest["skipped"].append(
                    {"job_id": job_id, "code": "job_not_completed", "message": "只有已完成任务可以导出。"}
                )
                continue

            artifact = store.get_artifact(job_id, payload.artifact_type)
            if not artifact:
                manifest["skipped"].append(
                    {"job_id": job_id, "code": "artifact_not_found", "message": "产物不存在。"}
                )
                continue

            path = Path(artifact["path"])
            if not path.exists():
                manifest["skipped"].append(
                    {"job_id": job_id, "code": "artifact_not_found", "message": "产物文件不存在。"}
                )
                continue

            exported_count += 1
            stem = safe_export_stem(job.title or _metadata_title(job.metadata), job.id)
            archive_name = f"{exported_count:03d}-{stem}-{job.id}{extension}"
            zip_file.write(path, arcname=archive_name)
            manifest["exported"].append(
                {"job_id": job.id, "filename": archive_name, "artifact_type": payload.artifact_type}
            )

        zip_file.writestr(
            "_manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )

    archive.seek(0)
    return archive, exported_count


def _build_batch_export_spreadsheet(payload: BatchExportRequest, store: SQLiteStore) -> tuple[BytesIO, int]:
    jobs: list[JobRecord] = []
    for job_id in _unique_job_ids(payload.job_ids):
        try:
            job = store.get_job(job_id)
        except KeyError:
            continue

        if job.status != "completed":
            continue
        if not job.result:
            continue
        jobs.append(job)

    return build_batch_xlsx(jobs), len(jobs)


def _metadata_title(metadata: dict) -> str | None:
    title = metadata.get("title") if isinstance(metadata, dict) else None
    return str(title) if title else None
