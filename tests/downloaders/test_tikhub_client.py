from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.downloaders import tikhub_client
from app.downloaders.tikhub_client import TikHubClient
from app.errors import AppError


class RecordingMetrics:
    def __init__(self) -> None:
        self.tikhub_calls: list[dict] = []
        self.http_requests: list[dict] = []

    def record_tikhub_call(self, **kwargs) -> None:
        self.tikhub_calls.append(kwargs)

    def record_http_request(self, **kwargs) -> None:
        self.http_requests.append(kwargs)


class FakeResponse:
    def __init__(self, status_code: int, payload: object):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=httpx.Request("GET", "https://api.tikhub.io/test"), response=self)


def install_fake_client(monkeypatch: pytest.MonkeyPatch, responses: list[FakeResponse]) -> list[dict]:
    calls: list[dict] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url: str, params: dict, headers: dict) -> FakeResponse:
            calls.append({"url": url, "params": params, "headers": headers})
            return responses.pop(0)

    monkeypatch.setattr(tikhub_client.httpx, "Client", FakeClient)
    monkeypatch.setattr(tikhub_client, "_sleep", lambda seconds: None)
    return calls


def test_tikhub_client_requires_key(tmp_path) -> None:
    client = TikHubClient(Settings(app_data_dir=tmp_path))
    with pytest.raises(AppError) as exc:
        client.request("/api/test", {})
    assert exc.value.code == "platform_provider_not_configured"


def test_tikhub_client_validates_envelope(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_client(monkeypatch, [FakeResponse(200, {"code": 200, "data": {"ok": True}})])
    client = TikHubClient(Settings(app_data_dir=tmp_path, tikhub_api_key="key"))
    payload = client.request("/api/test", {"id": "1"})
    assert payload["data"]["ok"] is True


def test_tikhub_client_rejects_non_dict_json(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_client(monkeypatch, [FakeResponse(200, ["bad"])])
    client = TikHubClient(Settings(app_data_dir=tmp_path, tikhub_api_key="key"))
    with pytest.raises(AppError) as exc:
        client.request("/api/test", {})
    assert exc.value.code == "download_failed"


def test_tikhub_client_tries_alternate_key_on_auth_failure(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_client(
        monkeypatch,
        [
            FakeResponse(401, {"message": "bad key"}),
            FakeResponse(200, {"code": 200, "data": {"ok": True}}),
        ],
    )
    client = TikHubClient(
        Settings(
            app_data_dir=tmp_path,
            tikhub_api_key="primary",
            tikhub_alternate_api_key="alternate",
        )
    )
    payload = client.request("/api/test", {})
    assert payload["data"]["ok"] is True
    assert calls[0]["headers"]["Authorization"] == "Bearer primary"
    assert calls[1]["headers"]["Authorization"] == "Bearer alternate"


def test_tikhub_client_retries_5xx(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_client(
        monkeypatch,
        [
            FakeResponse(500, {"message": "temporary"}),
            FakeResponse(200, {"code": "200", "data": {"ok": True}}),
        ],
    )
    client = TikHubClient(
        Settings(
            app_data_dir=tmp_path,
            tikhub_api_key="key",
            tikhub_max_retries=1,
            tikhub_retry_delay=0,
        )
    )
    assert client.request("/api/test", {})["data"]["ok"] is True
    assert len(calls) == 2


def test_tikhub_client_retries_429_with_jitter(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_client(
        monkeypatch,
        [
            FakeResponse(429, {"message": "rate limited"}),
            FakeResponse(200, {"code": "200", "data": {"ok": True}}),
        ],
    )
    sleeps: list[float] = []
    monkeypatch.setattr(tikhub_client.random, "uniform", lambda start, end: 1.25)
    monkeypatch.setattr(tikhub_client, "_sleep", lambda seconds: sleeps.append(seconds))
    client = TikHubClient(
        Settings(
            app_data_dir=tmp_path,
            tikhub_api_key="key",
            tikhub_max_retries=1,
            tikhub_retry_delay=5,
            tikhub_request_min_interval_seconds=0,
            tikhub_request_max_interval_seconds=0,
        )
    )

    assert client.request("/api/test", {})["data"]["ok"] is True
    assert len(calls) == 2
    assert sleeps == [6.25]


def test_tikhub_client_records_metrics(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_client(
        monkeypatch,
        [
            FakeResponse(500, {"message": "temporary"}),
            FakeResponse(200, {"code": "200", "data": {"ok": True}}),
        ],
    )
    metrics = RecordingMetrics()
    client = TikHubClient(
        Settings(
            app_data_dir=tmp_path,
            tikhub_api_key="key",
            tikhub_max_retries=1,
            tikhub_retry_delay=0,
        ),
        metrics=metrics,
    )

    assert client.request("/api/test", {})["data"]["ok"] is True

    assert metrics.tikhub_calls == [{"endpoint": "/api/test"}]
    assert [item["status_code"] for item in metrics.http_requests] == [500, 200]
    assert [item["retry_attempt"] for item in metrics.http_requests] == [1, 2]
    assert all(item["provider"] == "tikhub" for item in metrics.http_requests)
