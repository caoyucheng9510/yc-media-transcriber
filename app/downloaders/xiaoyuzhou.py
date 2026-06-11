from __future__ import annotations

import html
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.downloaders.base import DownloadResult, Downloader
from app.downloaders.direct import DirectMediaDownloader
from app.errors import AppError
from app.source_resolver import ResolvedSource


META_RE = re.compile(
    r'<meta\s+(?:property|name)=["\'](?P<name>[^"\']+)["\']\s+content=["\'](?P<content>[^"\']*)["\']',
    re.IGNORECASE,
)


class XiaoyuzhouDownloader(Downloader):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.direct = DirectMediaDownloader(settings)

    def download(
        self,
        source: ResolvedSource,
        job_temp_dir: Path,
        options: dict,
        metrics: Any | None = None,
    ) -> DownloadResult:
        started = time.perf_counter()
        status_code: int | None = None
        error_code: str | None = None
        try:
            response = httpx.get(source.url, follow_redirects=True, timeout=30.0)
            status_code = response.status_code
            response.raise_for_status()
        except httpx.HTTPError as exc:
            error_code = exc.__class__.__name__
            raise AppError("download_failed", f"小宇宙页面请求失败：{exc}", "downloading") from exc
        finally:
            if metrics is not None:
                metrics.record_http_request(
                    provider="xiaoyuzhou",
                    method="GET",
                    endpoint=_safe_endpoint(source.url),
                    status_code=status_code,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    request_kind="page",
                    error_code=error_code,
                )
        metadata = self._extract_metadata(response.text, source.url)
        audio_url = metadata.get("audio_url")
        if not audio_url:
            raise AppError("download_failed", "小宇宙页面未找到音频地址。", "downloading")
        media_source = ResolvedSource(
            kind="url",
            platform="direct_media",
            url=str(audio_url),
            media_id=source.media_id,
            normalized_url=str(audio_url),
            original_text=source.original_text,
            input_url=source.input_url,
            display_url=source.display_url,
        )
        result = self.direct.download(media_source, job_temp_dir, options, metrics=metrics)
        result.metadata = {
            **result.metadata,
            **metadata,
            "platform": "xiaoyuzhou",
            "source_url": source.url,
            "display_url": source.display_url or source.url,
            "media_id": source.media_id,
        }
        result.source_fingerprint = source.fingerprint
        return result

    def _extract_metadata(self, page: str, url: str) -> dict:
        values: dict[str, str] = {}
        for match in META_RE.finditer(page):
            values[match.group("name")] = html.unescape(match.group("content"))
        return {
            "title": values.get("og:title") or values.get("twitter:title") or "小宇宙单集",
            "description": values.get("og:description") or "",
            "author": values.get("article:author") or values.get("og:site_name") or "小宇宙",
            "audio_url": values.get("og:audio") or values.get("og:audio:url"),
            "source_url": url,
        }


def _safe_endpoint(url: str) -> str:
    return urlparse(url).hostname or "unknown"
