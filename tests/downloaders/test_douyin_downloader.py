from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.downloaders.base import DownloadResult
from app.downloaders.douyin import DouyinDownloader, collect_douyin_media_urls, extract_aweme_id
from app.errors import AppError
from app.source_resolver import ResolvedSource


def test_extract_aweme_id_from_video_url() -> None:
    source = ResolvedSource(kind="url", platform="douyin", url="https://www.douyin.com/video/7333333333333333333")
    assert extract_aweme_id(source)[0] == "7333333333333333333"


def test_extract_aweme_id_from_query() -> None:
    source = ResolvedSource(kind="url", platform="douyin", url="https://www.douyin.com/?aweme_id=7333333333333333333")
    assert extract_aweme_id(source)[0] == "7333333333333333333"


def test_collect_douyin_audio_url_first() -> None:
    detail = {
        "music": {"play_url": {"url_list": ["https://cdn.example.com/audio.m4a"]}},
        "video": {"play_addr": {"url_list": ["https://cdn.example.com/video.mp4"]}},
    }
    assert collect_douyin_media_urls(detail)[0].endswith("audio.m4a")


def test_douyin_downloader_sets_stable_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    downloader = DouyinDownloader(Settings(app_data_dir=tmp_path, tikhub_api_key="key"))

    def fake_request(endpoint: str, params: dict) -> dict:
        assert endpoint == "/api/v1/douyin/web/fetch_one_video"
        assert params["aweme_id"] == "7333333333333333333"
        return {
            "code": 200,
            "data": {
                "aweme_detail": {
                    "desc": "标题",
                    "author": {"nickname": "作者"},
                    "music": {"play_url": {"url_list": ["https://cdn.example.com/audio.m4a"]}},
                }
            },
        }

    def fake_download(**kwargs) -> DownloadResult:
        assert kwargs["urls"] == ["https://cdn.example.com/audio.m4a"]
        return DownloadResult(source_path=tmp_path / "source.m4a", metadata={}, source_fingerprint="direct")

    monkeypatch.setattr(downloader.client, "request", fake_request)
    monkeypatch.setattr("app.downloaders.douyin.download_first_available", fake_download)

    source = ResolvedSource(kind="url", platform="douyin", url="https://www.douyin.com/video/7333333333333333333")
    result = downloader.download(source, tmp_path, {})
    assert result.metadata["platform"] == "douyin"
    assert result.metadata["provider"] == "tikhub"
    assert result.metadata["title"] == "标题"
    assert result.metadata["media_id"] == "7333333333333333333"
    assert result.source_fingerprint != "direct"


def test_douyin_downloader_fails_without_media_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    downloader = DouyinDownloader(
        Settings(app_data_dir=tmp_path, tikhub_api_key="key", tikhub_max_retries=0)
    )
    monkeypatch.setattr(downloader.client, "request", lambda endpoint, params: {"code": 200, "data": {"aweme_detail": {"desc": "x"}}})
    source = ResolvedSource(kind="url", platform="douyin", url="https://www.douyin.com/video/7333333333333333333")
    with pytest.raises(AppError) as exc:
        downloader.download(source, tmp_path, {})
    assert exc.value.code == "download_failed"
