from __future__ import annotations

from app.asr.base import Transcriber
from app.asr.funasr_engine import FunASRTranscriber
from app.asr.mock import MockTranscriber
from app.config import Settings


def create_transcriber(settings: Settings) -> Transcriber:
    if settings.asr_engine == "mock":
        return MockTranscriber(settings)
    if settings.asr_engine == "funasr_paraformer":
        return FunASRTranscriber(settings)
    return FunASRTranscriber(settings)
