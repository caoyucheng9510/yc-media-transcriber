from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.config import Settings
from app.errors import AppError
from app.llm.base import LLMClient
from app.llm.prompts import SPEAKER_INFERENCE_SYSTEM_PROMPT, build_speaker_inference_user_prompt
from app.llm.segmenter import format_segments_for_llm
from app.llm.structured import SpeakerInferencePayload
from app.llm.utils import chat_json
from app.schemas import Segment, Term


@dataclass
class SpeakerInferenceResult:
    payload: SpeakerInferencePayload = field(default_factory=SpeakerInferencePayload)
    warnings: list[str] = field(default_factory=list)

    @property
    def mapping(self) -> dict[str, str]:
        return self.payload.applied_mapping


class SpeakerInferencer:
    def __init__(self, settings: Settings, client: LLMClient):
        self.settings = settings
        self.client = client

    def infer(
        self,
        *,
        metadata: dict,
        segments: list[Segment],
        transcript_preview: str,
        terms: list[Term],
        metrics: Any | None = None,
    ) -> SpeakerInferenceResult:
        speakers = sorted({segment.speaker for segment in segments if segment.speaker})
        if not speakers:
            return SpeakerInferenceResult()

        preview_segments = segments[:40]
        preview = format_segments_for_llm(preview_segments) or transcript_preview[:2000]
        preview = preview[:2000]
        try:
            data = chat_json(
                self.client,
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": SPEAKER_INFERENCE_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": build_speaker_inference_user_prompt(
                            metadata=metadata,
                            source_labels=speakers,
                            preview=preview,
                            terms=terms,
                        ),
                    },
                ],
                purpose="speaker_inference",
                metrics=metrics,
                timeout=self.settings.llm_chat_timeout_seconds,
            )
            payload = _payload_from_data(data, speakers)
        except AppError as exc:
            code = "speaker_mapping_invalid_json" if exc.code == "llm_failed" else "speaker_inference_failed"
            return SpeakerInferenceResult(warnings=[code])
        except (ValidationError, TypeError, ValueError):
            return SpeakerInferenceResult(warnings=["speaker_mapping_invalid_json"])
        return SpeakerInferenceResult(payload=payload)


def _payload_from_data(data: dict[str, Any], source_labels: list[str]) -> SpeakerInferencePayload:
    if "speaker_mapping" not in data:
        data = {
            "speaker_mapping": {
                label: value
                for label, value in data.items()
                if label in source_labels and isinstance(value, str)
            },
            "confidence": {},
            "source_labels": source_labels,
        }
    if not isinstance(data.get("speaker_mapping"), dict):
        data["speaker_mapping"] = {}
    if not isinstance(data.get("confidence"), dict):
        data["confidence"] = {}
    if not isinstance(data.get("source_labels"), list):
        data["source_labels"] = source_labels
    payload = SpeakerInferencePayload.model_validate(data)
    mapping = {
        label: str(payload.speaker_mapping.get(label) or "").strip()
        for label in source_labels
    }
    confidence = {
        label: _confidence_value(payload.confidence.get(label))
        for label in source_labels
    }
    applied = {
        label: name
        for label, name in mapping.items()
        if name and name != label and confidence.get(label, 1.0) >= 0.7
    }
    return SpeakerInferencePayload(
        speaker_mapping=mapping,
        confidence=confidence,
        source_labels=source_labels,
        applied_mapping=applied,
    )


def _confidence_value(raw: object) -> float:
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 1.0
