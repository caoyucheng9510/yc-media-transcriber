from __future__ import annotations

import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from app.config import Settings
from app.downloaders.tikhub_client import TikHubClient
from app.downloaders.tikhub_utils import first_string, first_string_at_paths, first_value_at_paths, values_at_path
from app.errors import AppError
from app.jobs.submission import JobSubmissionService
from app.schemas import (
    CreateJobResponse,
    CreatorInfo,
    CreatorPagination,
    CreatorPreviewRequest,
    CreatorPreviewResponse,
    CreatorSubmitCreated,
    CreatorSubmitRequest,
    CreatorSubmitResponse,
    CreatorSubmitSkipped,
    CreatorWorkItem,
)
from app.source_resolver.resolver import URL_RE, SourceResolver
from app.source_resolver.ssrf import assert_safe_url


XIAOHONGSHU_USER_POSTS = "/api/v1/xiaohongshu/app_v2/get_user_posted_notes"
XIAOHONGSHU_USER_INFO = "/api/v1/xiaohongshu/app_v2/get_user_info"
DOUYIN_GET_SEC_USER_ID = "/api/v1/douyin/web/get_sec_user_id"
DOUYIN_APP_USER_POSTS = "/api/v1/douyin/app/v3/fetch_user_post_videos"
DOUYIN_WEB_USER_POSTS = "/api/v1/douyin/web/fetch_user_post_videos"
DOUYIN_APP_USER_PROFILE = "/api/v1/douyin/app/v3/handler_user_profile"


class CreatorPreviewCache:
    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = max(60, ttl_seconds)
        self._lock = threading.RLock()
        self._items: dict[str, tuple[float, CreatorPreviewResponse]] = {}
        self._keys: dict[str, tuple[float, str]] = {}

    def put(self, preview: CreatorPreviewResponse, *, cache_key: str | None = None) -> None:
        expires_at = time.monotonic() + self.ttl_seconds
        with self._lock:
            self._cleanup_locked()
            self._items[preview.preview_id] = (expires_at, preview)
            if cache_key:
                self._keys[cache_key] = (expires_at, preview.preview_id)

    def get(self, preview_id: str) -> CreatorPreviewResponse | None:
        with self._lock:
            self._cleanup_locked()
            item = self._items.get(preview_id)
            if item is None:
                return None
            return item[1]

    def get_by_key(self, cache_key: str) -> CreatorPreviewResponse | None:
        with self._lock:
            self._cleanup_locked()
            item = self._keys.get(cache_key)
            if item is None:
                return None
            _, preview_id = item
            preview = self._items.get(preview_id)
            if preview is None:
                self._keys.pop(cache_key, None)
                return None
            return preview[1]

    def _cleanup_locked(self) -> None:
        now = time.monotonic()
        expired = [key for key, (expires_at, _) in self._items.items() if expires_at <= now]
        for key in expired:
            self._items.pop(key, None)
        expired_keys = [
            key
            for key, (expires_at, preview_id) in self._keys.items()
            if expires_at <= now or preview_id not in self._items
        ]
        for key in expired_keys:
            self._keys.pop(key, None)


