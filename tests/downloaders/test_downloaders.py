from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.downloaders.base import DownloadResult
from app.downloaders.direct import DirectMediaDownloader
from app.downloaders.tikhub_utils import download_first_available
from app.downloaders.vtt import parse_vtt
from app.downloaders.xiaoyuzhou import XiaoyuzhouDownloader
from app.errors import AppError
from app.source_resolver import ResolvedSource
from app.source_resolver.ssrf import assert_safe_url


class RecordingMetrics:
    def __init__(self) -> None:
        self.http_requests: list[dict] = []

    def record_http_request(self, **kwargs) -> None:
        self.http_requests.append(kwargs)


def test_parse_vtt() -> None:
    content = """WEBVTT

00:00:00.000 --> 00:00:01.000
你好

00:00:01.000 --> 00:00:02.000
世界
"""
    segments = parse_vtt(content)
    assert [segment.text for segment in segments] == ["你好", "世界"]


def test_xiaoyuzhou_metadata_parser(tmp_path: Path) -> None:
    downloader = XiaoyuzhouDownloader(Settings(app_data_dir=tmp_path))
    metadata = downloader._extract_metadata(
        '<meta property="og:title" content="标题"><meta property="og:audio" content="https://cdn.example.com/a.mp3">',
        "https://www.xiaoyuzhoufm.com/episode/abc",
    )
    assert metadata["title"] == "标题"
    assert metadata["audio_url"] == "https://cdn.example.com/a.mp3"


def test_direct_downloader_validates_redirect_targets(tmp_path: Path) -> None:
    class FakeResponse:
        status_code = 302
        headers = {"location": "http://127.0.0.1/private.mp3"}
        url = "https://example.com/audio.mp3"

        def raise_for_status(self) -> None:
            return None

        def close(self) -> None:
            return None

    class FakeClient:
        def build_request(self, method: str, url: str, headers: dict | None = None) -> str:
            return url

        def send(self, request: str, stream: bool = False) -> FakeResponse:
            return FakeResponse()

    downloader = DirectMediaDownloader(Settings(app_data_dir=tmp_path))
    with pytest.raises(AppError) as exc:
        downloader._open_safe_stream(FakeClient(), "https://example.com/audio.mp3")
    assert exc.value.code == "invalid_source"


def test_direct_downloader_allows_trusted_media_fake_ip_redirect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(host: str, *args, **kwargs) -> list:
        if host == "example.com":
            return [(None, None, None, None, ("8.8.8.8", 0))]
        if host == "sns-v10.rednotecdn.com":
            return [(None, None, None, None, ("198.18.0.12", 0))]
        raise AssertionError(host)

    class FakeResponse:
        def __init__(self, status_code: int, url: str, location: str | None = None):
            self.status_code = status_code
            self.url = url
            self.headers = {"location": location} if location else {}

        def raise_for_status(self) -> None:
            return None

        def close(self) -> None:
            return None

    class FakeClient:
        def __init__(self) -> None:
            self.requests: list[str] = []

        def build_request(self, method: str, url: str, headers: dict | None = None) -> str:
            return url

        def send(self, request: str, stream: bool = False) -> FakeResponse:
            self.requests.append(request)
            if len(self.requests) == 1:
                return FakeResponse(
                    302,
                    "https://example.com/audio.mp3",
                    "http://sns-v10.rednotecdn.com/audio.m4a",
                )
            return FakeResponse(200, "http://sns-v10.rednotecdn.com/audio.m4a")

    monkeypatch.setattr("app.source_resolver.ssrf.socket.getaddrinfo", fake_getaddrinfo)
    downloader = DirectMediaDownloader(Settings(app_data_dir=tmp_path))
    response = downloader._open_safe_stream(FakeClient(), "https://example.com/audio.mp3")
    assert response.status_code == 200


