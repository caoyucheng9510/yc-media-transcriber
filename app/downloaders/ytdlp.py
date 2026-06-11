from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.downloaders.bilibili_headers import bilibili_media_headers
from app.downloaders.bilibili_tikhub import BilibiliTikHubFallback
from app.downloaders.base import DownloadResult, Downloader
from app.downloaders.vtt import parse_vtt
from app.downloaders.youtube_tikhub import YouTubeTikHubFallback, has_tikhub_key
from app.errors import AppError
from app.source_resolver import ResolvedSource


class YtDlpDownloader(Downloader):
    def __init__(self, settings: Settings, platform: str):
        self.settings = settings
        self.platform = platform

    def download(
        self,
        source: ResolvedSource,
        job_temp_dir: Path,
        options: dict,
        metrics: Any | None = None,
    ) -> DownloadResult:
        try:
            import yt_dlp
        except ImportError as exc:
            return self._download_with_tikhub_fallback(
                source,
                job_temp_dir,
                options,
                "yt-dlp 未安装，无法解析该平台。",
                cause=exc,
                metrics=metrics,
            )

        job_temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            if metrics is not None:
                metrics.record_yt_dlp_invocation(purpose="extract_info")
            info = self._extract_info(yt_dlp, source.url)
        except Exception as exc:
            return self._download_with_tikhub_fallback(
                source,
                job_temp_dir,
                options,
                f"yt-dlp 元数据解析失败：{exc}",
                cause=exc,
                metrics=metrics,
            )

        metadata = self._metadata_from_info(info, source)
        wants_speaker = bool(options.get("speaker_diarization"))
        if self.platform == "youtube" and not wants_speaker:
            subtitles = self._fetch_youtube_subtitles(info, metrics=metrics)
            if subtitles:
                return DownloadResult(
                    source_path=None,
                    metadata={**metadata, "transcript_source": "youtube_subtitle"},
                    source_fingerprint=source.fingerprint,
                    pretranscribed_segments=subtitles,
                )
            subtitles = self._fetch_youtube_tikhub_subtitles(source, metrics=metrics)
            if subtitles:
                return DownloadResult(
                    source_path=None,
                    metadata={
                        **metadata,
                        "provider": "tikhub",
                        "transcript_source": "youtube_subtitle",
                        "subtitle_provider": "tikhub",
                    },
                    source_fingerprint=source.fingerprint,
                    pretranscribed_segments=subtitles,
                )

        output_template = str(job_temp_dir / "source.%(ext)s")
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "quiet": True,
            "noplaylist": True,
            "postprocessors": [],
            "http_headers": self._http_headers(),
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if metrics is not None:
                    metrics.record_yt_dlp_invocation(purpose="download")
                downloaded_info = ydl.extract_info(source.url, download=True)
        except Exception as exc:
            return self._download_with_tikhub_fallback(
                source,
                job_temp_dir,
                options,
                f"yt-dlp 下载失败：{exc}",
                cause=exc,
                metrics=metrics,
            )
        source_path = self._find_downloaded_file(job_temp_dir, downloaded_info)
        return DownloadResult(
            source_path=source_path,
            metadata=metadata,
            source_fingerprint=source.fingerprint,
        )

    def _extract_info(self, yt_dlp: Any, url: str) -> dict:
        with yt_dlp.YoutubeDL(
            {
                "quiet": True,
                "skip_download": True,
                "noplaylist": True,
                "http_headers": self._http_headers(),
            }
        ) as ydl:
            return ydl.extract_info(url, download=False)

    def _metadata_from_info(self, info: dict, source: ResolvedSource) -> dict:
        return {
            "platform": self.platform,
            "title": info.get("title") or source.media_id or source.url,
            "author": info.get("uploader") or info.get("channel") or info.get("creator"),
            "description": info.get("description") or "",
            "published_at": info.get("upload_date"),
            "duration": info.get("duration"),
            "source_url": source.url,
            "display_url": source.display_url or source.url,
            "media_id": source.media_id,
        }

    def _http_headers(self) -> dict[str, str]:
        if self.platform != "bilibili":
            return {}
        return bilibili_media_headers()

    def _fetch_youtube_subtitles(self, info: dict, metrics: Any | None = None) -> list:
        subtitle_groups = [info.get("subtitles") or {}, info.get("automatic_captions") or {}]
        language_order = [
            "zh-Hans",
            "zh-CN",
            "zh",
            "zh-Hant",
            "en",
            "en-US",
        ]
        for subtitles in subtitle_groups:
            for language in language_order + list(subtitles.keys()):
                entries = subtitles.get(language) or []
                for entry in entries:
                    if entry.get("ext") != "vtt" or not entry.get("url"):
                        continue
                    started = time.perf_counter()
                    status_code: int | None = None
                    error_code: str | None = None
                    try:
                        response = httpx.get(entry["url"], timeout=30.0, follow_redirects=True)
                        status_code = response.status_code
                        response.raise_for_status()
                    except httpx.HTTPError as exc:
                        error_code = exc.__class__.__name__
                        if metrics is not None:
                            metrics.record_http_request(
                                provider="youtube_subtitle",
                                method="GET",
                                endpoint=_safe_endpoint(entry["url"]),
                                status_code=status_code,
                                duration_ms=int((time.perf_counter() - started) * 1000),
                                request_kind="subtitle",
                                error_code=error_code,
                            )
                        continue
                    if metrics is not None:
                        metrics.record_http_request(
                            provider="youtube_subtitle",
                            method="GET",
                            endpoint=_safe_endpoint(entry["url"]),
                            status_code=status_code,
                            duration_ms=int((time.perf_counter() - started) * 1000),
                            request_kind="subtitle",
                            bytes_received=len(response.content),
                        )
                    segments = parse_vtt(response.text)
                    if segments:
                        return segments
        return []

    def _find_downloaded_file(self, job_temp_dir: Path, downloaded_info: dict) -> Path:
        requested = downloaded_info.get("requested_downloads") or []
        for item in requested:
            filepath = item.get("filepath")
            if filepath and Path(filepath).exists():
                return Path(filepath)
        candidates = [path for path in job_temp_dir.iterdir() if path.is_file()]
        if not candidates:
            raise AppError("download_failed", "yt-dlp 未生成下载文件。", "downloading")
        return max(candidates, key=lambda item: item.stat().st_size)

    def _fetch_youtube_tikhub_subtitles(
        self,
        source: ResolvedSource,
        metrics: Any | None = None,
    ) -> list:
        if self.platform != "youtube":
            return []
        if not self.settings.tikhub_enable_youtube_fallback or not has_tikhub_key(self.settings):
            return []
        return YouTubeTikHubFallback(self.settings, metrics=metrics).fetch_subtitle_segments(source)

    def _download_with_tikhub_fallback(
        self,
        source: ResolvedSource,
        job_temp_dir: Path,
        options: dict,
        reason: str,
        *,
        cause: BaseException | None = None,
        metrics: Any | None = None,
    ) -> DownloadResult:
        if not self._can_use_tikhub_fallback():
            raise AppError("download_failed", reason, "downloading") from cause
        try:
            if self.platform == "youtube":
                return YouTubeTikHubFallback(self.settings, metrics=metrics).download(
                    source,
                    job_temp_dir,
                    options,
                    metrics=metrics,
                )
            if self.platform == "bilibili":
                return BilibiliTikHubFallback(self.settings, metrics=metrics).download(
                    source,
                    job_temp_dir,
                    options,
                    metrics=metrics,
                )
        except AppError as exc:
            raise AppError(
                "download_failed",
                f"{reason}；TikHub fallback 也失败：{exc.message}",
                "downloading",
            ) from exc
        raise AppError("download_failed", reason, "downloading") from cause

    def _can_use_tikhub_fallback(self) -> bool:
        if not has_tikhub_key(self.settings):
            return False
        if self.platform == "youtube":
            return self.settings.tikhub_enable_youtube_fallback
        if self.platform == "bilibili":
            return self.settings.tikhub_enable_bilibili_fallback
        return False


def _safe_endpoint(url: str) -> str:
    parsed = urlparse(url)
    return parsed.hostname or "unknown"
