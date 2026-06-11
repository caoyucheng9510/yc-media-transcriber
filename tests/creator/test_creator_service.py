from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.creator.service import CreatorPreviewCache, CreatorService
from app.schemas import CreatorPreviewRequest, CreatorSubmitRequest, JobOptions
from app.schemas import CreateJobResponse


class FakeTikHubClient:
    def __init__(self, settings: Settings):
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def request(self, endpoint: str, params: dict[str, Any] | None = None, metrics: Any | None = None) -> dict[str, Any]:
        params = params or {}
        self.calls.append((endpoint, params))
        if endpoint == "/api/v1/xiaohongshu/app_v2/get_user_info":
            return {
                "code": 200,
                "data": {
                    "data": {
                        "userid": "user_1",
                        "nickname": "creator",
                        "images": "https://img.example.com/avatar.jpg",
                    }
                },
            }
        if endpoint == "/api/v1/xiaohongshu/app_v2/get_user_posted_notes":
            cursor = params.get("cursor") or ""
            if cursor == "":
                return {
                    "code": 200,
                    "data": {
                        "data": {
                            "has_more": True,
                            "notes": [
                                _note("note_video_1", "video", "video 1"),
                                _note("note_normal_1", "normal", "image 1"),
                                _note("note_video_1", "video", "duplicate"),
                            ],
                        }
                    },
                }
            return {
                "code": 200,
                "data": {
                    "data": {
                        "has_more": False,
                        "notes": [_note("note_video_2", "video", "video 2")],
                    }
                },
            }
        raise AssertionError(endpoint)


class SparseVideoTikHubClient:
    def __init__(self, settings: Settings):
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def request(self, endpoint: str, params: dict[str, Any] | None = None, metrics: Any | None = None) -> dict[str, Any]:
        params = params or {}
        self.calls.append((endpoint, params))
        if endpoint == "/api/v1/xiaohongshu/app_v2/get_user_info":
            return {"code": 200, "data": {"data": {"userid": "user_1", "nickname": "creator"}}}
        if endpoint == "/api/v1/xiaohongshu/app_v2/get_user_posted_notes":
            cursor = params.get("cursor") or ""
            if cursor == "":
                notes = [_note("note_video_1", "video", "video 1")]
                notes.extend(_note(f"note_normal_a_{index}", "normal", f"image {index}") for index in range(19))
                return {
                    "code": 200,
                    "data": {"data": {"has_more": True, "cursor": "cursor_1", "notes": notes}},
                }
            notes = [_note(f"note_normal_b_{index}", "normal", f"image b {index}") for index in range(20)]
            return {
                "code": 200,
                "data": {"data": {"has_more": True, "cursor": "cursor_2", "notes": notes}},
            }
        raise AssertionError(endpoint)


class FakeDouyinTikHubClient:
    sec_user_id = "MS4wLjABAAAAprofile"

    def __init__(self, settings: Settings):
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def request(self, endpoint: str, params: dict[str, Any] | None = None, metrics: Any | None = None) -> dict[str, Any]:
        params = params or {}
        self.calls.append((endpoint, params))
        if endpoint == "/api/v1/douyin/app/v3/handler_user_profile":
            assert params["sec_user_id"] == self.sec_user_id
            return {
                "code": 200,
                "data": {
                    "user": {
                        "sec_uid": self.sec_user_id,
                        "nickname": "douyin creator",
                        "signature": "creator profile",
                    }
                },
            }
        if endpoint == "/api/v1/douyin/app/v3/fetch_user_post_videos":
            assert params["sec_user_id"] == self.sec_user_id
            return {
                "code": 200,
                "data": {
                    "aweme_list": [_aweme("7333333333333333333", "douyin video")],
                    "has_more": False,
                    "max_cursor": "0",
                },
            }
        raise AssertionError(endpoint)


class RecordingSubmission:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    def create_url_job(
        self,
        *,
        source_type: str,
        source_value: str,
        options: JobOptions,
        metadata: dict[str, Any] | None = None,
        title: str | None = None,
    ) -> CreateJobResponse:
        job_id = f"job_{len(self.created) + 1}"
        self.created.append(
            {
                "source_type": source_type,
                "source_value": source_value,
                "options": options,
                "metadata": metadata,
                "title": title,
            }
        )
        return CreateJobResponse(job_id=job_id, status="queued", view_url="/")


def test_xiaohongshu_preview_filters_paginates_and_dedupes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.creator.service.TikHubClient", FakeTikHubClient)
    service = CreatorService(
        settings=Settings(app_data_dir=tmp_path, tikhub_api_key="key"),
        cache=CreatorPreviewCache(ttl_seconds=3600),
    )

    preview = service.preview(
        CreatorPreviewRequest(
            input="https://xhslink.com/m/example",
            max_pages=2,
            max_items=20,
        )
    )

    assert preview.platform == "xiaohongshu"
    assert preview.creator.name == "creator"
    assert [item.work_id for item in preview.items] == ["note_video_1", "note_video_2"]
    assert all(item.transcribable for item in preview.items)
    assert preview.pagination.fetched_pages == 2
    assert preview.pagination.fetched_count == 2
    assert preview.pagination.scanned_count == 4
    assert preview.pagination.filtered_count == 1
    assert preview.pagination.stop_reason == "no_more"