def test_direct_downloader_records_download_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(host: str, *args, **kwargs) -> list:
        assert host == "example.com"
        return [(None, None, None, None, ("8.8.8.8", 0))]

    class FakeResponse:
        status_code = 200
        headers: dict = {}
        url = "https://example.com/audio.mp3"

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self):
            yield b"abc"

        def close(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def build_request(self, method: str, url: str, headers: dict | None = None) -> str:
            return url

        def send(self, request: str, stream: bool = False) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr("app.source_resolver.ssrf.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("app.downloaders.direct.httpx.Client", FakeClient)
    metrics = RecordingMetrics()
    downloader = DirectMediaDownloader(Settings(app_data_dir=tmp_path))
    source = ResolvedSource(
        kind="url",
        platform="direct_media",
        url="https://example.com/audio.mp3",
        media_id=None,
    )

    result = downloader.download(source, tmp_path, {}, metrics=metrics)

    assert result.metadata["media_size_bytes"] == 3
    assert metrics.http_requests[0]["provider"] == "direct_media"
    assert metrics.http_requests[0]["request_kind"] == "media_download"
    assert metrics.http_requests[0]["bytes_received"] == 3


def test_direct_downloader_infers_extension_from_content_type_when_url_has_no_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(host: str, *args, **kwargs) -> list:
        assert host == "cdn.example.com"
        return [(None, None, None, None, ("8.8.8.8", 0))]

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "video/mp4; charset=utf-8"}
        url = "https://cdn.example.com/play"

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self):
            yield b"abc"

        def close(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def build_request(self, method: str, url: str, headers: dict | None = None) -> str:
            return url

        def send(self, request: str, stream: bool = False) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr("app.source_resolver.ssrf.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("app.downloaders.direct.httpx.Client", FakeClient)
    downloader = DirectMediaDownloader(Settings(app_data_dir=tmp_path))
    source = ResolvedSource(
        kind="url",
        platform="direct_media",
        url="https://cdn.example.com/play",
        media_id=None,
    )

    result = downloader.download(source, tmp_path, {})

    assert result.source_path == tmp_path / "source.mp4"
    assert result.source_path.read_bytes() == b"abc"


def test_direct_downloader_passes_request_headers_to_http_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(host: str, *args, **kwargs) -> list:
        assert host == "example.com"
        return [(None, None, None, None, ("8.8.8.8", 0))]

    class FakeResponse:
        status_code = 200
        headers: dict = {}
        url = "https://example.com/audio.mp3"

        def raise_for_status(self) -> None:
            return None

        def close(self) -> None:
            return None

    class FakeClient:
        def __init__(self) -> None:
            self.requests: list[dict] = []

        def build_request(self, method: str, url: str, headers: dict | None = None) -> dict:
            return {"method": method, "url": url, "headers": headers}

        def send(self, request: dict, stream: bool = False) -> FakeResponse:
            self.requests.append(request)
            return FakeResponse()

    monkeypatch.setattr("app.source_resolver.ssrf.socket.getaddrinfo", fake_getaddrinfo)
    client = FakeClient()
    headers = {"Referer": "https://www.bilibili.com", "User-Agent": "TestBrowser"}
    downloader = DirectMediaDownloader(Settings(app_data_dir=tmp_path), request_headers=headers)

    response = downloader._open_safe_stream(client, "https://example.com/audio.mp3")
    response.close()

    assert client.requests == [
        {
            "method": "GET",
            "url": "https://example.com/audio.mp3",
            "headers": headers,
        }
    ]


def test_direct_downloader_records_http_error_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(host: str, *args, **kwargs) -> list:
        assert host == "example.com"
        return [(None, None, None, None, ("8.8.8.8", 0))]

    class FakeResponse:
        def __init__(self) -> None:
            self.status_code = 403
            self.headers: dict = {}
            self.url = "https://example.com/audio.mp3"
            self.close_count = 0

        def raise_for_status(self) -> None:
            request = httpx.Request("GET", self.url)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("forbidden", request=request, response=response)

        def close(self) -> None:
            self.close_count += 1

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def build_request(self, method: str, url: str, headers: dict | None = None) -> str:
            return url

        def send(self, request: str, stream: bool = False) -> FakeResponse:
            return response

    monkeypatch.setattr("app.source_resolver.ssrf.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("app.downloaders.direct.httpx.Client", FakeClient)
    response = FakeResponse()
    metrics = RecordingMetrics()
    downloader = DirectMediaDownloader(Settings(app_data_dir=tmp_path))
    source = ResolvedSource(
        kind="url",
        platform="direct_media",
        url="https://example.com/audio.mp3",
        media_id=None,
    )

    with pytest.raises(AppError):
        downloader.download(source, tmp_path, {}, metrics=metrics)

    assert response.close_count == 1
    assert len(metrics.http_requests) == 1
    assert metrics.http_requests[0]["provider"] == "direct_media"
    assert metrics.http_requests[0]["request_kind"] == "media_download"
    assert metrics.http_requests[0]["status_code"] == 403
    assert metrics.http_requests[0]["error_code"] == "HTTPStatusError"


def test_direct_downloader_closes_response_on_resource_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(host: str, *args, **kwargs) -> list:
        assert host == "example.com"
        return [(None, None, None, None, ("8.8.8.8", 0))]

    class FakeResponse:
        status_code = 200
        headers: dict = {}
        url = "https://example.com/audio.mp3"

        def __init__(self) -> None:
            self.close_count = 0

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self):
            yield b"ab"
            yield b"cd"

        def close(self) -> None:
            self.close_count += 1

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def build_request(self, method: str, url: str, headers: dict | None = None) -> str:
            return url

        def send(self, request: str, stream: bool = False) -> FakeResponse:
            return response

    monkeypatch.setattr("app.source_resolver.ssrf.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("app.downloaders.direct.httpx.Client", FakeClient)
    response = FakeResponse()
    downloader = DirectMediaDownloader(Settings(app_data_dir=tmp_path, app_max_upload_mb=0))
    source = ResolvedSource(
        kind="url",
        platform="direct_media",
        url="https://example.com/audio.mp3",
        media_id=None,
    )

    with pytest.raises(AppError) as exc:
        downloader.download(source, tmp_path, {})

    assert exc.value.code == "resource_limited"
    assert response.close_count == 1


def test_tikhub_candidates_continue_for_download_failed_and_invalid_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    headers = {"User-Agent": "TestBrowser"}

    class FakeDirect:
        def __init__(self, settings: Settings, request_headers: dict | None = None):
            assert request_headers == headers

        def download(
            self,
            source: ResolvedSource,
            job_temp_dir: Path,
            options: dict,
            metrics=None,
        ) -> DownloadResult:
            calls.append(source.url)
            if source.url.endswith("one.mp4"):
                raise AppError("download_failed", "first candidate failed", "downloading")
            if source.url.endswith("two.mp4"):
                raise AppError("invalid_source", "second candidate unsafe", "downloading")
            return DownloadResult(
                source_path=job_temp_dir / "source.mp4",
                metadata={"platform": "direct_media"},
                source_fingerprint="ok",
            )

    monkeypatch.setattr("app.downloaders.tikhub_utils.DirectMediaDownloader", FakeDirect)
    source = ResolvedSource(kind="url", platform="bilibili", url="https://www.bilibili.com/video/BV1")

    result = download_first_available(
        settings=Settings(app_data_dir=tmp_path),
        urls=[
            "https://cdn.example.com/one.mp4",
            "https://cdn.example.com/two.mp4",
            "https://cdn.example.com/three.mp4",
        ],
        source=source,
        job_temp_dir=tmp_path,
        options={},
        media_id="BV1",
        request_headers=headers,
    )

    assert result.source_fingerprint == "ok"
    assert calls == [
        "https://cdn.example.com/one.mp4",
        "https://cdn.example.com/two.mp4",
        "https://cdn.example.com/three.mp4",
    ]


def test_tikhub_candidates_return_invalid_source_when_all_candidates_are_unsafe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeDirect:
        def __init__(self, settings: Settings, request_headers: dict | None = None):
            return None

        def download(
            self,
            source: ResolvedSource,
            job_temp_dir: Path,
            options: dict,
            metrics=None,
        ) -> DownloadResult:
            calls.append(source.url)
            raise AppError("invalid_source", "unsafe candidate", "downloading")

    monkeypatch.setattr("app.downloaders.tikhub_utils.DirectMediaDownloader", FakeDirect)
    source = ResolvedSource(kind="url", platform="xiaohongshu", url="https://www.xiaohongshu.com/explore/1")

    with pytest.raises(AppError) as exc:
        download_first_available(
            settings=Settings(app_data_dir=tmp_path),
            urls=["https://cdn.example.com/one.mp4", "https://cdn.example.com/two.mp4"],
            source=source,
            job_temp_dir=tmp_path,
            options={},
        )

    assert exc.value.code == "invalid_source"
    assert calls == ["https://cdn.example.com/one.mp4", "https://cdn.example.com/two.mp4"]


def test_tikhub_candidates_stop_on_resource_limited(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeDirect:
        def __init__(self, settings: Settings, request_headers: dict | None = None):
            return None

        def download(
            self,
            source: ResolvedSource,
            job_temp_dir: Path,
            options: dict,
            metrics=None,
        ) -> DownloadResult:
            calls.append(source.url)
            raise AppError("resource_limited", "candidate too large", "downloading")

    monkeypatch.setattr("app.downloaders.tikhub_utils.DirectMediaDownloader", FakeDirect)
    source = ResolvedSource(kind="url", platform="xiaohongshu", url="https://www.xiaohongshu.com/explore/1")

    with pytest.raises(AppError) as exc:
        download_first_available(
            settings=Settings(app_data_dir=tmp_path),
            urls=["https://cdn.example.com/one.mp4", "https://cdn.example.com/two.mp4"],
            source=source,
            job_temp_dir=tmp_path,
            options={},
        )

    assert exc.value.code == "resource_limited"
    assert calls == ["https://cdn.example.com/one.mp4"]


def test_ssrf_blocks_untrusted_fake_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(host: str, *args, **kwargs) -> list:
        assert host == "cdn.example.com"
        return [(None, None, None, None, ("198.18.0.12", 0))]

    monkeypatch.setattr("app.source_resolver.ssrf.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(AppError) as exc:
        assert_safe_url(
            "https://cdn.example.com/video.mp4",
            trusted_media_host_suffixes=("rednotecdn.com",),
            fake_ip_cidrs=("198.18.0.0/15",),
        )
    assert exc.value.code == "invalid_source"
    assert "cdn.example.com" in exc.value.message
    assert "198.18.0.12" in exc.value.message


def test_ssrf_blocks_trusted_media_host_on_non_fake_private_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(host: str, *args, **kwargs) -> list:
        assert host == "sns-v10.rednotecdn.com"
        return [(None, None, None, None, ("10.0.0.12", 0))]

    monkeypatch.setattr("app.source_resolver.ssrf.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(AppError) as exc:
        assert_safe_url(
            "https://sns-v10.rednotecdn.com/video.mp4",
            trusted_media_host_suffixes=("rednotecdn.com",),
            fake_ip_cidrs=("198.18.0.0/15",),
        )
    assert exc.value.code == "invalid_source"
    assert "10.0.0.12" in exc.value.message
