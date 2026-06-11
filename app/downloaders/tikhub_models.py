from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TikHubMediaInfo:
    platform: str
    media_id: str | None
    title: str
    author: str | None = None
    description: str = ""
    source_url: str = ""
    display_url: str = ""
    provider: str = "tikhub"
    download_urls: list[str] = field(default_factory=list)
    file_ext: str | None = None
    duration: int | float | None = None
    published_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
