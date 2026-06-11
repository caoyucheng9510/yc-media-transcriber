from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.config import Settings
from app.downloaders.base import DownloadResult, Downloader
from app.downloaders.tikhub_client import TikHubClient
from app.downloaders.tikhub_models import TikHubMediaInfo
from app.downloaders.tikhub_utils import (
    collect_urls_from_paths,
    dedupe_urls,
    download_first_available,
    first_string,
    first_string_at_paths,
    stable_fingerprint,
)
from app.errors import AppError
from app.source_resolver import ResolvedSource
from app.source_resolver.short_url import resolve_short_url


AWEME_ID_PATTERNS = [
    re.compile(r"/video/(\d+)"),
    re.compile(r"/note/(\d+)"),
    re.compile(r"/(\d{10,})/?$"),
]

DOUYIN_ENDPOINTS = [
    ("web", "/api/v1/douyin/web/fetch_one_video", {"need_anchor_info": "false"}),
    ("web_v2", "/api/v1/douyin/web/fetch_one_video_v2", {}),
    ("app_v3", "/api/v1/douyin/app/v3/fetch_one_video", {}),
    ("app_v3_v2", "/api/v1/douyin/app/v3/fetch_one_video_v2", {}),
]

DOUYIN_MEDIA_URL_PATHS = [
    "music.play_url.uri",
    "music.play_url.url_list",
    "video.bit_rate_audio.audio_meta.url_list.main_url",
    "video.bit_rate_audio.audio_meta.url_list.url_list",
    "video.play_addr.url_list",
    "video.download_addr.url_list",
    "video.play_addr.url_list.url",
    "video.download_addr.url_list.url",
]


class DouyinDownloader(Downloader):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = TikHubClient(settings)

    def download(
        self,
        source: ResolvedSource,
        job_temp_dir: Path,
        options: dict,
        metrics: Any | None = None,
    ) -> DownloadResult:
        if metrics is not None:
            self.client.metrics = metrics
        aweme_id, display_url = extract_aweme_id(source)
        media_info = self.fetch_media_info(source, aweme_id, display_url, metrics=metrics)
        result = download_first_available(
            settings=self.settings,
            urls=media_info.download_urls,
            source=source,
            job_temp_dir=job_temp_dir,
            options=options,
            media_id=aweme_id,
            metrics=metrics,
        )
        result.metadata = {
            "platform": "douyin",
            "provider": "tikhub",
            "title": media_info.title,
            "author": media_info.author,
            "description": media_info.description,
            "source_url": source.url,
            "display_url": display_url,
            "media_id": aweme_id,
            "download_method": "tikhub",
        }
        result.source_fingerprint = source.fingerprint if source.source_identity else stable_fingerprint("douyin", aweme_id)
        return result

    def fetch_media_info(
        self,
        source: ResolvedSource,
        aweme_id: str,
        display_url: str,
        metrics: Any | None = None,
    ) -> TikHubMediaInfo:
        failures: list[str] = []
        for name, endpoint, extra_params in DOUYIN_ENDPOINTS:
            params = {"aweme_id": aweme_id, **extra_params}
            try:
                payload = self.client.request(endpoint, params)
            except AppError as exc:
                if _should_stop_endpoint_fallback(exc):
                    raise
                failures.append(f"{name}:{exc.code}")
                continue

            detail = unwrap_aweme_detail(payload)
            urls = collect_douyin_media_urls(detail)
            if not urls:
                failures.append(f"{name}:no_media_url")
                continue
            title = first_string_at_paths(detail, ["desc", "item_title"]) or f"douyin_{aweme_id}"
            description = first_string_at_paths(detail, ["desc"]) or ""
            author = first_string_at_paths(detail, ["author.nickname", "author.name"])
            return TikHubMediaInfo(
                platform="douyin",
                media_id=aweme_id,
                title=title,
                author=author,
                description=description,
                source_url=source.url,
                display_url=display_url,
                download_urls=urls,
                extra={"endpoint": name},
            )

        raise AppError(
            "download_failed",
            f"TikHub 抖音解析失败，所有接口均未返回可下载媒体。{_failure_suffix(failures)}",
            "downloading",
        )


def extract_aweme_id(source: ResolvedSource) -> tuple[str, str]:
    url = source.url
    display_url = source.display_url or url
    host = (urlparse(url).hostname or "").lower()
    if host == "v.douyin.com":
        try:
            resolved_url = resolve_short_url(url, allowed_platforms={"douyin"})
        except AppError as exc:
            raise AppError("download_failed", "无法解析抖音短链。", "downloading") from exc
        url = resolved_url

    parsed = urlparse(url)
    query_id = first_string(parse_qs(parsed.query).get("aweme_id", [None])[0])
    if query_id:
        return query_id, display_url

    for pattern in AWEME_ID_PATTERNS:
        match = pattern.search(parsed.path)
        if match:
            return match.group(1), display_url

    if source.media_id and source.media_id.isdigit():
        return source.media_id, display_url

    raise AppError("download_failed", "无法从抖音链接中提取视频 ID。", "downloading")


def unwrap_aweme_detail(payload: dict) -> dict:
    data = payload.get("data")
    if isinstance(data, dict):
        for path in ("aweme_detail", "aweme", "data.aweme_detail", "data"):
            value = _value_at_path(data, path)
            if isinstance(value, dict):
                return value
        return data
    return payload


def collect_douyin_media_urls(detail: dict) -> list[str]:
    return dedupe_urls(collect_urls_from_paths(detail, DOUYIN_MEDIA_URL_PATHS))


def _value_at_path(payload: dict, path: str) -> object:
    current: object = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _should_stop_endpoint_fallback(exc: AppError) -> bool:
    if exc.code == "platform_provider_not_configured":
        return True
    return "授权失败" in exc.message


def _failure_suffix(failures: list[str]) -> str:
    if not failures:
        return ""
    return " 失败摘要：" + ", ".join(failures[:4])
