from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.errors import AppError
from app.llm.base import LLMClient
from app.llm.prompts import QUALITY_VALIDATION_SYSTEM_PROMPT, build_quality_validation_user_prompt
from app.llm.structured import DialogItem
from app.llm.utils import chat_json, safe_timeout


@dataclass
class LLMQualityReport:
    warnings: list[str] = field(default_factory=list)


@dataclass
class LLMValidationResult:
    score: float | None = None
    accepted: bool = True
    warnings: list[str] = field(default_factory=list)


class LLMQualityChecker:
    def __init__(self, *, min_ratio: float, max_ratio: float):
        self.min_ratio = min_ratio
        self.max_ratio = max_ratio

    def check(
        self,
        *,
        raw_transcript: str,
        polished_text: str,
        expected_chunks: int,
        produced_chunks: int,
        input_speakers: set[str],
        speaker_mapping: dict[str, str],
    ) -> LLMQualityReport:
        if not polished_text.strip():
            raise AppError("llm_failed", "LLM 校对输出为空。", "llm_processing")

        warnings: list[str] = []
        input_len = len(raw_transcript.strip())
        output_len = len(polished_text.strip())
        if input_len >= 20 and output_len > 0:
            ratio = output_len / input_len
            if ratio < self.min_ratio:
                warnings.append("polished_text_too_short")
            if ratio > self.max_ratio:
                warnings.append("polished_text_too_long")

        if expected_chunks != produced_chunks:
            warnings.append("llm_chunk_count_mismatch")

        if input_speakers:
            speaker_tokens = set(input_speakers)
            speaker_tokens.update(value for value in speaker_mapping.values() if value)
            if not any(token in polished_text for token in speaker_tokens):
                warnings.append("speaker_labels_lost")

        return LLMQualityReport(warnings=warnings)

    def validate_dialog_payload(
        self,
        *,
        original_items: list[DialogItem],
        payload: object,
    ) -> list[str]:
        if not isinstance(payload, list):
            return ["dialog_output_invalid"]
        if len(payload) != len(original_items):
            return ["dialog_count_mismatch"]
        warnings: list[str] = []
        for index, (original, item) in enumerate(zip(original_items, payload)):
            if not isinstance(item, dict):
                warnings.append("dialog_output_invalid")
                break
            if str(item.get("speaker_label") or "") != original.speaker_label:
                warnings.append("speaker_label_mismatch")
                break
            if not str(item.get("text") or "").strip():
                warnings.append("dialog_text_empty")
                break
        return warnings

    def validate_text_ratio(self, *, original_text: str, polished_text: str) -> list[str]:
        if not polished_text.strip():
            return ["polished_text_empty"]
        input_len = len(original_text.strip())
        output_len = len(polished_text.strip())
        if input_len < 20 or output_len <= 0:
            return []
        ratio = output_len / input_len
        warnings: list[str] = []
        if ratio < self.min_ratio:
            warnings.append("polished_text_too_short")
        if ratio > self.max_ratio:
            warnings.append("polished_text_too_long")
        return warnings


class LLMQualityValidator:
    def __init__(self, settings: Settings, client: LLMClient):
        self.settings = settings
        self.client = client

    def validate(
        self,
        *,
        original_text: str,
        polished_text: str,
        mode: str,
        metrics: Any | None = None,
        deadline: float | None = None,
        monotonic_now: float,
    ) -> LLMValidationResult:
        if not self.settings.llm_validation_enabled:
            return LLMValidationResult()
        try:
            data = chat_json(
                self.client,
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": QUALITY_VALIDATION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": build_quality_validation_user_prompt(
                            original_text=original_text,
                            polished_text=polished_text,
                            mode=mode,
                        ),
                    },
                ],
                purpose="quality_validation",
                metrics=metrics,
                timeout=safe_timeout(
                    self.settings.llm_chat_timeout_seconds,
                    deadline,
                    monotonic_now,
                ),
            )
            score = _weighted_score(data)
            return LLMValidationResult(
                score=score,
                accepted=score >= 0.65,
                warnings=[] if score >= 0.65 else ["quality_validation_low_score"],
            )
        except Exception:
            return LLMValidationResult(
                score=None,
                accepted=True,
                warnings=["quality_validation_failed"],
            )


def _weighted_score(data: dict[str, Any]) -> float:
    weights = {
        "accuracy": 0.4,
        "completeness": 0.3,
        "fluency": 0.2,
        "format": 0.1,
    }
    total = 0.0
    for key, weight in weights.items():
        try:
            value = float(data.get(key, 0.0))
        except (TypeError, ValueError):
            value = 0.0
        total += max(0.0, min(1.0, value)) * weight
    return round(total, 4)
