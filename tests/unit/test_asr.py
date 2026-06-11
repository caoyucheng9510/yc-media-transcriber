from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.asr.funasr_engine import (
    FunASRTranscriber,
    _funasr_millis_to_seconds,
    _parse_funasr_output,
)
from app.asr.mock import MockTranscriber
from app.config import Settings
from app.errors import AppError
from app.schemas import JobOptions


def test_mock_transcriber_returns_segment(sample_wav: Path, tmp_path: Path) -> None:
    settings = Settings(app_data_dir=tmp_path, asr_engine="mock", asr_mock_text="hello")
    segments = MockTranscriber(settings).transcribe(sample_wav, JobOptions(speaker_diarization=True))
    assert segments[0].text == "hello"
    assert segments[0].speaker == "Speaker1"


def test_funasr_transcriber_uses_cache_dir(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class FakeAutoModel:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=FakeAutoModel))
    monkeypatch.delenv("MODELSCOPE_CACHE", raising=False)

    settings = Settings(
        app_data_dir=tmp_path,
        asr_model_dir=tmp_path / "models",
        modelscope_cache_dir=tmp_path,
    )
    transcriber = FunASRTranscriber(settings)
    model = transcriber._load_model(speaker_diarization=False)

    assert isinstance(model, FakeAutoModel)
    assert calls[0]["model"] == "paraformer-zh"
    assert calls[0]["model_revision"] == "v2.0.4"
    assert calls[0]["vad_model"] == "fsmn-vad"
    assert calls[0]["vad_model_revision"] == "v2.0.4"
    assert calls[0]["punc_model"] == "ct-punc-c"
    assert calls[0]["punc_model_revision"] == "v2.0.4"
    assert calls[0]["cache_dir"] == str(tmp_path / "models")
    assert os.environ["MODELSCOPE_CACHE"] == str(tmp_path)
    assert "model_path" not in calls[0]
    assert "spk_model" not in calls[0]


def test_funasr_transcriber_adds_speaker_model_when_enabled(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class FakeAutoModel:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=FakeAutoModel))

    transcriber = FunASRTranscriber(Settings(app_data_dir=tmp_path, asr_model_dir=tmp_path / "models"))
    transcriber._load_model(speaker_diarization=True)

    assert calls[0]["spk_model"] == "cam++"
    assert calls[0]["spk_model_revision"] == "v2.0.2"


def test_funasr_transcriber_uses_settings_language(monkeypatch, sample_wav: Path, tmp_path: Path) -> None:
    calls = []

    class FakeModel:
        def generate(self, **kwargs):
            calls.append(kwargs)
            return [{"text": "hello"}]

    settings = Settings(
        app_data_dir=tmp_path,
        asr_model_dir=tmp_path / "models",
        asr_language="en",
    )
    transcriber = FunASRTranscriber(settings)
    monkeypatch.setattr(transcriber, "_load_model", lambda speaker_diarization: FakeModel())

    segments = transcriber.transcribe(sample_wav, JobOptions())

    assert segments[0].text == "hello"
    assert calls[0]["language"] == "en"


def test_funasr_model_load_error_is_reported_as_transcribing(monkeypatch, sample_wav: Path, tmp_path: Path) -> None:
    transcriber = FunASRTranscriber(Settings(app_data_dir=tmp_path, asr_model_dir=tmp_path / "models"))

    def fail_load_model(speaker_diarization: bool):
        raise RuntimeError("model registry dumped a long internal error")

    monkeypatch.setattr(transcriber, "_load_model", fail_load_model)

    with pytest.raises(AppError) as exc_info:
        transcriber.transcribe(sample_wav, JobOptions())

    assert exc_info.value.code == "asr_failed"
    assert exc_info.value.stage == "transcribing"
    assert exc_info.value.message == "FunASR 转录失败，请检查模型配置和本地依赖。"


def test_funasr_sentence_info_timestamps_are_milliseconds() -> None:
    segments = _parse_funasr_output(
        [
            {
                "sentence_info": [
                    {"start": 130, "end": 355, "speaker": "Speaker1", "text": "你好"},
                    {"start": 15790, "end": 16710, "speaker": "Speaker1", "text": "继续"},
                ]
            }
        ]
    )

    assert segments[0].start == 0.13
    assert segments[0].end == 0.355
    assert segments[1].start == 15.79
    assert segments[1].end == 16.71


def test_funasr_segments_timestamps_are_milliseconds() -> None:
    segments = _parse_funasr_output(
        [
            {
                "segments": [
                    {"st": 130, "ed": 355, "spk": "Speaker1", "text": "你好"},
                ]
            }
        ]
    )

    assert segments[0].start == 0.13
    assert segments[0].end == 0.355


def test_funasr_invalid_timestamp_returns_zero() -> None:
    assert _funasr_millis_to_seconds("bad") == 0.0
    assert _funasr_millis_to_seconds(None) == 0.0
    assert _funasr_millis_to_seconds(-1) == 0.0
