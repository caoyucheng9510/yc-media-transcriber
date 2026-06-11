from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.config import Settings
from app.downloaders.base import DownloadResult, Downloader
from app.errors import AppError
from app.media.ffmpeg import MEDIA_EXTENSIONS
from app.source_resolver import ResolvedSource
from app.source_resolver.ssrf import assert_safe_url


CONTENT_TYPE_EXTENSIONS = {
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
    "audio/x-aac": ".aac",
    "audio/x-m4a": ".m4a",
    "audio/x-wav": ".wav",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
}


class DirectMediaDownloader(Downloader):
    def __init__(
        self,
        settings: Settings,
        extra_host_allowlist: tuple[str, ...] = (),
        request_headers: dict[str, str] | None = None,
    ):
        self.settings = settings
        self.extra_host_allowlist = extra_host_allowlist
        self.request_headers = request_headers or {}

    def download(
        self,
        source: ResolvedSource,
        job_temp_dir: Path,
        options: dict,
        metrics: Any | None = None,
    ) -> DownloadResult:
        job_temp_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        total = 0
        response_status: int | None = None
        response: httpx.Response | None = None
        target: Path | None = None
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=60.0, follow_redirects=False) as client:
                response = self._open_safe_stream(client, source.url, metrics=metrics)
                response_status = response.status_code
                suffix = _infer_media_suffix(str(response.url), response.headers.get("content-type"))
                target = job_temp_dir / f"source{suffix}"
                try:
                    with target.open("wb") as fh:
                        for chunk in response.iter_bytes():
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > self.settings.max_upload_bytes:
                                raise AppError("resource_limited", "下载文件超过大小限制。", "downloading")
                            digest.update(chunk)
                            fh.write(chunk)
                finally:
                    response.close()
        except AppError:
            raise
        except httpx.HTTPError as exc:
            raise AppError("download_failed", f"媒体直链下载失败：{exc}", "downloading") from exc
        finally:
            if metrics is not None and (response_status is not None or total > 0):
                metrics.record_http_request(
                    provider="direct_media",
                    method="GET",
                    endpoint=_safe_endpoint(source.url),
                    status_code=response_status,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    request_kind="media_download",
                    bytes_received=total or None,
                )
        if total <= 0:
            raise AppError("download_failed", "下载结果为空。", "downloading")
        if target is None:
            raise AppError("download_failed", "媒体直链下载未生成文件。", "downloading")
        return DownloadResult(
            source_path=target,
            metadata={
                "platform": "direct_media",
                "title": Path(urlparse(source.url).path).name or "direct-media",
                "source_url": source.url,
                "display_url": source.display_url or source.url,
                "media_size_bytes": total,
            },
            source_fingerprint=digest.hexdigest(),
        )

    def _open_safe_stream(
        self,
        client: httpx.Client,
        url: str,
        metrics: Any | None = None,
    ) -> httpx.Response:
        current_url = url
        for attempt in range(5):
            assert_safe_url(
                current_url,
                allow_private=self.settings.app_allow_private_urls,
                host_allowlist=self.settings.app_private_url_allowlist + self.extra_host_allowlist,
                trusted_media_host_suffixes=self.settings.app_trusted_media_host_suffixes,
                fake_ip_cidrs=self.settings.app_media_fake_ip_cidrs,
            )
            request = client.build_request("GET", current_url, headers=self.request_headers)
            started = time.perf_counter()
            response = client.send(request, stream=True)
            if response.status_code not in {301, 302, 303, 307, 308}:
                if response.status_code >= 400 and metrics is not None:
                    metrics.record_http_request(
                        provider="direct_media",
                        method="GET",
                        endpoint=_safe_endpoint(current_url),
                        status_code=response.status_code,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                        request_kind="media_download",
                        error_code="HTTPStatusError",
                    )
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError:
                    response.close()
                    raise
                return response
            if metrics is not None:
                metrics.record_http_request(
                    provider="direct_media",
                    method="GET",
                    endpoint=_safe_endpoint(current_url),
                    status_code=response.status_code,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    request_kind="redirect",
                    retry_attempt=attempt + 1,
                )
            location = response.headers.get("location")
            response.close()
            if not location:
                raise AppError("download_failed", "下载重定向缺少 Location。", "downloading")
            current_url = urljoin(str(response.url), location)
        raise AppError("download_failed", "下载重定向次数过多。", "downloading")


def _safe_endpoint(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or "unknown"
    suffix = Path(parsed.path).suffix
    return f"{host}{suffix}" if suffix else host


def _infer_media_suffix(url: str, content_type: str | None, default: str = ".media") -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in MEDIA_EXTENSIONS:
        return suffix
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    return CONTENT_TYPE_EXTENSIONS.get(media_type, default)
