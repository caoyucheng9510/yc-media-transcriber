from __future__ import annotations


def bilibili_media_headers() -> dict[str, str]:
    return {
        "Referer": "https://www.bilibili.com",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
    }
