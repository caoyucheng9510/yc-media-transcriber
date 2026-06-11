from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.schemas import Segment
from app.source_resolver import ResolvedSource


@dataclass
class DownloadResult:
    source_path: Path | None
    metadata: dict
    source_fingerprint: str
    pretranscribed_segments: list[Segment] = field(default_factory=list)


class Downloader:
    def download(
        self,
        source: ResolvedSource,
        job_temp_dir: Path,
        options: dict,
        metrics: Any | None = None,
    ) -> DownloadResult:
        raise NotImplementedError
