from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.schemas import JobOptions, Segment


class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, audio_path: Path, options: JobOptions) -> list[Segment]:
        raise NotImplementedError
