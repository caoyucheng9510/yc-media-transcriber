from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.config import Settings
from app.downloaders.base import DownloadResult
from app.downloaders.bilibili_headers import bilibili_media_headers
from app.downloaders.tikhub_client import TikHubClient
from app.downloaders.tikhub_models import TikHubMediaInfo
from app.downloaders.tikhub_utils import (
    collect_urls_from_paths,
    download_first_available,
    first_string_at_paths,
    first_value_at_paths,
    stable_fingerprint,
)
from app.errors import AppError
from app.source_resolver import ResolvedSource
from app.source_resolver.short_url import resolve_short_url


BV_RE = re.compile(r"(BV[0-9A-Za-z]+)")
BILIBILI_DETAIL_ENDPOINTS = [
    "/api/v1/bilibili/web/fetch_one_video",
    "/api/v1/bilibili/web/fetch_one_video_v2",
    "/api/v1/bilibili/web/fetch_one_video_v3",
]
BILIBILI_AUDIO_URL_PATHS = [
    "dash.audio.baseUrl",
    "dash.audio.base_url",
    "durl.url",
]


class BilibiliTikHubFallback:
    def __init__(self, settings: Settings, metrics: Any | None = None):
        self.settings = settings
        self.client = TikHubClient(settings, metrics=metrics)

    def download(
        self,
        source: ResolvedSource,
        job_temp_dir: Path,
        options: dict,
        metrics: Any | None = None,
    ) -> DownloadResult:
        if metrics is not None:
            self.client.metrics = metrics
        media_info = self.fetch_media_info(source)
        result = download_first_available(
            settings=self.settings,
            urls=media_info.download_urls,
            source=source,
            job_temp_dir=job_temp_dir,
            options=options,
            media_id=media_info.media_id,
            request_headers=bilibili_media_headers(),
            metrics=metrics,
        )
        result.metadata = {
            "platform": "bilibili",
            "provider": "tikhub",
            "title": media_info.title,
            "author": media_info.author,
            "description": media_info.description,
            "source_url": source.url,
            "display_url": media_info.display_url,
            "media_id": media_info.media_id,
            "duration": media_info.duration,
            "download_method": "tikhub",
            "page": media_info.extra.get("page"),
            "cid": media_info.extra.get("cid"),
        }
        if media_info.media_id:
            result.source_fingerprint = (
                source.fingerprint
                if source.source_identity
                else stable_fingerprint("bilibili", media_info.media_id)
            )
        return result

    def fetch_media_info(self, source: ResolvedSource) -> TikHubMediaInfo:
        bv_id, display_url = extract_bv_id(source)
        page = extract_page_number(source.url)
        detail = self._fetch_video_detail(bv_id)
        cid = extract_cid_for_page(detail, page)
        if not cid:
            raise AppError("download_failed", "TikHub Bilibili 解析失败，未找到 cid。", "downloading")

        play_payload = self.client.request(
            "/api/v1/bilibili/web/fetch_video_playurl",
            {"bv_id": bv_id, "cid": str(cid)},
        )
        play_data = unwrap_bilibili_data(play_payload)
        urls = collect_urls_from_paths(play_data, BILIBILI_AUDIO_URL_PATHS)
        if not urls:
            raise AppError("download_failed", "TikHub Bilibili 解析失败，未找到音频下载地址。", "downloading")

        title = first_string_at_paths(detail, ["title"]) or f"bilibili_{bv_id}"
        author = first_string_at_paths(detail, ["owner.name", "author", "name"])
        duration = first_value_at_paths(detail, ["duration"])
        return TikHubMediaInfo(
            platform="bilibili",
            media_id=bv_id,
            title=title,
            author=author,
            description="",
            source_url=source.url,
            display_url=display_url,
            download_urls=urls,
            duration=duration if isinstance(duration, (int, float)) else None,
            extra={"cid": cid, "page": page},
        )

    def _fetch_video_detail(self, bv_id: str) -> dict:
        failures: list[str] = []
        for endpoint in BILIBILI_DETAIL_ENDPOINTS:
            try:
                payload = self.client.request(endpoint, {"bv_id": bv_id})
            except AppError as exc:
                if exc.code == "platform_provider_not_configured" or "授权失败" in exc.message:
                    raise
                failures.append(f"{endpoint.rsplit('/', 1)[-1]}:{exc.code}")
                continue
            detail = unwrap_bilibili_data(payload)
            if first_value_at_paths(detail, ["cid", "pages.cid"]):
                return detail
            failures.append(f"{endpoint.rsplit('/', 1)[-1]}:missing_cid")
        raise AppError(
            "download_failed",
            "TikHub Bilibili 解析失败，所有详情接口均未返回 cid。"
            + (" 失败摘要：" + ", ".join(failures[:4]) if failures else ""),
            "downloading",
        )


def extract_bv_id(source: ResolvedSource) -> tuple[str, str]:
    url = source.url
    display_url = source.display_url or url
    if (urlparse(url).hostname or "").lower() == "b23.tv":
        url = resolve_short_url(url, allowed_platforms={"bilibili"})
    if source.media_id and source.media_id.startswith("BV"):
        return source.media_id, display_url
    match = BV_RE.search(url)
    if match:
        return match.group(1), display_url
    raise AppError("download_failed", "无法从 Bilibili 链接中提取 BV 号。", "downloading")


def extract_page_number(url: str) -> int:
    raw_page = parse_qs(urlparse(url).query).get("p", [None])[0]
    try:
        page = int(raw_page) if raw_page else 1
    except (TypeError, ValueError):
        return 1
    return page if page > 0 else 1


def extract_cid_for_page(detail: dict, page: int) -> Any:
    pages = detail.get("pages")
    if isinstance(pages, list) and pages:
        index = page - 1
        if index < 0 or index >= len(pages):
            return None
        candidate = pages[index]
        if isinstance(candidate, dict):
            cid = candidate.get("cid")
            if cid:
                return cid
        return None
    return first_value_at_paths(detail, ["cid", "pages.cid"])


def unwrap_bilibili_data(payload: dict) -> dict:
    data = payload.get("data")
    if isinstance(data, dict):
        nested = data.get("data")
        if isinstance(nested, dict):
            return nested
        return data
    return payload