class CreatorService:
    def __init__(self, *, settings: Settings, cache: CreatorPreviewCache):
        self.settings = settings
        self.cache = cache
        self.client = TikHubClient(settings)
        self.resolver = SourceResolver()

    def preview(self, request: CreatorPreviewRequest) -> CreatorPreviewResponse:
        platform = self._resolve_platform(request.platform, request.input)
        cache_key = _preview_cache_key(platform, request, self.settings.creator_preview_max_items)
        cached = self.cache.get_by_key(cache_key)
        if cached is not None:
            return cached
        if platform == "xiaohongshu":
            preview = self._preview_xiaohongshu(request)
        elif platform == "douyin":
            preview = self._preview_douyin(request)
        else:
            raise AppError("unsupported_platform", "只支持抖音和小红书创作者主页导入。", "api")
        self.cache.put(preview, cache_key=cache_key)
        return preview

    def submit(
        self,
        request: CreatorSubmitRequest,
        submission: JobSubmissionService,
    ) -> CreatorSubmitResponse:
        preview = self.cache.get(request.preview_id)
        if preview is None:
            raise AppError("creator_preview_not_found", "预览结果已过期，请重新拉取。", "api")

        items_by_id = {item.id: item for item in preview.items}
        created: list[CreatorSubmitCreated] = []
        skipped: list[CreatorSubmitSkipped] = []
        submission_id = f"creator_submit_{uuid.uuid4().hex[:16]}"
        seen: set[str] = set()

        for item_id in request.selected_item_ids:
            if item_id in seen:
                skipped.append(CreatorSubmitSkipped(item_id=item_id, reason="duplicate_selection"))
                continue
            seen.add(item_id)
            item = items_by_id.get(item_id)
            if item is None:
                skipped.append(CreatorSubmitSkipped(item_id=item_id, reason="item_not_found"))
                continue
            if not item.transcribable:
                skipped.append(CreatorSubmitSkipped(item_id=item_id, reason="not_transcribable"))
                continue

            metadata = {
                "platform": item.platform,
                "title": item.title,
                "media_id": item.work_id,
                "creator_import": {
                    "preview_id": preview.preview_id,
                    "submission_id": submission_id,
                    "creator_id": preview.creator.id,
                    "creator_name": preview.creator.name,
                    "work_id": item.work_id,
                    "work_type": item.type,
                    "source_url": item.source_url,
                },
            }
            response = submission.create_url_job(
                source_type="url",
                source_value=item.source_url,
                options=request.options,
                metadata=metadata,
                title=item.title,
            )
            created.append(
                CreatorSubmitCreated(
                    item_id=item.id,
                    job_id=response.job_id,
                    source_url=item.source_url,
                )
            )

        if not created and not skipped:
            raise AppError("creator_selection_empty", "没有可提交的作品。", "api")
        return CreatorSubmitResponse(submission_id=submission_id, created=created, skipped=skipped)

    def _preview_xiaohongshu(self, request: CreatorPreviewRequest) -> CreatorPreviewResponse:
        share_link = _extract_url(request.input)
        _assert_platform_link(share_link, "xiaohongshu")
        max_items = min(request.max_items, self.settings.creator_preview_max_items)
        scan_limit = request.page_size * request.max_pages
        cursor = request.cursor or ""
        pages = 0
        has_more = False
        next_cursor: str | None = cursor or None
        items: list[CreatorWorkItem] = []
        seen: set[str] = set()
        scanned_count = 0
        filtered_count = 0
        stop_reason: str | None = None
        creator = CreatorInfo(profile_url=share_link)

        try:
            profile = self.client.request(XIAOHONGSHU_USER_INFO, {"share_text": share_link})
            creator = _xiaohongshu_creator_info(profile, fallback_url=share_link)
        except AppError as exc:
            if exc.code == "platform_provider_not_configured":
                raise

        while pages < request.max_pages and len(items) < max_items and scanned_count < scan_limit:
            payload = self.client.request(
                XIAOHONGSHU_USER_POSTS,
                {"share_text": share_link, "cursor": cursor},
            )
            pages += 1
            note_payload = _xiaohongshu_notes_payload(payload)
            notes = note_payload["notes"]
            has_more = bool(note_payload["has_more"])
            next_cursor = note_payload["next_cursor"]

            for note in notes:
                if not isinstance(note, dict):
                    continue
                if scanned_count >= scan_limit:
                    stop_reason = "scan_limit"
                    break
                scanned_count += 1
                item = _xiaohongshu_item(note)
                if item is None or item.id in seen:
                    continue
                seen.add(item.id)
                if not item.transcribable:
                    filtered_count += 1
                    continue
                items.append(item)
                if len(items) >= max_items:
                    stop_reason = "target_reached"
                    break

            if stop_reason == "target_reached" or stop_reason == "scan_limit":
                break
            if not has_more or not next_cursor:
                stop_reason = "no_more"
                break
            if next_cursor == cursor:
                stop_reason = "cursor_stalled"
                break
            cursor = next_cursor

        if stop_reason is None:
            if len(items) >= max_items:
                stop_reason = "target_reached"
            elif not has_more or not next_cursor:
                stop_reason = "no_more"
            elif pages >= request.max_pages:
                stop_reason = "page_limit"
            elif scanned_count >= scan_limit:
                stop_reason = "scan_limit"

        if not creator.id or not creator.name or not creator.avatar_url:
            creator = _merge_creator_info(creator, _creator_from_items(items))

        preview = CreatorPreviewResponse(
            preview_id=f"creator_preview_{uuid.uuid4().hex[:16]}",
            platform="xiaohongshu",
            creator=creator,
            items=items,
            pagination=CreatorPagination(
                has_more=has_more,
                next_cursor=next_cursor,
                fetched_pages=pages,
                fetched_count=len(items),
                scanned_count=scanned_count,
                filtered_count=filtered_count,
                stop_reason=stop_reason,
            ),
        )
        if not preview.items:
            raise AppError("creator_items_empty", "未找到可转录的视频作品。", "api")
        return preview

    def _preview_douyin(self, request: CreatorPreviewRequest) -> CreatorPreviewResponse:
        profile_url = _resolve_douyin_profile_url(_extract_url(request.input), self.resolver)
        max_items = min(request.max_items, self.settings.creator_preview_max_items)
        page_size = min(request.page_size, 20)
        scan_limit = page_size * request.max_pages
        sec_user_id = self._douyin_sec_user_id(profile_url)
        creator = CreatorInfo(id=sec_user_id, profile_url=profile_url)
        try:
            profile = self.client.request(DOUYIN_APP_USER_PROFILE, {"sec_user_id": sec_user_id})
            creator = _douyin_creator_info(profile, fallback_id=sec_user_id, fallback_url=profile_url)
        except AppError as exc:
            if exc.code == "platform_provider_not_configured":
                raise

        cursor: int | str = request.cursor or 0
        pages = 0
        has_more = False
        next_cursor: str | None = str(cursor)
        items: list[CreatorWorkItem] = []
        seen: set[str] = set()
        sort_type = 1 if request.sort == "hot" else 0
        scanned_count = 0
        filtered_count = 0
        stop_reason: str | None = None

        while pages < request.max_pages and len(items) < max_items and scanned_count < scan_limit:
            try:
                payload = self.client.request(
                    DOUYIN_APP_USER_POSTS,
                    {
                        "sec_user_id": sec_user_id,
                        "max_cursor": int(cursor),
                        "count": page_size,
                        "sort_type": sort_type,
                    },
                )
                post_payload = _douyin_posts_payload(payload)
            except AppError as exc:
                if pages > 0 or exc.code == "platform_provider_not_configured":
                    raise
                payload = self.client.request(
                    DOUYIN_WEB_USER_POSTS,
                    {
                        "sec_user_id": sec_user_id,
                        "max_cursor": str(cursor),
                        "count": page_size,
                        "filter_type": "3" if request.sort == "hot" else "0",
                    },
                )
                post_payload = _douyin_posts_payload(payload)

            pages += 1
            has_more = bool(post_payload["has_more"])
            next_cursor = post_payload["next_cursor"]
            for aweme in post_payload["items"]:
                if not isinstance(aweme, dict):
                    continue
                if scanned_count >= scan_limit:
                    stop_reason = "scan_limit"
                    break
                scanned_count += 1
                item = _douyin_item(aweme)
                if item is None or item.id in seen:
                    continue
                seen.add(item.id)
                if not item.transcribable:
                    filtered_count += 1
                    continue
                items.append(item)
                if len(items) >= max_items:
                    stop_reason = "target_reached"
                    break

            if stop_reason == "target_reached" or stop_reason == "scan_limit":
                break
            if not has_more or not next_cursor:
                stop_reason = "no_more"
                break
            if next_cursor == str(cursor):
                stop_reason = "cursor_stalled"
                break
            cursor = next_cursor

        if stop_reason is None:
            if len(items) >= max_items:
                stop_reason = "target_reached"
            elif not has_more or not next_cursor:
                stop_reason = "no_more"
            elif pages >= request.max_pages:
                stop_reason = "page_limit"
            elif scanned_count >= scan_limit:
                stop_reason = "scan_limit"

        preview = CreatorPreviewResponse(
            preview_id=f"creator_preview_{uuid.uuid4().hex[:16]}",
            platform="douyin",
            creator=creator,
            items=items,
            pagination=CreatorPagination(
                has_more=has_more,
                next_cursor=next_cursor,
                fetched_pages=pages,
                fetched_count=len(items),
                scanned_count=scanned_count,
                filtered_count=filtered_count,
                stop_reason=stop_reason,
            ),
        )
        if not preview.items:
            raise AppError("creator_items_empty", "未找到可转录的视频作品。", "api")
        return preview

    def _douyin_sec_user_id(self, profile_url: str) -> str:
        path_tail = urlparse(profile_url).path.rstrip("/").split("/")[-1]
        if path_tail.startswith("MS4w"):
            return path_tail
        payload = self.client.request(DOUYIN_GET_SEC_USER_ID, {"url": profile_url})
        value = _first_recursive(payload.get("data"), {"sec_user_id", "sec_uid"})
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise AppError("creator_identity_not_found", "无法从抖音主页链接提取 sec_user_id。", "api")

    def _resolve_platform(self, requested: str, raw_input: str) -> str:
        if requested != "auto":
            return requested
        url = _extract_url(raw_input)
        platform = self.resolver.detect_platform(url)
        if platform in {"douyin", "xiaohongshu"}:
            return platform
        raise AppError("unsupported_platform", "只支持抖音和小红书创作者主页导入。", "api")


