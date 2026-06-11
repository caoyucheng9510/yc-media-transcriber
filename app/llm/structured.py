from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class KeyInfo(BaseModel):
    names: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    technical_terms: list[str] = Field(default_factory=list)
    brands: list[str] = Field(default_factory=list)
    abbreviations: list[str] = Field(default_factory=list)
    foreign_terms: list[str] = Field(default_factory=list)
    other_entities: list[str] = Field(default_factory=list)


class SpeakerInferencePayload(BaseModel):
    speaker_mapping: dict[str, str] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)
    source_labels: list[str] = Field(default_factory=list)
    applied_mapping: dict[str, str] = Field(default_factory=dict)


class DialogItem(BaseModel):
    start: float = 0.0
    end: float = 0.0
    speaker_label: str
    speaker_name: str | None = None
    text: str
    original_text: str | None = None


class CalibrationChunkStats(BaseModel):
    index: int
    status: Literal["success", "fallback", "failed"]
    attempts: int = 0
    input_count: int = 0
    output_count: int = 0
    warning_codes: list[str] = Field(default_factory=list)
    validation_score: float | None = None


class CalibrationDetail(BaseModel):
    mode: Literal["none", "plain_text", "structured_dialog"] = "none"
    total_chunks: int = 0
    success_count: int = 0
    fallback_count: int = 0
    failed_count: int = 0
    chunks: list[CalibrationChunkStats] = Field(default_factory=list)


class ValidationDetail(BaseModel):
    enabled: bool = False
    validated_chunks: int = 0
    failed_chunks: int = 0
    warning_codes: list[str] = Field(default_factory=list)


class LLMDetail(BaseModel):
    enabled: bool = False
    prompt_version: str | None = None
    key_info: KeyInfo = Field(default_factory=KeyInfo)
    speaker_inference: SpeakerInferencePayload = Field(default_factory=SpeakerInferencePayload)
    calibration: CalibrationDetail = Field(default_factory=CalibrationDetail)
    validation: ValidationDetail = Field(default_factory=ValidationDetail)
    models: dict[str, str] = Field(default_factory=dict)
