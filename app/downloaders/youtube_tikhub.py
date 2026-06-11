from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.config import Settings
from app.downloaders.base import DownloadResult
from app.downloaders.tikhub_client import TikHubClient
from app.downloaders.tikhub_models import TikHubMediaInfo
from app.downloaders.tikhub_utils import (
    collect_urls_from_paths,
    dedupe_urls,
    download_first_available,
    first_string_at_paths,
    first_value_at_paths,
    stable_fingerprint,
    values_at_path,
)
from app.downloaders.vtt import parse_vtt
from app.errors import AppError
from app.schemas import Segment
from app.source_resolver import ResolvedSource


YOUTUBE_PATH_ID_RE = re.compile(r"/(?:shorts|live|embed)/([0-9A-Za-z_-]+)")
LANGUAGE_ORDER = ["zh-CN", "zh-Hans", "zh", "zh-TW", "zh-Hant", "en", "en-US"]

YOUTUBE_AUDIO_URL_PATHS = [
    "audios.items.url",
    "audios.items.audio_url",
    "audios.url",
    "audio.url",
    "audio_url",
]

YOUTUBE_STREAM_AUDIO_URL_PATHS = [
    "audios.items.url",
    "audios.url",
    "audioStreams.url",
    "streams.audio.url",
    "adaptiveFormats.url",
]


