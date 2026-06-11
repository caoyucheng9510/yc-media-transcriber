from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import Any

from app.asr.base import Transcriber
from app.config import Settings
from app.downloaders import DownloaderFactory
from app.errors import AppError, normalize_error
from app.exporters.formats import USER_ARTIFACT_MIME_TYPES, transcript_text, write_job_artifacts
from app.llm import LLMProcessor
from app.media import normalize_audio
from app.metrics import JobMetricsCollector
from app.schemas import JobOptions, JobResult, Segment
from app.source_resolver import SourceResolver
from app.storage import SQLiteStore
from app.storage.media_cache import MediaCacheStore, build_media_cache_key


logger = logging.getLogger(__name__)

class JobProcessor:
    def __init__(
        self,
        *,
        settings: Settings,
        store: SQLiteStore,
        transcriber: Transcriber,
        llm: LLMProcessor,
    ):
        self.settings = settings
        self.store = store
        self.transcriber = transcriber
        self.llm = llm
        self.resolver = SourceResolver(
            allow_private_urls=settings.app_allow_private_urls,
            private_url_allowlist=settings.app_private_url_allowlist,
        )
        self.downloaders = DownloaderFactory(settings)
        self.media_cache = MediaCacheStore(settings, store)

    def process(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        metrics = JobMetricsCollector(job_id, self.store, self.settings)
        metrics.start(created_at=job.created_at, source_type=job.source_type)
        try:
            self._process(job_id, metrics)
        except BaseException as exc:
            stage = "processing"
            if isinstance(exc, AppError):
                stage = exc.stage
            error = normalize_error(exc, stage)
            self.store.update_job(
                job_id,
                status="failed",
                progress=100,
                error=error,
            )
            metrics.finish(status="failed", metadata=self._safe_job_metadata(job_id), error=error)
        else:
            completed = self.store.get_job(job_id)
            metrics.finish(status=completed.status, metadata=completed.metadata)
        finally:
            metrics.close()
            shutil.rmtree(self.settings.temp_dir / job_id, ignore_errors=True)

    def _process(self, job_id: str, metrics: JobMetricsCollector) -> None:
        job = self.store.get_job(job_id)
        options = JobOptions.model_validate(job.options)
        job_dir = self.settings.jobs_dir / job_id
        temp_dir = self.settings.temp_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        source_path: Path | None = None
        metadata: dict[str, Any] = dict(job.metadata or {})
        segments: list[Segment] = []
        raw_transcript: str | None = None
        source_fingerprint: str | None = None
        cache_key: str | None = None
        cache_hit = False
        source_identity: str | None = None
        platform: str | None = None
        media_id: str | None = None

        if job.source_type == "upload":
            source_path = Path(job.source_value)
            if not source_path.is_file():
                raise AppError("source_file_missing", "上传文件不存在，请重新上传后再试。", "normalizing")
            metadata = {
                **metadata,
                "platform": "local_file",
                "title": source_path.name,
                "source_path": str(source_path),
                "media_size_bytes": source_path.stat().st_size,
            }
            source_fingerprint = _file_sha256(source_path)
            cache_key = build_media_cache_key(source_fingerprint, options, self.settings)
            cached = self.media_cache.get(cache_key)
            if cached:
                cache_hit = True
                metadata = _metadata_with_cache(
                    {**cached.metadata, **metadata},
                    cache_key,
                    hit=True,
                )
                segments = cached.segments
                raw_transcript = cached.raw_transcript
            else:
                metadata = _metadata_with_cache(metadata, cache_key, hit=False)
            self.store.update_job(
                job_id,
                status="transcribing" if cache_hit else "normalizing",
                progress=65 if cache_hit else 20,
                metadata=metadata,
                source_fingerprint=source_fingerprint,
                title=metadata["title"],
            )
        else:
            self.store.update_job(job_id, status="downloading", progress=10)
            resolved = self.resolver.resolve(job.source_type, job.source_value)
            platform = resolved.platform
            media_id = resolved.media_id
            source_identity = resolved.source_identity
            if source_identity:
                source_fingerprint = resolved.fingerprint
                cache_key = build_media_cache_key(source_fingerprint, options, self.settings)
                cached = self.media_cache.get(cache_key)
                if cached:
                    cache_hit = True
                    metadata = _metadata_with_cache({**metadata, **cached.metadata}, cache_key, hit=True)
                    segments = cached.segments
                    raw_transcript = cached.raw_transcript
                    self.store.update_job(
                        job_id,
                        status="transcribing",
                        progress=65,
                        metadata=metadata,
                        source_fingerprint=source_fingerprint,
                        title=metadata.get("title"),
                    )

            if not cache_hit:
                downloader = self.downloaders.create(resolved.platform)
                with metrics.stage("downloading"):
                    download_result = downloader.download(
                        resolved,
                        temp_dir,
                        options.model_dump(),
                        metrics=metrics,
                    )
                source_path = download_result.source_path
                metadata = {**metadata, **download_result.metadata}
                source_fingerprint = download_result.source_fingerprint
                segments = download_result.pretranscribed_segments
                platform = str(metadata.get("platform") or resolved.platform)
                media_id = metadata.get("media_id") or resolved.media_id
                source_identity = source_identity or _source_identity(platform, media_id)
                cache_key = build_media_cache_key(source_fingerprint, options, self.settings)

                cached = self.media_cache.get(cache_key)
                if cached:
                    cache_hit = True
                    metadata = _metadata_with_cache(
                        {**cached.metadata, **metadata},
                        cache_key,
                        hit=True,
                    )
                    segments = cached.segments
                    raw_transcript = cached.raw_transcript
                else:
                    metadata = _metadata_with_cache(metadata, cache_key, hit=False)

                self.store.update_job(
                    job_id,
                    status="normalizing" if source_path and not segments else "transcribing",
                    progress=35 if not cache_hit else 65,
                    metadata=metadata,
                    source_fingerprint=source_fingerprint,
                    title=metadata.get("title"),
                )

        metrics.record_cache_hit(cache_hit)

        if source_path and not segments:
            audio_path = job_dir / "audio.wav"
            with metrics.stage("normalizing"):
                media_info = normalize_audio(source_path, audio_path)
            metadata = _metadata_with_media_info(metadata, media_info.duration, media_info.size)
            metrics.record_media_info(
                duration_seconds=media_info.duration,
                size_bytes=media_info.size,
            )
            self.store.update_job(job_id, status="transcribing", progress=55, metadata=metadata)
            with metrics.stage("transcribing"):
                segments = self.transcriber.transcribe(audio_path, options)

        if raw_transcript is None:
            raw_transcript = transcript_text([segment.model_dump() for segment in segments])
        if not cache_hit and cache_key and source_fingerprint:
            self._save_media_cache(
                cache_key=cache_key,
                source_fingerprint=source_fingerprint,
                options=options,
                metadata=metadata,
                segments=segments,
                raw_transcript=raw_transcript,
                source_identity=source_identity,
                platform=platform or str(metadata.get("platform") or ""),
                media_id=media_id,
            )

        result: dict[str, Any] = {
            "job_id": job_id,
            "status": "completed",
            "metadata": metadata,
            "segments": [segment.model_dump() for segment in segments],
            "raw_transcript": raw_transcript,
            "polished_text": raw_transcript,
            "summary": None,
            "key_points": [],
            "speaker_mapping": {},
            "quality_warnings": [],
            "structured_transcript": [],
            "llm_detail": {"enabled": False},
            "artifacts": {},
        }

        if options.llm_polish or options.summary:
            self.store.update_job(job_id, status="llm_processing", progress=80)
            with metrics.stage("llm_processing"):
                llm_result = self.llm.process(
                    metadata=metadata,
                    raw_transcript=raw_transcript,
                    options=options,
                    segments=segments,
                    metrics=metrics,
                )
            result.update(llm_result)

        artifact_urls: dict[str, str] = {}
        for artifact_type in USER_ARTIFACT_MIME_TYPES:
            artifact_urls[artifact_type] = f"/api/jobs/{job_id}/artifacts/{artifact_type}"
        result["artifacts"] = artifact_urls
        result = JobResult.model_validate(result).model_dump(mode="json")
        artifacts = write_job_artifacts(job_dir, result)
        for artifact_type, path in artifacts.items():
            self.store.save_artifact(job_id, artifact_type, path, USER_ARTIFACT_MIME_TYPES[artifact_type])
        self.store.update_job(
            job_id,
            status="completed",
            progress=100,
            result=result,
            metadata=metadata,
            source_fingerprint=source_fingerprint,
            title=metadata.get("title"),
        )
        shutil.rmtree(temp_dir, ignore_errors=True)

    def _save_media_cache(
        self,
        *,
        cache_key: str,
        source_fingerprint: str,
        options: JobOptions,
        metadata: dict[str, Any],
        segments: list[Segment],
        raw_transcript: str,
        source_identity: str | None,
        platform: str | None,
        media_id: str | None,
    ) -> None:
        try:
            self.media_cache.save(
                cache_key=cache_key,
                source_fingerprint=source_fingerprint,
                options=options,
                metadata=metadata,
                segments=segments,
                raw_transcript=raw_transcript,
                source_identity=source_identity,
                platform=platform or None,
                media_id=media_id,
            )
        except Exception as exc:
            logger.warning("Failed to save media cache %s: %s", cache_key, exc)

    def _safe_job_metadata(self, job_id: str) -> dict[str, Any]:
        try:
            return self.store.get_job(job_id).metadata
        except Exception:
            return {}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_with_cache(metadata: dict[str, Any], cache_key: str, *, hit: bool) -> dict[str, Any]:
    payload = dict(metadata)
    payload["cache"] = {"hit": hit, "cache_key": cache_key}
    return payload


def _metadata_with_media_info(
    metadata: dict[str, Any],
    duration_seconds: float,
    size_bytes: int,
) -> dict[str, Any]:
    payload = dict(metadata)
    payload["duration"] = duration_seconds
    payload["media_duration_seconds"] = duration_seconds
    payload["media_size_bytes"] = size_bytes
    return payload

def _source_identity(platform: str | None, media_id: Any) -> str | None:
    if not platform or not media_id:
        return None
    return f"{platform}:{media_id}"
