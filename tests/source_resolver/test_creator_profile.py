from __future__ import annotations

import pytest

from app.source_resolver import detect_creator_profile_input


@pytest.mark.parametrize(
    ("value", "platform"),
    [
        ("https://xhslink.com/m/3NeGLNEUVHb", "xiaohongshu"),
        ("看看这个主页 https://www.xiaohongshu.com/user/profile/63fc8880000000001f0329db", "xiaohongshu"),
        ("https://www.douyin.com/user/MS4wLjABAAAAexample", "douyin"),
        ("https://www.iesdouyin.com/share/user/MS4wLjABAAAAexample", "douyin"),
    ],
)
def test_detect_creator_profile_input(value: str, platform: str) -> None:
    detected = detect_creator_profile_input(value)

    assert detected is not None
    assert detected.platform == platform


@pytest.mark.parametrize(
    "value",
    [
        "http://xhslink.com/o/35v51fVs63",
        "https://www.xiaohongshu.com/explore/69ff7ffd0000000008003ef3",
        "https://www.xiaohongshu.com/discovery/item/68f60f0000000000040230eb",
        "https://www.douyin.com/video/7123456789012345678",
        "https://www.douyin.com/note/7123456789012345678",
        "https://www.youtube.com/watch?v=EN7frwQIbKc",
    ],
)
def test_detect_creator_profile_input_ignores_single_work_links(value: str) -> None:
    assert detect_creator_profile_input(value) is None