class YouTubeTikHubFallback:
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
            metrics=metrics,
        )
        result.metadata = {
            "platform": "youtube",
            "provider": "tikhub",
            "title": media_info.title,
            "author": media_info.author,
            "description": media_info.description,
            "duration": media_info.duration,
            "source_url": source.url,
            "display_url": source.display_url or source.url,
            "media_id": media_info.media_id,
            "download_method": "tikhub",
        }
        if media_info.media_id:
            result.source_fingerprint = (
                source.fingerprint
                if source.source_identity
                else stable_fingerprint("youtube", media_info.media_id)
            )
        return result

    def fetch_media_info(self, source: ResolvedSource) -> TikHubMediaInfo:
        video_id = extract_youtube_video_id(source)
        payload = self.client.request(
            "/api/v1/youtube/web/get_video_info",
            {
                "video_id": video_id,
                "videos": "false",
                "audios": "true",
                "subtitles": "true",
                "related": "false",
                "lang": "zh-CN",
            },
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        urls = collect_urls_from_paths(data, YOUTUBE_AUDIO_URL_PATHS)
        if not urls:
            urls = self._fetch_stream_urls(video_id)
        if not urls:
            raise AppError("download_failed", "TikHub YouTube 解析失败，未找到音频下载地址。", "downloading")

        title = first_string_at_paths(data, ["title", "videoDetails.title"]) or f"youtube_{video_id}"
        author = first_string_at_paths(data, ["channel.name", "author", "ownerChannelName"])
        description = first_string_at_paths(data, ["description", "videoDetails.shortDescription"]) or ""
        duration = first_value_at_paths(data, ["duration", "videoDetails.lengthSeconds"])
        return TikHubMediaInfo(
            platform="youtube",
            media_id=video_id,
            title=title,
            author=author,
            description=description,
            source_url=source.url,
            display_url=source.url,
            download_urls=urls,
            duration=duration if isinstance(duration, (int, float)) else None,
        )

    def fetch_subtitle_segments(self, source: ResolvedSource) -> list[Segment]:
        if not has_tikhub_key(self.settings):
            return []
        video_id = extract_youtube_video_id(source)
        segments = self._fetch_captions_v2(video_id)
        if segments:
            return segments
        return self._fetch_subtitles_from_video_info(video_id)

    def _fetch_stream_urls(self, video_id: str) -> list[str]:
        payload = self.client.request("/api/v1/youtube/web_v2/get_video_streams", {"video_id": video_id})
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        return dedupe_urls(collect_urls_from_paths(data, YOUTUBE_STREAM_AUDIO_URL_PATHS))

    def _fetch_captions_v2(self, video_id: str) -> list[Segment]:
        try:
            payload = self.client.request(
                "/api/v1/youtube/web_v2/get_video_captions",
                {"video_id": video_id, "format": "srt"},
            )
        except AppError:
            return []
        return parse_caption_payload(payload)

    def _fetch_subtitles_from_video_info(self, video_id: str) -> list[Segment]:
        try:
            payload = self.client.request(
                "/api/v1/youtube/web/get_video_info",
                {
                    "video_id": video_id,
                    "videos": "false",
                    "audios": "false",
                    "subtitles": "true",
                    "related": "false",
                },
            )
        except AppError:
            return []
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        entry = select_subtitle_entry(data)
        subtitle_url = entry.get("url") if entry else None
        if not subtitle_url:
            return []
        try:
            subtitle_payload = self.client.request(
                "/api/v1/youtube/web/get_video_subtitles",
                {"subtitle_url": subtitle_url, "format": "srt", "fix_overlap": "true"},
            )
        except AppError:
            return []
        return parse_caption_payload(subtitle_payload)


def has_tikhub_key(settings: Settings) -> bool:
    return bool(settings.tikhub_api_key or settings.tikhub_alternate_api_key)


def extract_youtube_video_id(source: ResolvedSource) -> str:
    if source.media_id:
        return source.media_id
    parsed = urlparse(source.url)
    if parsed.hostname == "youtu.be":
        video_id = parsed.path.strip("/")
        if video_id:
            return video_id
    query_id = parse_qs(parsed.query).get("v", [None])[0]
    if query_id:
        return query_id
    match = YOUTUBE_PATH_ID_RE.search(parsed.path)
    if match:
        return match.group(1)
    raise AppError("download_failed", "无法从 YouTube 链接中提取视频 ID。", "downloading")


def select_subtitle_entry(data: dict) -> dict | None:
    entries: list[object] = []
    for path in ("subtitles.items", "captions.items", "subtitles", "captions"):
        entries.extend(values_at_path(data, path))
    normalized = [entry for entry in entries if isinstance(entry, dict)]
    for language in LANGUAGE_ORDER:
        for entry in normalized:
            if _entry_language(entry) == language:
                return entry
    return normalized[0] if normalized else None


def parse_caption_payload(payload: object) -> list[Segment]:
    text = caption_text_from_payload(payload)
    if not text:
        return []
    if "WEBVTT" in text:
        return parse_vtt(text)
    if "<text" in text or "<transcript" in text:
        return parse_xml_captions(text)
    return parse_srt(text)


def caption_text_from_payload(payload: object) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        value = first_value_at_paths(payload, ["data.content", "data.text", "data", "content", "text", "subtitle"])
        return value if isinstance(value, str) else ""
    return ""


def parse_srt(content: str) -> list[Segment]:
    segments: list[Segment] = []
    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if re.fullmatch(r"\d+", lines[0]):
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            continue
        start_raw, end_raw = [part.strip() for part in lines[0].split("-->", 1)]
        text = "\n".join(lines[1:]).strip()
        if not text:
            continue
        segments.append(Segment(start=_parse_timestamp(start_raw), end=_parse_timestamp(end_raw), text=text))
    return segments


def parse_xml_captions(content: str) -> list[Segment]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    segments: list[Segment] = []
    for item in root.iter("text"):
        raw_text = "".join(item.itertext()).strip()
        if not raw_text:
            continue
        start = float(item.attrib.get("start", 0.0))
        duration = float(item.attrib.get("dur", 0.0))
        segments.append(Segment(start=start, end=start + duration, text=html.unescape(raw_text)))
    return segments


def _parse_timestamp(value: str) -> float:
    time_part = value.split()[0].replace(",", ".")
    pieces = time_part.split(":")
    if len(pieces) == 3:
        hours, minutes, seconds = pieces
    elif len(pieces) == 2:
        hours, minutes, seconds = "0", pieces[0], pieces[1]
    else:
        return 0.0
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _entry_language(entry: dict) -> str | None:
    for key in ("language", "language_code", "languageCode", "lang"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            return value
    return None