def _preview_cache_key(platform: str, request: CreatorPreviewRequest, configured_max_items: int) -> str:
    url = _extract_url(request.input)
    max_items = min(request.max_items, configured_max_items)
    page_size = min(request.page_size, 20)
    cursor = request.cursor or ""
    return "|".join(
        [
            platform,
            url,
            str(max_items),
            str(request.max_pages),
            str(page_size),
            request.sort,
            cursor,
        ]
    )


def _extract_url(value: str) -> str:
    match = URL_RE.search(value)
    if not match:
        raise AppError("invalid_source", "未识别到创作者主页链接。", "api")
    return match.group(0).rstrip(").,，。>")


def _resolve_douyin_profile_url(url: str, resolver: SourceResolver) -> str:
    _assert_platform_link(url, "douyin")
    resolved_url = resolver.resolve_platform_url("douyin", url)
    _assert_platform_link(resolved_url, "douyin")
    return resolved_url


def _assert_platform_link(url: str, platform: str) -> None:
    assert_safe_url(url, allow_private=False, resolve_dns=False)
    host = (urlparse(url).hostname or "").lower()
    if platform == "xiaohongshu" and (host.endswith("xiaohongshu.com") or host.endswith("xhslink.com")):
        return
    if platform == "douyin" and host.endswith("douyin.com"):
        return
    raise AppError("unsupported_platform", "主页链接平台与请求平台不一致。", "api")


