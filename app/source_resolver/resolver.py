from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.errors import AppError
from app.media.ffmpeg import MEDIA_EXTENSIONS
from app.source_resolver.short_url import resolve_short_url
from app.source_resolver.ssrf import assert_safe_url


URL_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
BV_RE = re.compile(r"(BV[0-9A-Za-z]+)")
DOUYIN_ID_RE = re.compile(r"/(?:video|note)/(\d+)")
XHS_ID_RE = re.compile(r"/(?:explore|discovery/item|items)/([0-9A-Za-z]+)")
YOUTUBE_PATH_ID_RE = re.compile(r"/(?:shorts|live|embed)/([0-9A-Za-z_-]+)")
SHORT_LINK_HOSTS_REQUIRING_RESOLUTION = {"b23.tv", "v.douyin.com", "xhslink.com"}
STABLE_IDENTITY_PLATFORMS = {"youtube", "bilibili", "xiaoyuzhou", "douyin", "xiaohongshu"}


@dataclass(frozen=True)
class ResolvedSource:
    kind: str
    platform: str
    url: str
    media_id: str | None = None
    normalized_url: str | None = None
    original_text: str | None = None
    input_url: str | None = None
    display_url: str | None = None
    source_identity: str | None = None

    @property
    def fingerprint(self) -> str:
        raw = self.source_identity or f"{self.platform}:{self.media_id or self.normalized_url or self.url}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SourceResolver:
    def __init__(
        self,
        *,
        allow_private_urls: bool = False,
        private_url_allowlist: tuple[str, ...] = (),
    ):
        self.allow_private_urls = allow_private_urls
        self.private_url_allowlist = private_url_allowlist

    def resolve(self, source_type: str, value: str) -> ResolvedSource:
        input_url = self.extract_url(value)
        if not input_url:
            raise AppError("invalid_source", "未识别到可处理的链接。", "downloading")
        platform = self.detect_platform(input_url)
        if platform == "direct_media":
            assert_safe_url(
                input_url,
                allow_private=self.allow_private_urls,
                host_allowlist=self.private_url_allowlist,
            )
        elif platform in {"douyin", "xiaohongshu", "bilibili", "youtube", "xiaoyuzhou"}:
            assert_safe_url(input_url, allow_private=False, resolve_dns=False)
        else:
            raise AppError("unsupported_platform", "该平台链接第一版暂不支持。", "downloading")

        resolved_url = self.resolve_platform_url(platform, input_url)
        if resolved_url != input_url:
            assert_safe_url(resolved_url, allow_private=False, resolve_dns=False)
            platform = self.detect_platform(resolved_url)

        media_id = self.extract_media_id(platform, resolved_url)
        source_identity = self.source_identity(platform, resolved_url, media_id)
        return ResolvedSource(
            kind="url",
            platform=platform,
            url=resolved_url,
            media_id=media_id,
            normalized_url=source_identity or self.normalize_url(platform, resolved_url),
            original_text=value if source_type == "text" else None,
            input_url=input_url,
            display_url=input_url,
            source_identity=source_identity,
        )

    def extract_url(self, value: str) -> str | None:
        match = URL_RE.search(value)
        if not match:
            return None
        return match.group(0).rstrip(").,，。")

    def detect_platform(self, url: str) -> str:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        suffix = Path(parsed.path).suffix.lower()
        if host in {"youtu.be"} or host.endswith("youtube.com"):
            return "youtube"
        if host == "b23.tv" or host.endswith("bilibili.com"):
            return "bilibili"
        if host.endswith("xiaoyuzhoufm.com"):
            return "xiaoyuzhou"
        if host.endswith("douyin.com"):
            return "douyin"
        if host.endswith("xiaohongshu.com") or host.endswith("xhslink.com"):
            return "xiaohongshu"
        if suffix in MEDIA_EXTENSIONS:
            return "direct_media"
        return "unknown"

    def extract_media_id(self, platform: str, url: str) -> str | None:
        parsed = urlparse(url)
        if platform == "youtube":
            if parsed.hostname == "youtu.be":
                return parsed.path.strip("/") or None
            query_id = parse_qs(parsed.query).get("v", [None])[0]
            if query_id:
                return query_id
            match = YOUTUBE_PATH_ID_RE.search(parsed.path)
            return match.group(1) if match else None
        if platform == "bilibili":
            match = BV_RE.search(url)
            return match.group(1) if match else None
        if platform == "xiaoyuzhou":
            return parsed.path.rstrip("/").split("/")[-1] or None
        if platform == "douyin":
            match = DOUYIN_ID_RE.search(parsed.path)
            if match:
                return match.group(1)
            return parse_qs(parsed.query).get("aweme_id", [None])[0]
        if platform == "xiaohongshu":
            match = XHS_ID_RE.search(parsed.path)
            if match:
                return match.group(1)
            parts = [part for part in parsed.path.split("/") if part]
            if parts and re.fullmatch(r"[0-9a-fA-F]{24}", parts[-1]):
                return parts[-1]
            return None
        return None

    def normalize_url(self, platform: str, url: str) -> str:
        media_id = self.extract_media_id(platform, url)
        if media_id:
            return f"{platform}:{media_id}"
        return url

    def resolve_platform_url(self, platform: str, url: str) -> str:
        host = (urlparse(url).hostname or "").lower()
        if host not in SHORT_LINK_HOSTS_REQUIRING_RESOLUTION:
            return url
        try:
            return resolve_short_url(url, allowed_platforms={platform})
        except AppError as exc:
            if exc.code != "download_failed":
                raise
            # Keep the original URL so provider-specific fallback logic can still try.
            return url

    def source_identity(self, platform: str, url: str, media_id: str | None) -> str | None:
        if platform not in STABLE_IDENTITY_PLATFORMS or not media_id:
            return None
        if platform == "bilibili":
            return f"bilibili:{media_id}:p{self.extract_bilibili_page(url)}"
        return f"{platform}:{media_id}"

    def extract_bilibili_page(self, url: str) -> int:
        raw_page = parse_qs(urlparse(url).query).get("p", [None])[0]
        try:
            page = int(raw_page) if raw_page else 1
        except (TypeError, ValueError):
            return 1
        return page if page > 0 else 1
