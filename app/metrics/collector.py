from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from app.config import Settings
from app.storage import SQLiteStore
from app.storage.sqlite import utc_now


logger = logging.getLogger(__name__)


class JobMetricsCollector:
    def __init__(self, job_id: str, store: SQLiteStore, settings: Settings):
        self.job_id = job_id
        self.store = store
        self.settings = settings
        self.enabled = settings.metrics_enabled
        self._lock = threading.RLock()
        self._started_monotonic: float | None = None
        self._created_at: str | None = None
        self._started_at: str | None = None
        self._source_type = ""
        self._stage_durations: dict[str, float] = {}
        self._http_requests: list[dict[str, Any]] = []
        self._llm_usage: list[dict[str, Any]] = []
        self._http_requests_total = 0
        self._tikhub_calls_total = 0
        self._tikhub_http_attempts_total = 0
        self._yt_dlp_invocations = 0
        self._llm_calls_total = 0
        self._llm_prompt_tokens = 0
        self._llm_completion_tokens = 0
        self._llm_total_tokens = 0
        self._cache_hit: bool | None = None
        self._download_bytes = 0
        self._media_duration_seconds: float | None = None
        self._media_size_bytes: int | None = None

    def start(self, *, created_at: str, source_type: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._created_at = created_at
            self._source_type = source_type
            self._started_at = utc_now()
            self._started_monotonic = time.perf_counter()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            with self._lock:
                self._stage_durations[name] = self._stage_durations.get(name, 0.0) + elapsed

    def record_http_request(
        self,
        *,
        provider: str,
        method: str,
        endpoint: str,
        status_code: int | None,
        duration_ms: int,
        request_kind: str = "http",
        bytes_received: int | None = None,
        retry_attempt: int | None = None,
        error_code: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        safe_item = {
            "provider": _safe_text(provider, 80),
            "method": _safe_text(method.upper(), 12),
            "endpoint": _safe_text(endpoint, 180),
            "status_code": status_code,
            "duration_ms": max(0, int(duration_ms)),
            "request_kind": _safe_text(request_kind, 40),
            "bytes_received": bytes_received,
            "retry_attempt": retry_attempt,
            "error_code": _safe_text(error_code, 80) if error_code else None,
        }
        with self._lock:
            self._http_requests_total += 1
            if safe_item["provider"] == "tikhub":
                self._tikhub_http_attempts_total += 1
            if bytes_received and bytes_received > 0 and request_kind == "media_download":
                self._download_bytes += int(bytes_received)
            if self.settings.metrics_record_http_details and len(self._http_requests) < 200:
                self._http_requests.append(safe_item)

    def record_tikhub_call(self, *, endpoint: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._tikhub_calls_total += 1

    def record_yt_dlp_invocation(self, *, purpose: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._yt_dlp_invocations += 1

    def record_llm_usage(
        self,
        *,
        provider: str,
        model: str,
        purpose: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        duration_ms: int,
        extra_usage: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        prompt_tokens = max(0, int(prompt_tokens or 0))
        completion_tokens = max(0, int(completion_tokens or 0))
        total_tokens = max(0, int(total_tokens or 0))
        item = {
            "provider": _safe_text(provider, 80),
            "model": _safe_text(model, 120),
            "purpose": _safe_text(purpose, 80),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "duration_ms": max(0, int(duration_ms or 0)),
        }
        if extra_usage:
            item["extra_usage"] = _safe_usage(extra_usage)
        with self._lock:
            self._llm_calls_total += 1
            self._llm_prompt_tokens += prompt_tokens
            self._llm_completion_tokens += completion_tokens
            self._llm_total_tokens += total_tokens
            if len(self._llm_usage) < 200:
                self._llm_usage.append(item)

    def record_cache_hit(self, hit: bool) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._cache_hit = hit

    def record_media_info(
        self,
        *,
        duration_seconds: float | None = None,
        size_bytes: int | None = None,
    ) -> None:
        if not self.enabled:
            return
        with self._lock:
            if duration_seconds is not None and duration_seconds >= 0:
                self._media_duration_seconds = float(duration_seconds)
            if size_bytes is not None and size_bytes >= 0:
                self._media_size_bytes = int(size_bytes)

    def finish(
        self,
        *,
        status: str,
        metadata: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        metadata = metadata or {}
        now = utc_now()
        try:
            record = self._build_record(status=status, metadata=metadata, error=error, finished_at=now)
            self.store.upsert_job_metrics(record)
        except Exception as exc:
            logger.warning("Failed to flush metrics for job %s: %s", self.job_id, exc)

    def close(self) -> None:
        return None

    def _build_record(
        self,
        *,
        status: str,
        metadata: dict[str, Any],
        error: dict[str, Any] | None,
        finished_at: str,
    ) -> dict[str, Any]:
        with self._lock:
            stage_durations = dict(self._stage_durations)
            llm_usage = list(self._llm_usage)
            http_requests = list(self._http_requests)
            media_duration_seconds = self._media_duration_seconds
            media_size_bytes = self._media_size_bytes
            download_bytes = self._download_bytes
            started_at = self._started_at or finished_at
            created_at = self._created_at or started_at
            started_monotonic = self._started_monotonic
            counters = {
                "http_requests_total": self._http_requests_total,
                "tikhub_calls_total": self._tikhub_calls_total,
                "tikhub_http_attempts_total": self._tikhub_http_attempts_total,
                "yt_dlp_invocations": self._yt_dlp_invocations,
                "llm_calls_total": self._llm_calls_total,
                "llm_prompt_tokens": self._llm_prompt_tokens,
                "llm_completion_tokens": self._llm_completion_tokens,
                "llm_total_tokens": self._llm_total_tokens,
            }
            cache_hit = self._cache_hit

        media_duration_seconds = _number_or_none(
            media_duration_seconds,
            metadata.get("duration"),
            metadata.get("media_duration_seconds"),
        )
        media_size_bytes = _int_or_none(
            media_size_bytes,
            metadata.get("media_size_bytes"),
            metadata.get("size_bytes"),
        )
        platform = _platform_from_metadata(metadata, self._source_type)
        download_seconds = stage_durations.get("downloading")
        normalizing_seconds = stage_durations.get("normalizing")
        transcribing_seconds = stage_durations.get("transcribing")
        llm_seconds = stage_durations.get("llm_processing")
        total_duration_ms = _duration_ms(created_at, finished_at)
        if total_duration_ms is None and started_monotonic is not None:
            total_duration_ms = int((time.perf_counter() - started_monotonic) * 1000)

        detail_json: dict[str, Any] = {}
        if error:
            detail_json["error"] = {
                "code": _safe_text(error.get("code"), 80),
                "stage": _safe_text(error.get("stage"), 80),
            }

        return {
            "job_id": self.job_id,
            "status": status,
            "source_type": self._source_type or "unknown",
            "platform": platform,
            "created_at": created_at,
            "started_at": started_at,
            "finished_at": finished_at,
            "updated_at": finished_at,
            "queue_wait_ms": _duration_ms(created_at, started_at),
            "total_duration_ms": total_duration_ms,
            "media_duration_seconds": media_duration_seconds,
            "media_size_bytes": media_size_bytes,
            "download_seconds": download_seconds,
            "download_bytes": download_bytes or None,
            "download_mb_per_second": _mb_per_second(download_bytes, download_seconds),
            "normalizing_seconds": normalizing_seconds,
            "normalizing_rtf": _rtf(normalizing_seconds, media_duration_seconds),
            "transcribing_seconds": transcribing_seconds if transcribing_seconds is not None else (0.0 if cache_hit else None),
            "asr_rtf": _rtf(transcribing_seconds, media_duration_seconds) if not cache_hit else 0.0,
            "llm_seconds": llm_seconds,
            "llm_calls_total": counters["llm_calls_total"],
            "llm_prompt_tokens": counters["llm_prompt_tokens"],
            "llm_completion_tokens": counters["llm_completion_tokens"],
            "llm_total_tokens": counters["llm_total_tokens"],
            "llm_tokens_per_second": _tokens_per_second(counters["llm_total_tokens"], llm_seconds),
            "http_requests_total": counters["http_requests_total"],
            "tikhub_calls_total": counters["tikhub_calls_total"],
            "tikhub_http_attempts_total": counters["tikhub_http_attempts_total"],
            "yt_dlp_invocations": counters["yt_dlp_invocations"],
            "cache_hit": None if cache_hit is None else int(cache_hit),
            "stage_durations_json": stage_durations,
            "http_requests_json": {"items": http_requests} if http_requests else {},
            "llm_usage_json": {"items": llm_usage} if llm_usage else {},
            "detail_json": detail_json,
        }


def _duration_ms(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        return max(0, int((_parse_datetime(end) - _parse_datetime(start)).total_seconds() * 1000))
    except ValueError:
        return None


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _number_or_none(*values: Any) -> float | None:
    for value in values:
        if value in (None, ""):
            continue
        try:
            result = float(value)
        except (TypeError, ValueError):
            continue
        if result >= 0:
            return result
    return None


def _int_or_none(*values: Any) -> int | None:
    for value in values:
        if value in (None, ""):
            continue
        try:
            result = int(value)
        except (TypeError, ValueError):
            continue
        if result >= 0:
            return result
    return None


def _rtf(seconds: float | None, duration_seconds: float | None) -> float | None:
    if seconds is None or not duration_seconds or duration_seconds <= 0:
        return None
    return seconds / duration_seconds


def _tokens_per_second(total_tokens: int, seconds: float | None) -> float | None:
    if total_tokens <= 0 or not seconds or seconds <= 0:
        return None
    return total_tokens / seconds


def _mb_per_second(bytes_received: int, seconds: float | None) -> float | None:
    if bytes_received <= 0 or not seconds or seconds <= 0:
        return None
    return bytes_received / 1024 / 1024 / seconds


def _platform_from_metadata(metadata: dict[str, Any], source_type: str) -> str | None:
    platform = metadata.get("platform")
    if isinstance(platform, str) and platform:
        return platform
    if source_type == "upload":
        return "local_file"
    return None


def _safe_text(value: Any, limit: int = 120) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").replace("\r", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _safe_usage(usage: dict[str, Any]) -> dict[str, int]:
    safe: dict[str, int] = {}
    for key, value in usage.items():
        if not isinstance(key, str):
            continue
        try:
            safe[key[:80]] = max(0, int(value or 0))
        except (TypeError, ValueError):
            continue
    return safe
