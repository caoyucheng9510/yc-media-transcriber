from __future__ import annotations

from pathlib import Path

from app.asr.base import Transcriber
from app.config import Settings
from app.media.ffmpeg import probe_media
from app.schemas import JobOptions, Segment


class MockTranscriber(Transcriber):
    def __init__(self, settings: Settings):
        self.settings = settings

    def transcribe(self, audio_path: Path, options: JobOptions) -> list[Segment]:
        duration = 1.0
        try:
            duration = max(1.0, probe_media(audio_path).duration)
        except Exception:
            pass
        speaker = "Speaker1" if options.speaker_diarization else None
        return [
            Segment(
                start=0.0,
                end=round(duration, 2),
                speaker=speaker,
                text=self.settings.asr_mock_text,
            )
        ]
