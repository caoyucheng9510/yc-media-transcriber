from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.downloaders.base import DownloadResult
from app.downloaders.xiaohongshu import (
    XiaohongshuDownloader,
    collect_xiaohongshu_media_urls,
    extract_note_id,
    inject_widgets_media_url,
    unwrap_note_data,
)
from app.source_resolver import ResolvedSource


def test_extract_note_id_from_supported_paths() -> None:
    source = ResolvedSource(
        kind="url",
        platform="xiaohongshu",
        url="https://www.xiaohongshu.com/explore/0123456789abcdef01234567",
    )
    assert extract_note_id(source)[0] == "0123456789abcdef01234567"


def test_unwrap_note_list() -> None:
    note = unwrap_note_data({"data": [{"note_list": [{"title": "标题", "video": {"url": "https://cdn.example.com/a.mp4"}}]}]})
    assert note is not None
    assert note["title"] == "标题"


def test_widgets_context_adds_media_url() -> None:
    note = {"widgets_context": '{"note_sound_info":{"url":"https://cdn.example.com/audio.mp3"}}'}
    inject_widgets_media_url(note)
    assert collect_xiaohongshu_media_urls(note) == ["https://cdn.example.com/audio.mp3"]


def test_xiaohongshu_endpoint_fallback_and_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    downloader = XiaohongshuDownloader(Settings(app_data_dir=tmp_path, tikhub_api_key="key"))
    calls: list[str] = []

    def fake_request(endpoint: str, params: dict) -> dict:
        calls.append(endpoint)
        if endpoint == "/api/v1/xiaohongshu/app_v2/get_video_note_detail":
            return {"code": 200, "data": {"title": "empty"}}
        return {
            "code": 200,
            "data": {
                "data": [
                    {
                        "note_list": [
                            {
                                "id": "0123456789abcdef01234567",
                                "title": "标题",
                                "user": {"nickname": "作者"},
                                "video_info_v2": {
                                    "media": {
                                        "stream": {
                                            "h264": [
                                                {
                                                    "backup_urls": [
                                                        "https://cdn.example.com/one.mp4",
                                                        "https://cdn.example.com/two.mp4",
                                                    ]
                                                }
                                            ]
                                        }
                                    }
                                },
                            }
                        ]
                    }
                ]
            },
        }

    def fake_download(**kwargs) -> DownloadResult:
        assert kwargs["urls"] == ["https://cdn.example.com/one.mp4", "https://cdn.example.com/two.mp4"]
        return DownloadResult(source_path=tmp_path / "source.mp4", metadata={}, source_fingerprint="direct")

    monkeypatch.setattr(downloader.client, "request", fake_request)
    monkeypatch.setattr("app.downloaders.xiaohongshu.download_first_available", fake_download)

    source = ResolvedSource(
        kind="url",
        platform="xiaohongshu",
        url="https://www.xiaohongshu.com/explore/0123456789abcdef01234567",
        media_id="0123456789abcdef01234567",
    )
    result = downloader.download(source, tmp_path, {})
    assert calls[:2] == [
        "/api/v1/xiaohongshu/app_v2/get_video_note_detail",
        "/api/v1/xiaohongshu/web/get_note_info_v7",
    ]
    assert result.metadata["title"] == "标题"
    assert result.metadata["media_id"] == "0123456789abcdef01234567"
    assert result.metadata["media_id_inferred"] is False
    assert result.source_fingerprint != "direct"
