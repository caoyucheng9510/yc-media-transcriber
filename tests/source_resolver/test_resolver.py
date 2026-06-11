from __future__ import annotations

import pytest

from app.errors import AppError
from app.source_resolver import SourceResolver
from app.source_resolver import resolver as resolver_module


def test_resolver_extracts_platforms() -> None:
    resolver = SourceResolver()
    assert resolver.resolve("url", "https://www.youtube.com/watch?v=EN7frwQIbKc").platform == "youtube"
    bili = resolver.resolve("url", "https://www.bilibili.com/video/BV1vd7D6UEf8/")
    assert bili.platform == "bilibili"
    assert bili.media_id == "BV1vd7D6UEf8"
    assert bili.source_identity == "bilibili:BV1vd7D6UEf8:p1"
    xiaoyuzhou = resolver.resolve(
        "text",
        "听这个 https://www.xiaoyuzhoufm.com/episode/6a15a2cbff7b9a8c0a5b953f",
    )
    assert xiaoyuzhou.platform == "xiaoyuzhou"


def test_direct_media_blocks_private_ip() -> None:
    resolver = SourceResolver()
    with pytest.raises(AppError) as exc:
        resolver.resolve("url", "http://127.0.0.1/test.mp3")
    assert exc.value.code == "invalid_source"


def test_resolver_expands_short_link_before_building_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_resolve_short_url(url: str, *, allowed_platforms: set[str], timeout: float = 8.0) -> str:
        assert allowed_platforms == {"xiaohongshu"}
        return "https://www.xiaohongshu.com/explore/0123456789abcdef01234567?xsec_token=abc"

    monkeypatch.setattr(resolver_module, "resolve_short_url", fake_resolve_short_url)
    resolved = SourceResolver().resolve("text", "看这个 https://xhslink.com/o/abc")

    assert resolved.platform == "xiaohongshu"
    assert resolved.input_url == "https://xhslink.com/o/abc"
    assert resolved.display_url == "https://xhslink.com/o/abc"
    assert resolved.url.startswith("https://www.xiaohongshu.com/explore/")
    assert resolved.media_id == "0123456789abcdef01234567"
    assert resolved.source_identity == "xiaohongshu:0123456789abcdef01234567"


def test_resolver_propagates_invalid_short_link_target(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_resolve_short_url(url: str, *, allowed_platforms: set[str], timeout: float = 8.0) -> str:
        raise AppError("invalid_source", "短链跳转到了不支持的平台。", "downloading")

    monkeypatch.setattr(resolver_module, "resolve_short_url", fake_resolve_short_url)

    with pytest.raises(AppError) as exc:
        SourceResolver().resolve("url", "https://xhslink.com/o/abc")
    assert exc.value.code == "invalid_source"


def test_resolver_uses_same_youtube_identity_for_short_and_watch_urls() -> None:
    resolver = SourceResolver()
    short = resolver.resolve("url", "https://youtu.be/EN7frwQIbKc")
    watch = resolver.resolve("url", "https://www.youtube.com/watch?v=EN7frwQIbKc")

    assert short.source_identity == "youtube:EN7frwQIbKc"
    assert watch.source_identity == short.source_identity
    assert watch.fingerprint == short.fingerprint


def test_resolver_includes_bilibili_page_in_identity() -> None:
    resolver = SourceResolver()
    page_one = resolver.resolve("url", "https://www.bilibili.com/video/BV1vd7D6UEf8/")
    page_two = resolver.resolve("url", "https://www.bilibili.com/video/BV1vd7D6UEf8/?p=2")

    assert page_one.media_id == page_two.media_id == "BV1vd7D6UEf8"
    assert page_one.source_identity == "bilibili:BV1vd7D6UEf8:p1"
    assert page_two.source_identity == "bilibili:BV1vd7D6UEf8:p2"
    assert page_one.fingerprint != page_two.fingerprint