def _xiaohongshu_notes_payload(payload: dict[str, Any]) -> dict[str, Any]:
    notes = _first_list_at_paths(
        payload,
        ["data.data.notes", "data.notes", "data.data.items", "data.items", "notes", "items"],
    )
    data = first_value_at_paths(payload, ["data.data", "data"])
    has_more = _bool_value(first_value_at_paths(data, ["has_more", "hasMore"])) if isinstance(data, dict) else False
    next_cursor = first_string_at_paths(data, ["cursor", "next_cursor"]) if isinstance(data, dict) else None
    if not next_cursor and notes:
        last = notes[-1]
        if isinstance(last, dict):
            next_cursor = first_string(last.get("cursor"), last.get("note_id"), last.get("id"))
    return {"notes": notes, "has_more": has_more, "next_cursor": next_cursor}


def _xiaohongshu_item(note: dict[str, Any]) -> CreatorWorkItem | None:
    work_id = first_string(note.get("id"), note.get("note_id"))
    if not work_id:
        return None
    raw_type = first_string(note.get("type"), note.get("note_type")) or "unknown"
    item_type = raw_type.lower()
    transcribable = item_type == "video"
    title = first_string(note.get("display_title"), note.get("title"), note.get("desc")) or f"xiaohongshu_{work_id}"
    return CreatorWorkItem(
        id=f"xiaohongshu:{work_id}",
        platform="xiaohongshu",
        work_id=work_id,
        type=item_type,
        transcribable=transcribable,
        title=title,
        cover_url=_first_media_url(note.get("cover")) or _first_media_url(note.get("images_list")),
        published_at=_timestamp_to_iso(note.get("create_time")),
        duration_seconds=_duration_seconds(note.get("duration")),
        stats={
            "like": _int_value(note.get("likes") or note.get("liked_count") or note.get("nice_count")),
            "comment": _int_value(note.get("comments_count") or note.get("comments")),
            "collect": _int_value(note.get("collected_count") or note.get("collect_count")),
            "share": _int_value(note.get("share_count") or note.get("shares")),
        },
        source_url=f"https://www.xiaohongshu.com/explore/{work_id}",
    )


def _xiaohongshu_creator_info(payload: dict[str, Any], *, fallback_url: str) -> CreatorInfo:
    data = payload.get("data")
    user_id = _first_recursive(data, {"user_id", "userid", "userId"})
    nickname = _first_recursive(data, {"nickname", "nick_name", "name"})
    avatar = _first_recursive(data, {"avatar", "avatar_url", "image", "url", "url_default"})
    desc = _first_recursive(data, {"desc", "description", "desc_info"})
    return CreatorInfo(
        id=user_id if isinstance(user_id, str) else None,
        name=nickname if isinstance(nickname, str) else None,
        avatar_url=avatar if isinstance(avatar, str) and avatar.startswith(("http://", "https://")) else None,
        profile_url=fallback_url,
        description=desc if isinstance(desc, str) else None,
    )


