from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.downloaders.base import DownloadResult
from app.downloaders.youtube_tikhub import (
    YouTubeTikHubFallback,
    parse_srt,
    parse_xml_captions,
    select_subtitle_entry,
)
from app.downloaders.ytdlp import YtDlpDownloader
from app.source_resolver import ResolvedSource


def test_parse_srt() -> None:
    segments = parse_srt("1\n00:00:00,000 --> 00:00:01,500\n你好\n")
    assert segments[0].start == 0
    assert segments[0].end == 1.5
    assert segments[0].text == "你好"


def test_parse_xml_captions() -> None:
    segments = parse_xml_captions('<transcript><text start="1.0" dur="2.0">hello</text></transcript>')
    assert segments[0].start == 1.0
    assert segments[0].end == 3.0
    assert segments[0].text == "hello"


def test_select_subtitle_language_priority() -> None:
    entry = select_subtitle_entry(
        {
            "subtitles": {
                "items": [
                    {"language_code": "en", "url": "https://cdn.example.com/en"},
                    {"language_code": "zh-CN", "url": "https://cdn.example.com/zh"},
                ]
            }
        }
    )
    assert entry is not None
    assert entry["language_code"] == "zh-CN"


def test_youtube_tikhub_download_uses_audio_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fallback = YouTubeTikHubFallback(Settings(app_data_dir=tmp_path, tikhub_api_key="key"))

    def fake_request(endpoint: str, params: dict) -> dict:
        assert endpoint == "/api/v1/youtube/web/get_video_info"
        return {
            "code": 200,
            "data": {
                "title": "标题",
                "channel": {"name": "频道"},
                "audios": {"items": [{"url": "https://cdn.example.com/audio.m4a"}]},
            },
        }

    def fake_download(**kwargs) -> DownloadResult:
        assert kwargs["urls"] == ["https://cdn.example.com/audio.m4a"]
        return DownloadResult(source_path=tmp_path / "source.m4a", metadata={}, source_fingerprint="direct")

    monkeypatch.setattr(fallback.client, "request", fake_request)
    monkeypatch.setattr("app.downloaders.youtube_tikhub.download_first_available", fake_download)
    source = ResolvedSource(kind="url", platform="youtube", url="https://www.youtube.com/watch?v=abc123", media_id="abc123")
    result = fallback.download(source, tmp_path, {})
    assert result.metadata["provider"] == "tikhub"
    assert result.metadata["title"] == "标题"
    assert result.source_fingerprint != "direct"


def test_ytdlp_download_can_call_youtube_tikhub_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeFallback:
        def __init__(self, settings: Settings, metrics=None):
            return None

        def download(
            self,
            source: ResolvedSource,
            job_temp_dir: Path,
            options: dict,
            metrics=None,
        ) -> DownloadResult:
            return DownloadResult(source_path=tmp_path / "source.m4a", metadata={"provider": "tikhub"}, source_fingerprint="fp")

    monkeypatch.setattr("app.downloaders.ytdlp.YouTubeTikHubFallback", FakeFallback)
    downloader = YtDlpDownloader(Settings(app_data_dir=tmp_path, tikhub_api_key="key"), "youtube")
    source = ResolvedSource(kind="url", platform="youtube", url="https://www.youtube.com/watch?v=abc123", media_id="abc123")
    result = downloader._download_with_tikhub_fallback(source, tmp_path, {}, "yt-dlp failed")
    assert result.metadata["provider"] == "tikhub"
