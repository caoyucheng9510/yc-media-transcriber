from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from app.source_resolver.resolver import URL_RE


@dataclass(frozen=True)
class CreatorProfileInput:
    platform: str
    url: str


def detect_creator_profile_input(value: str) -> CreatorProfileInput | None:
    match = URL_RE.search(value)
    if not match:
        return None
    raw_url = match.group(0).rstrip(").,，。")
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")

    if _is_xiaohongshu_profile(host, path):
        return CreatorProfileInput(platform="xiaohongshu", url=raw_url)
    if _is_douyin_profile(host, path):
        return CreatorProfileInput(platform="douyin", url=raw_url)
    return None


def _is_xiaohongshu_profile(host: str, path: str) -> bool:
    if host == "xhslink.com" and path.startswith("/m/"):
        return True
    if not host.endswith("xiaohongshu.com"):
        return False
    return path.startswith("/user/profile/")


def _is_douyin_profile(host: str, path: str) -> bool:
    if not (host.endswith("douyin.com") or host.endswith("iesdouyin.com")):
        return False
    return path.startswith("/user/") or path.startswith("/share/user/")
