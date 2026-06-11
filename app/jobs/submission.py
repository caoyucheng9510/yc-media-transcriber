from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.config import Settings
from app.errors import AppError
from app.schemas import CreateJobResponse, JobOptions
from app.source_resolver import detect_creator_profile_input
from app.storage import SQLiteStore


TERMINAL_STATUSES = {"completed", "failed"}


class JobSubmissionService:
    def __init__(self, *, settings: Settings, store: SQLiteStore, queue: Any):
        self.settings = settings
        self.store = store
        self.queue = queue

    def create_url_job(
        self,
        *,
        source_type: str,
        source_value: str,
        options: JobOptions,
        metadata: dict[str, Any] | None = None,
        title: str | None = None,
    ) -> CreateJobResponse:
        if detect_creator_profile_input(source_value):
            raise AppError(
                "creator_profile_input",
                "这是创作者主页链接，请使用“创作者主页”入口先拉取作品清单，再选择要转录的视频。",
                "api",
            )

        job_id = _new_job_id()
        self.store.create_job(
            job_id=job_id,
            source_type=source_type,
            source_value=source_value,
            options=options.model_dump(),
            metadata=metadata,
            title=title,
        )
        self.queue.enqueue(job_id)
        return CreateJobResponse(job_id=job_id, status="queued", view_url="/")

    async def create_upload_job(
        self,
        *,
        file: UploadFile,
        options: JobOptions,
    ) -> CreateJobResponse:
        job_id = _new_job_id()
        upload_dir = self.settings.upload_dir / job_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        filename = Path(file.filename or "upload.media").name
        target = upload_dir / filename
        total = 0
        try:
            with target.open("wb") as fh:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.settings.max_upload_bytes:
                        raise AppError("upload_too_large", "上传文件超过大小限制。", "upload")
                    fh.write(chunk)
            if total <= 0:
                raise AppError("media_invalid", "上传文件为空。", "upload")
            self.store.create_job(
                job_id=job_id,
                source_type="upload",
                source_value=str(target),
                options=options.model_dump(),
            )
            self.queue.enqueue(job_id)
            return CreateJobResponse(job_id=job_id, status="queued", view_url="/")
        except Exception:
            if total <= 0 or total > self.settings.max_upload_bytes:
                shutil.rmtree(upload_dir, ignore_errors=True)
            raise

    def retry_job(self, job_id: str) -> CreateJobResponse:
        try:
            job = self.store.get_job(job_id)
        except KeyError as exc:
            raise AppError("job_not_found", "任务不存在。", "api") from exc
        if job.status != "failed":
            raise AppError("job_not_retryable", "只有失败任务可以重试。", "api")

        shutil.rmtree(self.settings.jobs_dir / job_id, ignore_errors=True)
        shutil.rmtree(self.settings.temp_dir / job_id, ignore_errors=True)
        retried = self.store.reset_job_for_retry(job_id)
        self.queue.enqueue(job_id)
        return CreateJobResponse(job_id=job_id, status=retried.status, view_url="/")

    def delete_job(self, job_id: str) -> None:
        try:
            job = self.store.get_job(job_id)
        except KeyError as exc:
            raise AppError("job_not_found", "任务不存在。", "api") from exc
        if job.status not in TERMINAL_STATUSES:
            raise AppError("job_not_deletable", "只能删除已结束任务。", "api")

        media_cache_records = self._media_cache_records_for_job_upload(job_id)
        self.store.delete_job(job_id)
        shutil.rmtree(self.settings.jobs_dir / job_id, ignore_errors=True)
        shutil.rmtree(self.settings.temp_dir / job_id, ignore_errors=True)
        if job.source_type == "upload":
            shutil.rmtree(self.settings.upload_dir / job_id, ignore_errors=True)
        for record in media_cache_records:
            self.store.delete_media_cache(record["cache_key"])
            _delete_media_cache_dir(self.settings, record["cache_dir"])

    def _media_cache_records_for_job_upload(self, job_id: str) -> list[dict[str, Any]]:
        upload_dir = _resolve_path(self.settings.upload_dir / job_id)
        records: list[dict[str, Any]] = []
        for record in self.store.list_media_cache_records():
            source_path = record.get("metadata", {}).get("source_path")
            if not isinstance(source_path, str):
                continue
            if _is_relative_to(_resolve_path(Path(source_path)), upload_dir):
                records.append(record)
        return records


def _new_job_id() -> str:
    return f"job_{uuid.uuid4().hex[:16]}"


def _delete_media_cache_dir(settings: Settings, raw_path: str) -> None:
    media_root = _resolve_path(settings.cache_dir / "media")
    cache_dir = _resolve_path(Path(raw_path))
    if cache_dir == media_root or not _is_relative_to(cache_dir, media_root):
        return
    shutil.rmtree(cache_dir, ignore_errors=True)


def _resolve_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_relative_to(path: Path, root: Path) -> bool:
    return path == root or root in path.parents
