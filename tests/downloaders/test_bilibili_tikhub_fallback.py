from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.downloaders.base import DownloadResult
from app.downloaders.bilibili_headers import bilibili_media_headers
from app.downloaders.bilibili_tikhub import BilibiliTikHubFallback, extract_bv_id
from app.downloaders.ytdlp import YtDlpDownloader
from app.errors import AppError
from app.source_resolver import ResolvedSource


def test_extract_bv_id() -> None:
    source = ResolvedSource(kind="url", platform="bilibili", url="https://www.bilibili.com/video/BV1vd7D6UEf8/")
    assert extract_bv_id(source)[0] == "BV1vd7D6UEf8"


def test_ytdlp_bilibili_reuses_bilibili_media_headers(tmp_path: Path) -> None:
    settings = Settings(app_data_dir=tmp_path)
    assert YtDlpDownloader(settings, "bilibili")._http_headers() == bilibili_media_headers()
    assert YtDlpDownloader(settings, "youtube")._http_headers() == {}


def test_bilibili_tikhub_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fallback = BilibiliTikHubFallback(Settings(app_data_dir=tmp_path, tikhub_api_key="key"))
    calls: list[str] = []

    def fake_request(endpoint: str, params: dict) -> dict:
        calls.append(endpoint)
        if endpoint == "/api/v1/bilibili/web/fetch_one_video":
            return {"code": 200, "data": {"data": {"title": "empty"}}}
        if endpoint == "/api/v1/bilibili/web/fetch_one_video_v2":
            return {
                "code": 200,
                "data": {"data": {"title": "标题", "owner": {"name": "作者"}, "cid": 123}},
            }
        return {"code": 200, "data": {"data": {"dash": {"audio": [{"baseUrl": "https://cdn.example.com/audio.m4a"}]}}}}

    def fake_download(**kwargs) -> DownloadResult:
        assert kwargs["urls"] == ["https://cdn.example.com/audio.m4a"]
        assert kwargs["request_headers"]["Referer"] == "https://www.bilibili.com"
        assert "Chrome" in kwargs["request_headers"]["User-Agent"]
        return DownloadResult(source_path=tmp_path / "source.m4a", metadata={}, source_fingerprint="direct")

    monkeypatch.setattr(fallback.client, "request", fake_request)
    monkeypatch.setattr("app.downloaders.bilibili_tikhub.download_first_available", fake_download)

    source = ResolvedSource(kind="url", platform="bilibili", url="https://www.bilibili.com/video/BV1vd7D6UEf8/", media_id="BV1vd7D6UEf8")
    result = fallback.download(source, tmp_path, {})
    assert calls == [
        "/api/v1/bilibili/web/fetch_one_video",
        "/api/v1/bilibili/web/fetch_one_video_v2",
        "/api/v1/bilibili/web/fetch_video_playurl",
    ]
    assert result.metadata["title"] == "标题"
    assert result.metadata["provider"] == "tikhub"
    assert result.source_fingerprint != "direct"


def test_bilibili_tikhub_fails_when_requested_page_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback = BilibiliTikHubFallback(Settings(app_data_dir=tmp_path, tikhub_api_key="key"))
    calls: list[str] = []

    def fake_request(endpoint: str, params: dict) -> dict:
        calls.append(endpoint)
        return {
            "code": 200,
            "data": {
                "data": {
                    "title": "multi page",
                    "pages": [
                        {"page": 1, "cid": 111},
                        {"page": 2, "cid": 222},
                    ],
                }
            },
        }

    def fake_download(**kwargs) -> DownloadResult:
        raise AssertionError("download should not run when requested page is missing")

    monkeypatch.setattr(fallback.client, "request", fake_request)
    monkeypatch.setattr("app.downloaders.bilibili_tikhub.download_first_available", fake_download)

    source = ResolvedSource(
        kind="url",
        platform="bilibili",
        url="https://www.bilibili.com/video/BV1vd7D6UEf8/?p=99",
        media_id="BV1vd7D6UEf8",
        source_identity="bilibili:BV1vd7D6UEf8:p99",
    )
    with pytest.raises(AppError) as exc:
        fallback.download(source, tmp_path, {})

    assert exc.value.code == "download_failed"
    assert calls == ["/api/v1/bilibili/web/fetch_one_video"]
