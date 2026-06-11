from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config import Settings
from app.downloaders.base import DownloadResult, Downloader
from app.downloaders.tikhub_client import TikHubClient
from app.downloaders.tikhub_models import TikHubMediaInfo
from app.downloaders.tikhub_utils import (
    collect_urls_from_paths,
    dedupe_urls,
    download_first_available,
    first_string_at_paths,
    first_value_at_paths,
    stable_fingerprint,
)
from app.errors import AppError
from app.source_resolver import ResolvedSource
from app.source_resolver.short_url import resolve_short_url


NOTE_ID_RE = re.compile(r"(?:explore|discovery/item|items)/([0-9A-Za-z]+)")
RAW_NOTE_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")


@dataclass(frozen=True)
class XiaohongshuEndpoint:
    name: str
    endpoint: str
    require_note_id: bool = False
    extra_params: dict[str, str] | None = None


XIAOHONGSHU_ENDPOINTS = [
    XiaohongshuEndpoint("app_v2_video", "/api/v1/xiaohongshu/app_v2/get_video_note_detail"),
    XiaohongshuEndpoint("web_v7", "/api/v1/xiaohongshu/web/get_note_info_v7"),
    XiaohongshuEndpoint("web_v4", "/api/v1/xiaohongshu/web/get_note_info_v4"),
    XiaohongshuEndpoint("app_v2_note", "/api/v1/xiaohongshu/app/get_note_info_v2"),
    XiaohongshuEndpoint(
        "app_note",
        "/api/v1/xiaohongshu/app/get_note_info",
        extra_params={"force_video_enabled": "true"},
    ),
    XiaohongshuEndpoint("web_v2_feed", "/api/v1/xiaohongshu/web_v2/fetch_feed_notes", require_note_id=True),
]

XIAOHONGSHU_MEDIA_URL_PATHS = [
    "video_info_v2.media.stream.h264.backup_urls",
    "video_info_v2.media.stream.h264.master_url",
    "video.media.stream.h264.backup_urls",
    "video.media.stream.h264.master_url",
    "video_info.media.stream.h264.backup_urls",
    "video_info.media.stream.h264.master_url",
    "video.url",
    "video_info.url",
    "videoInfo.url",
    "_widgets_media_url",
]


class XiaohongshuDownloader(Downloader):
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
        initial_note_id, display_url = extract_note_id(source)
        media_info = self.fetch_media_info(source, initial_note_id, display_url, metrics=metrics)
        result = download_first_available(
            settings=self.settings,
            urls=media_info.download_urls,
            source=source,
            job_temp_dir=job_temp_dir,
            options=options,
            media_id=media_info.media_id,
            metrics=metrics,
        )
        result.metadata = {
            "platform": "xiaohongshu",
            "provider": "tikhub",
            "title": media_info.title,
            "author": media_info.author,
            "description": media_info.description,
            "source_url": source.url,
            "display_url": media_info.display_url,
            "media_id": media_info.media_id,
            "media_id_inferred": bool(media_info.extra.get("media_id_inferred")),
            "download_method": "tikhub",
        }
        if media_info.media_id:
            result.source_fingerprint = (
                source.fingerprint
                if source.source_identity
                else stable_fingerprint("xiaohongshu", media_info.media_id)
            )
        return result

    def fetch_media_info(
        self,
        source: ResolvedSource,
        initial_note_id: str | None,
        display_url: str,
        metrics: Any | None = None,
    ) -> TikHubMediaInfo:
        failures: list[str] = []
        share_text = source.original_text or source.url

        for endpoint in XIAOHONGSHU_ENDPOINTS:
            if endpoint.require_note_id and not initial_note_id:
                failures.append(f"{endpoint.name}:missing_note_id")
                continue
            params = build_xiaohongshu_params(endpoint, share_text, initial_note_id)
            try:
                payload = self.client.request(endpoint.endpoint, params)
            except AppError as exc:
                if _should_stop_endpoint_fallback(exc):
                    raise
                failures.append(f"{endpoint.name}:{exc.code}")
                continue

            data = payload.get("data")
            if not isinstance(data, dict):
                failures.append(f"{endpoint.name}:invalid_data")
                continue
            note = unwrap_note_data(data)
            if note is None:
                failures.append(f"{endpoint.name}:unwrap_failed")
                continue
            inject_widgets_media_url(note)
            urls = collect_xiaohongshu_media_urls(note)
            if not urls:
                failures.append(f"{endpoint.name}:no_media_url")
                continue

            note_id = initial_note_id or extract_note_id_from_payload(note)
            media_id_inferred = False
            if not note_id:
                note_id = source.media_id or f"url_{hashlib.sha256(source.url.encode('utf-8')).hexdigest()[:16]}"
                media_id_inferred = True
            title = first_string_at_paths(note, ["title", "note_info.title", "note.title"]) or f"xiaohongshu_{note_id}"
            author = first_string_at_paths(
                note,
                ["user.nickname", "user.nick_name", "user.name", "note_user.nickname"],
            )
            description = first_string_at_paths(note, ["desc", "description", "note_info.desc"]) or ""
            return TikHubMediaInfo(
                platform="xiaohongshu",
                media_id=note_id,
                title=title,
                author=author,
                description=description,
                source_url=source.url,
                display_url=display_url,
                download_urls=urls,
                extra={
                    "endpoint": endpoint.name,
                    "media_id_inferred": media_id_inferred,
                },
            )

        raise AppError(
            "download_failed",
            f"TikHub 小红书解析失败，所有接口均未返回可下载媒体。{_failure_suffix(failures)}",
            "downloading",
        )


