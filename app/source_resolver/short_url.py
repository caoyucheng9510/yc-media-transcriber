from __future__ import annotations

from urllib.parse import urlparse

import httpx

from app.errors import AppError
from app.source_resolver.ssrf import assert_safe_url


SHORT_HOSTS = {"v.douyin.com", "xhslink.com", "b23.tv", "youtu.be"}


def resolve_short_url(
    url: str,
    *,
    allowed_platforms: set[str],
    timeout: float = 8.0,
) -> str:
    assert_safe_url(url, allow_private=False, resolve_dns=False)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.head(url)
            if _needs_get_fallback(response):
                response = client.get(url)
    except httpx.HTTPError as exc:
        raise AppError("download_failed", "短链解析失败。", "downloading") from exc

    final_url = str(response.url)
    assert_safe_url(final_url, allow_private=False, resolve_dns=False)
    platform = detect_supported_platform(final_url)
    if platform not in allowed_platforms:
        raise AppError("invalid_source", "短链跳转到了不支持的平台。", "downloading")
    return final_url


def is_short_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in SHORT_HOSTS


def detect_supported_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host == "youtu.be" or host.endswith("youtube.com"):
        return "youtube"
    if host == "b23.tv" or host.endswith("bilibili.com"):
        return "bilibili"
    if host.endswith("douyin.com"):
        return "douyin"
    if host.endswith("xiaohongshu.com") or host.endswith("xhslink.com"):
        return "xiaohongshu"
    return "unknown"


def _needs_get_fallback(response: httpx.Response) -> bool:
    if response.history:
        return False
    if response.status_code == 404:
        return True
    return response.status_code < 200 or response.status_code >= 300