def _creator_from_items(items: list[CreatorWorkItem]) -> CreatorInfo:
    return CreatorInfo()


def _merge_creator_info(primary: CreatorInfo, fallback: CreatorInfo) -> CreatorInfo:
    return CreatorInfo(
        id=primary.id or fallback.id,
        name=primary.name or fallback.name,
        avatar_url=primary.avatar_url or fallback.avatar_url,
        profile_url=primary.profile_url or fallback.profile_url,
        description=primary.description or fallback.description,
    )


def _douyin_posts_payload(payload: dict[str, Any]) -> dict[str, Any]:
    items = _first_list_at_paths(
        payload,
        ["data.aweme_list", "data.data.aweme_list", "data.data", "aweme_list", "data.list", "list"],
    )
    data = first_value_at_paths(payload, ["data.data", "data"])
    has_more = _bool_value(first_value_at_paths(data, ["has_more", "hasMore"])) if isinstance(data, dict) else False
    next_cursor = _string_value(first_value_at_paths(data, ["max_cursor", "next_cursor", "cursor"]))
    return {"items": items, "has_more": has_more, "next_cursor": next_cursor}


def _douyin_item(aweme: dict[str, Any]) -> CreatorWorkItem | None:
    work_id = first_string(aweme.get("aweme_id"), aweme.get("id"))
    if not work_id:
        return None
    duration_ms = _int_value(first_value_at_paths(aweme, ["video.duration"]))
    return CreatorWorkItem(
        id=f"douyin:{work_id}",
        platform="douyin",
        work_id=work_id,
        type="video",
        transcribable=True,
        title=first_string(aweme.get("desc"), aweme.get("item_title")) or f"douyin_{work_id}",
        cover_url=first_string_at_paths(aweme, ["video.cover.url_list", "video.origin_cover.url_list"]),
        published_at=_timestamp_to_iso(aweme.get("create_time")),
        duration_seconds=(duration_ms / 1000) if duration_ms else None,
        stats={
            "like": _int_value(first_value_at_paths(aweme, ["statistics.digg_count"])),
            "comment": _int_value(first_value_at_paths(aweme, ["statistics.comment_count"])),
            "collect": _int_value(first_value_at_paths(aweme, ["statistics.collect_count"])),
            "share": _int_value(first_value_at_paths(aweme, ["statistics.share_count"])),
        },
        source_url=f"https://www.douyin.com/video/{work_id}",
    )


def _douyin_creator_info(payload: dict[str, Any], *, fallback_id: str, fallback_url: str) -> CreatorInfo:
    data = payload.get("data")
    return CreatorInfo(
        id=_string_value(_first_recursive(data, {"sec_user_id", "sec_uid"})) or fallback_id,
        name=_string_value(_first_recursive(data, {"nickname", "unique_id", "short_id"})),
        avatar_url=_string_value(_first_recursive(data, {"avatar_url", "url_list"})),
        profile_url=fallback_url,
        description=_string_value(_first_recursive(data, {"signature", "description"})),
    )


def _first_list_at_paths(payload: Any, paths: list[str]) -> list[Any]:
    for path in paths:
        value = _value_at_path(payload, path)
        if isinstance(value, list):
            return value
    return []


def _value_at_path(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if 0 <= index < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def _first_recursive(value: Any, names: set[str]) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in names and item not in (None, ""):
                if isinstance(item, list):
                    media_url = _first_media_url(item)
                    if media_url:
                        return media_url
                else:
                    return item
        for item in value.values():
            found = _first_recursive(item, names)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for item in value:
            found = _first_recursive(item, names)
            if found not in (None, ""):
                return found
    return None


def _first_media_url(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    if isinstance(value, dict):
        for key in ("url", "url_default", "url_pre", "url_list", "info_list"):
            result = _first_media_url(value.get(key))
            if result:
                return result
        for item in value.values():
            result = _first_media_url(item)
            if result:
                return result
    if isinstance(value, list):
        for item in value:
            result = _first_media_url(item)
            if result:
                return result
    return None


def _timestamp_to_iso(value: Any) -> str | None:
    seconds = _int_value(value)
    if seconds is None or seconds <= 0:
        return None
    if seconds > 10_000_000_000:
        seconds = int(seconds / 1000)
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def _duration_seconds(value: Any) -> float | None:
    number = _float_value(value)
    if number is None or number < 0:
        return None
    if number > 1000:
        return number / 1000
    return number


def _int_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        value = re.sub(r"[,，]", "", value)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float_value(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _string_value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, list):
        return _first_media_url(value)
    return str(value).strip()
