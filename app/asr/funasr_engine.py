from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from app.asr.base import Transcriber
from app.config import Settings
from app.errors import AppError
from app.media.ffmpeg import probe_media
from app.schemas import JobOptions, Segment


logger = logging.getLogger(__name__)


class FunASRTranscriber(Transcriber):
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model: Any | None = None
        self._model_with_speaker: Any | None = None

    def _load_model(self, speaker_diarization: bool) -> Any:
        target_attr = "_model_with_speaker" if speaker_diarization else "_model"
        cached = getattr(self, target_attr)
        if cached is not None:
            return cached
        try:
            from funasr import AutoModel
        except ImportError as exc:
            raise AppError(
                "asr_failed",
                "FunASR 未安装。请安装可选依赖，或将 ASR_ENGINE 设置为 mock 仅验证流程。",
                "transcribing",
            ) from exc

        self.settings.modelscope_cache_dir.mkdir(parents=True, exist_ok=True)
        self.settings.asr_model_dir.mkdir(parents=True, exist_ok=True)
        os.environ["MODELSCOPE_CACHE"] = str(self.settings.modelscope_cache_dir)
        kwargs: dict[str, Any] = {
            "model": self.settings.asr_model,
            "model_revision": self.settings.asr_model_revision,
            "vad_model": self.settings.asr_vad_model,
            "vad_model_revision": self.settings.asr_vad_model_revision,
            "punc_model": self.settings.asr_punc_model,
            "punc_model_revision": self.settings.asr_punc_model_revision,
            "cache_dir": str(self.settings.asr_model_dir),
            "device": self.settings.asr_device,
            "disable_update": True,
            "disable_pbar": True,
        }
        if speaker_diarization:
            kwargs["spk_model"] = self.settings.asr_spk_model
            kwargs["spk_model_revision"] = self.settings.asr_spk_model_revision
        model = AutoModel(**kwargs)
        setattr(self, target_attr, model)
        return model

    def transcribe(self, audio_path: Path, options: JobOptions) -> list[Segment]:
        try:
            model = self._load_model(options.speaker_diarization)
            output = model.generate(
                input=str(audio_path),
                language=self.settings.asr_language,
                batch_size_s=300,
            )
        except AppError:
            raise
        except Exception as exc:
            logger.exception("FunASR transcription failed")
            raise AppError("asr_failed", "FunASR 转录失败，请检查模型配置和本地依赖。", "transcribing") from exc
        segments = _parse_funasr_output(output)
        if segments:
            return segments
        duration = max(1.0, probe_media(audio_path).duration)
        text = _extract_text(output).strip()
        if not text:
            raise AppError("asr_failed", "FunASR 未返回有效转录文本。", "transcribing")
        return [Segment(start=0.0, end=round(duration, 2), speaker=None, text=text)]


def _extract_text(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return "\n".join(_extract_text(item) for item in output)
    if isinstance(output, dict):
        if "text" in output:
            return str(output["text"])
        return "\n".join(_extract_text(value) for value in output.values())
    return ""


def _parse_funasr_output(output: Any) -> list[Segment]:
    candidates = output if isinstance(output, list) else [output]
    segments: list[Segment] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        sentence_info = item.get("sentence_info") or item.get("segments") or []
        for sentence in sentence_info:
            if not isinstance(sentence, dict):
                continue
            text = str(sentence.get("text") or "").strip()
            if not text:
                continue
            start = _funasr_millis_to_seconds(_first_present(sentence, "start", "st", default=0))
            end = _funasr_millis_to_seconds(_first_present(sentence, "end", "ed", default=start))
            speaker = sentence.get("speaker") or sentence.get("spk")
            segments.append(
                Segment(
                    start=start,
                    end=max(end, start),
                    speaker=str(speaker) if speaker is not None else None,
                    text=text,
                )
            )
    return segments


def _first_present(payload: dict[str, Any], *keys: str, default: Any) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def _funasr_millis_to_seconds(value: Any) -> float:
    # FunASR sentence_info and segments timestamps are millisecond offsets.
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if numeric < 0:
        return 0.0
    return round(numeric / 1000.0, 3)