def extract_note_id(source: ResolvedSource) -> tuple[str | None, str]:
    url = source.url
    display_url = source.display_url or url
    host = (urlparse(url).hostname or "").lower()
    if host == "xhslink.com":
        try:
            url = resolve_short_url(url, allowed_platforms={"xiaohongshu"})
        except AppError:
            url = source.url

    match = NOTE_ID_RE.search(url)
    if match:
        return match.group(1), display_url

    candidate = url.strip().strip("/")
    if RAW_NOTE_ID_RE.fullmatch(candidate):
        return candidate, display_url
    if source.media_id and RAW_NOTE_ID_RE.fullmatch(source.media_id):
        return source.media_id, display_url
    return None, display_url


def build_xiaohongshu_params(
    endpoint: XiaohongshuEndpoint,
    share_text: str,
    note_id: str | None,
) -> dict[str, str]:
    params = {"share_text": share_text}
    if note_id:
        params["note_id"] = note_id
    if endpoint.extra_params:
        params.update(endpoint.extra_params)
    return params


def unwrap_note_data(data: dict) -> dict | None:
    if _contains_note_media_shape(data):
        return data
    nested = data.get("data")
    if isinstance(nested, dict) and _contains_note_media_shape(nested):
        return nested
    if isinstance(nested, list) and nested:
        first = nested[0]
        if isinstance(first, dict):
            note_list = first.get("note_list")
            if isinstance(note_list, list) and note_list and isinstance(note_list[0], dict):
                return note_list[0]
            if _contains_note_media_shape(first) or first.get("title") or first.get("desc"):
                return first
    note_list = data.get("note_list")
    if isinstance(note_list, list) and note_list and isinstance(note_list[0], dict):
        return note_list[0]
    return None


def inject_widgets_media_url(note: dict) -> None:
    raw = note.get("widgets_context")
    if not isinstance(raw, str) or not raw.strip():
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return
    url = first_string_at_paths(payload, ["note_sound_info.url"])
    if url:
        note["_widgets_media_url"] = url


def extract_note_id_from_payload(note: dict) -> str | None:
    value = first_value_at_paths(
        note,
        ["id", "note_id", "note.id", "note.note_id", "note_info.id", "note_info.note_id"],
    )
    return value if isinstance(value, str) and value.strip() else None


def collect_xiaohongshu_media_urls(note: dict) -> list[str]:
    return dedupe_urls(collect_urls_from_paths(note, XIAOHONGSHU_MEDIA_URL_PATHS))


def _contains_note_media_shape(value: dict) -> bool:
    return any(key in value for key in ("video", "videoInfo", "video_info", "video_info_v2", "widgets_context"))


def _should_stop_endpoint_fallback(exc: AppError) -> bool:
    if exc.code == "platform_provider_not_configured":
        return True
    return "授权失败" in exc.message


def _failure_suffix(failures: list[str]) -> str:
    if not failures:
        return ""
    return " 失败摘要：" + ", ".join(failures[:6])
