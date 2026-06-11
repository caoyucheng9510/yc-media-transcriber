from __future__ import annotations

import httpx
import pytest

from app.errors import AppError
from app.source_resolver import short_url


class FakeResponse:
    def __init__(self, url: str, status_code: int = 200, history: list | None = None):
        self.url = httpx.URL(url)
        self.status_code = status_code
        self.history = history or []


def install_fake_client(monkeypatch: pytest.MonkeyPatch, *, head: FakeResponse, get: FakeResponse | None = None) -> None:
    class FakeClient:
        def __init__(self, *args, **kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def head(self, url: str) -> FakeResponse:
            return head

        def get(self, url: str) -> FakeResponse:
            assert get is not None
            return get

    monkeypatch.setattr(short_url.httpx, "Client", FakeClient)


def test_short_url_resolves_head_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_client(
        monkeypatch,
        head=FakeResponse("https://www.douyin.com/video/123", history=[object()]),
    )
    resolved = short_url.resolve_short_url("https://v.douyin.com/abc/", allowed_platforms={"douyin"})
    assert resolved == "https://www.douyin.com/video/123"


def test_short_url_falls_back_to_get(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_client(
        monkeypatch,
        head=FakeResponse("https://xhslink.com/a", status_code=404),
        get=FakeResponse("https://www.xiaohongshu.com/explore/0123456789abcdef01234567", history=[object()]),
    )
    resolved = short_url.resolve_short_url("https://xhslink.com/a", allowed_platforms={"xiaohongshu"})
    assert "xiaohongshu.com/explore" in resolved


def test_short_url_rejects_unknown_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_client(
        monkeypatch,
        head=FakeResponse("https://example.com/video/123", history=[object()]),
    )
    with pytest.raises(AppError) as exc:
        short_url.resolve_short_url("https://v.douyin.com/abc/", allowed_platforms={"douyin"})
    assert exc.value.code == "invalid_source"
