from __future__ import annotations

from typing import Any

from app.config import Settings
from app.errors import AppError
from app.llm.base import LLMClient
from app.llm.calibration import CalibrationProcessor
from app.llm.key_info import KeyInfoExtractor, merge_reference_terms
from app.llm.providers import create_llm_client
from app.llm.quality import LLMQualityChecker
from app.llm.speaker import SpeakerInferencer
from app.llm.structured import LLMDetail
from app.llm.summary import SummaryProcessor
from app.schemas import JobOptions, Segment
from app.terminology import TerminologyStore
from app.transcript import format_dialog_items_for_display


class LLMProcessor:
    def __init__(
        self,
        settings: Settings,
        terms: TerminologyStore,
        client: LLMClient | None = None,
    ):
        self.settings = settings
        self.terms = terms
        self.client = client or create_llm_client(settings)
        self.quality = LLMQualityChecker(
            min_ratio=settings.llm_quality_min_ratio,
            max_ratio=settings.llm_quality_max_ratio,
        )

    @property
    def available(self) -> bool:
        return self.client.available

    def process(
        self,
        *,
        metadata: dict,
        raw_transcript: str,
        options: JobOptions,
        segments: list[Segment] | None = None,
        metrics: Any | None = None,
    ) -> dict[str, object]:
        needs_llm = options.llm_polish or options.summary
        input_segments = segments or []
        if not needs_llm:
            return {
                "polished_text": raw_transcript,
                "summary": None,
                "key_points": [],
                "speaker_mapping": {},
                "quality_warnings": [],
                "structured_transcript": [],
                "llm_detail": {"enabled": False},
            }
        if not self.available:
            raise AppError(
                "llm_provider_not_configured",
                self.client.missing_configuration_reason
                or "已启用 LLM 校对或总结，但未配置 LLM provider。",
                "llm_processing",
            )

        quality_warnings: list[str] = []
        models: dict[str, str] = {"model": self.settings.llm_model}
        matched_terms = self.terms.match_terms(
            title=str(metadata.get("title") or ""),
            description=str(metadata.get("description") or ""),
            transcript_preview=raw_transcript[:2000],
        )

        key_info_result = KeyInfoExtractor(self.settings, self.client).extract(
            metadata=metadata,
            metrics=metrics,
        )
        key_info = key_info_result.key_info
        quality_warnings.extend(key_info_result.warnings)
        reference_terms = merge_reference_terms(key_info, matched_terms)

        speaker_result = SpeakerInferencer(self.settings, self.client).infer(
            metadata=metadata,
            segments=input_segments,
            transcript_preview=raw_transcript,
            terms=reference_terms,
            metrics=metrics,
        )
        speaker_mapping = speaker_result.mapping
        speaker_payload = speaker_result.payload
        quality_warnings.extend(speaker_result.warnings)
        strict_polished_text = raw_transcript
        public_polished_text = raw_transcript
        structured_transcript: list[dict[str, object]] = []
        calibration_detail = None
        validation_detail = None
        if options.llm_polish:
            calibration = CalibrationProcessor(
                self.settings,
                self.client,
                self.quality,
            ).calibrate(
                raw_transcript=raw_transcript,
                segments=input_segments,
                speaker_mapping=speaker_mapping,
                terms=reference_terms,
                key_info=key_info,
                metadata=metadata,
                metrics=metrics,
            )
            strict_polished_text = calibration.polished_text or raw_transcript
            structured_transcript = [
                item.model_dump(mode="json")
                for item in calibration.structured_transcript
            ]
            calibration_detail = calibration.detail
            validation_detail = calibration.validation
            quality_warnings.extend(calibration.warnings)
            if not strict_polished_text.strip():
                strict_polished_text = raw_transcript
                quality_warnings.append("calibration_output_empty")

            input_speakers = {segment.speaker for segment in input_segments if segment.speaker}
            quality_warnings.extend(
                self.quality.check(
                    raw_transcript=raw_transcript,
                    polished_text=strict_polished_text,
                    expected_chunks=calibration.detail.total_chunks,
                    produced_chunks=calibration.detail.total_chunks,
                    input_speakers=input_speakers,
                    speaker_mapping=speaker_mapping,
                ).warnings
            )

        summary = None
        key_points: list[str] = []
        if options.summary:
            source_for_summary = strict_polished_text if options.llm_polish else raw_transcript
            has_multiple_speakers = len({segment.speaker for segment in input_segments if segment.speaker}) > 1
            summary_payload = SummaryProcessor(self.settings, self.client).summarize(
                text=source_for_summary,
                metadata=metadata,
                speaker_mapping=speaker_mapping,
                has_multiple_speakers=has_multiple_speakers,
                metrics=metrics,
            )
            summary = summary_payload.summary
            key_points = summary_payload.key_points
            quality_warnings.extend(summary_payload.warnings)

        if options.llm_polish:
            public_polished_text = strict_polished_text
            if calibration_detail and calibration_detail.mode == "structured_dialog" and structured_transcript:
                display_polished_text = format_dialog_items_for_display(structured_transcript)
                if display_polished_text.strip():
                    public_polished_text = display_polished_text

        llm_detail = LLMDetail(
            enabled=True,
            prompt_version=self.settings.llm_prompt_version,
            key_info=key_info,
            speaker_inference=speaker_payload,
            calibration=calibration_detail or LLMDetail().calibration,
            validation=validation_detail or LLMDetail().validation,
            models=models,
        )
        return {
            "polished_text": public_polished_text,
            "summary": summary,
            "key_points": key_points,
            "speaker_mapping": speaker_mapping,
            "quality_warnings": _dedupe(quality_warnings),
            "structured_transcript": structured_transcript,
            "llm_detail": llm_detail.model_dump(mode="json"),
        }


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