def test_xiaohongshu_preview_stops_at_page_limit_when_videos_are_sparse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.creator.service.TikHubClient", SparseVideoTikHubClient)
    service = CreatorService(
        settings=Settings(app_data_dir=tmp_path, tikhub_api_key="key"),
        cache=CreatorPreviewCache(ttl_seconds=3600),
    )

    preview = service.preview(
        CreatorPreviewRequest(
            input="https://xhslink.com/m/example",
            max_pages=2,
            max_items=2,
            page_size=20,
        )
    )

    assert [item.work_id for item in preview.items] == ["note_video_1"]
    assert preview.pagination.fetched_pages == 2
    assert preview.pagination.fetched_count == 1
    assert preview.pagination.scanned_count == 40
    assert preview.pagination.filtered_count == 39
    assert preview.pagination.stop_reason == "page_limit"


def test_douyin_preview_resolves_short_profile_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_resolve_short_url(url: str, *, allowed_platforms: set[str]) -> str:
        assert url == "https://v.douyin.com/abc/"
        assert allowed_platforms == {"douyin"}
        return f"https://www.iesdouyin.com/share/user/{FakeDouyinTikHubClient.sec_user_id}?from=share"

    monkeypatch.setattr("app.creator.service.TikHubClient", FakeDouyinTikHubClient)
    monkeypatch.setattr("app.source_resolver.resolver.resolve_short_url", fake_resolve_short_url)
    service = CreatorService(
        settings=Settings(app_data_dir=tmp_path, tikhub_api_key="key"),
        cache=CreatorPreviewCache(ttl_seconds=3600),
    )

    preview = service.preview(
        CreatorPreviewRequest(
            input="长按复制此条消息，打开抖音搜索，查看TA的更多作品。 https://v.douyin.com/abc/",
            max_pages=1,
            max_items=1,
        )
    )

    assert preview.platform == "douyin"
    assert preview.creator.id == FakeDouyinTikHubClient.sec_user_id
    assert preview.creator.profile_url == (
        f"https://www.iesdouyin.com/share/user/{FakeDouyinTikHubClient.sec_user_id}?from=share"
    )
    assert [item.work_id for item in preview.items] == ["7333333333333333333"]
    assert service.client.calls[0] == (  # type: ignore[attr-defined]
        "/api/v1/douyin/app/v3/handler_user_profile",
        {"sec_user_id": FakeDouyinTikHubClient.sec_user_id},
    )


def test_creator_preview_reuses_same_request_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.creator.service.TikHubClient", FakeTikHubClient)
    service = CreatorService(
        settings=Settings(app_data_dir=tmp_path, tikhub_api_key="key"),
        cache=CreatorPreviewCache(ttl_seconds=3600),
    )

    request = CreatorPreviewRequest(input="https://xhslink.com/m/example", max_pages=2, max_items=20)
    first = service.preview(request)
    calls_after_first = len(service.client.calls)  # type: ignore[attr-defined]
    second = service.preview(request)

    assert second.preview_id == first.preview_id
    assert len(service.client.calls) == calls_after_first  # type: ignore[attr-defined]


def test_creator_submit_creates_jobs_and_skips_invalid_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.creator.service.TikHubClient", FakeTikHubClient)
    cache = CreatorPreviewCache(ttl_seconds=3600)
    service = CreatorService(settings=Settings(app_data_dir=tmp_path, tikhub_api_key="key"), cache=cache)
    preview = service.preview(
        CreatorPreviewRequest(input="https://xhslink.com/m/example")
    )
    submission = RecordingSubmission()

    result = service.submit(
        CreatorSubmitRequest(
            preview_id=preview.preview_id,
            selected_item_ids=[
                "xiaohongshu:note_video_1",
                "xiaohongshu:note_video_1",
                "xiaohongshu:note_normal_1",
                "missing",
            ],
            options=JobOptions(llm_polish=False, summary=False),
        ),
        submission,  # type: ignore[arg-type]
    )

    assert [item.job_id for item in result.created] == ["job_1"]
    assert [item.reason for item in result.skipped] == [
        "duplicate_selection",
        "item_not_found",
        "item_not_found",
    ]
    assert submission.created[0]["source_type"] == "url"
    assert submission.created[0]["source_value"] == "https://www.xiaohongshu.com/explore/note_video_1"
    assert submission.created[0]["metadata"]["creator_import"]["work_id"] == "note_video_1"


def _note(note_id: str, note_type: str, title: str) -> dict[str, Any]:
    return {
        "id": note_id,
        "type": note_type,
        "display_title": title,
        "likes": 10,
        "comments_count": 2,
        "collected_count": 3,
        "create_time": 1_780_000_000,
        "cursor": note_id,
        "cover": [{"url": "https://img.example.com/cover.jpg"}],
    }


def _aweme(aweme_id: str, title: str) -> dict[str, Any]:
    return {
        "aweme_id": aweme_id,
        "desc": title,
        "create_time": 1_780_000_000,
        "video": {"duration": 1234},
        "statistics": {
            "digg_count": 10,
            "comment_count": 2,
            "collect_count": 3,
            "share_count": 4,
        },
    }
