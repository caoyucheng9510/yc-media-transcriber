from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.errors import AppError
from app.llm.base import LLMClient
from app.llm.prompts import (
    PLAIN_CALIBRATION_SYSTEM_PROMPT,
    STRUCTURED_CALIBRATION_SYSTEM_PROMPT,
    build_plain_calibration_user_prompt,
    build_structured_calibration_user_prompt,
)
from app.llm.quality import LLMQualityChecker, LLMQualityValidator
from app.llm.segmenter import LLMChunk, LLMDialogChunk, LLMSegmenter
from app.llm.structured import (
    CalibrationChunkStats,
    CalibrationDetail,
    DialogItem,
    KeyInfo,
    ValidationDetail,
)
from app.llm.utils import chat_json, chat_text, safe_timeout
from app.schemas import Segment, Term


DEFAULT_CALIBRATION_MAX_WORKERS = 3


@dataclass
class CalibrationResult:
    polished_text: str
    structured_transcript: list[DialogItem] = field(default_factory=list)
    detail: CalibrationDetail = field(default_factory=CalibrationDetail)
    validation: ValidationDetail = field(default_factory=ValidationDetail)
    warnings: list[str] = field(default_factory=list)


class CalibrationProcessor:
    def __init__(self, settings: Settings, client: LLMClient, quality: LLMQualityChecker):
        self.settings = settings
        self.client = client
        self.quality = quality
        self.validator = LLMQualityValidator(settings, client)
        self.segmenter = LLMSegmenter(
            threshold=settings.llm_segment_enable_threshold,
            segment_size=settings.llm_segment_size,
            overlap=settings.llm_segment_overlap,
            dialog_min_chars=settings.llm_dialog_min_chunk_chars,
            dialog_preferred_chars=settings.llm_dialog_preferred_chunk_chars,
            dialog_max_chars=settings.llm_dialog_max_chunk_chars,
        )

    def calibrate(
        self,
        *,
        raw_transcript: str,
        segments: list[Segment],
        speaker_mapping: dict[str, str],
        terms: list[Term],
        key_info: KeyInfo,
        metadata: dict,
        metrics: Any | None = None,
    ) -> CalibrationResult:
        if any(segment.speaker for segment in segments):
            dialog_chunks = self.segmenter.build_dialog_chunks(segments, speaker_mapping)
            if dialog_chunks:
                return self._calibrate_dialog_chunks(
                    dialog_chunks,
                    terms=terms,
                    key_info=key_info,
                    metadata=metadata,
                    speaker_mapping=speaker_mapping,
                    metrics=metrics,
                )
        plain_chunks = self.segmenter.build_plain_text_chunks(raw_transcript)
        return self._calibrate_plain_chunks(
            plain_chunks,
            terms=terms,
            key_info=key_info,
            metadata=metadata,
            speaker_mapping=speaker_mapping,
            metrics=metrics,
        )

    def _calibrate_plain_chunks(
        self,
        chunks: list[LLMChunk],
        *,
        terms: list[Term],
        key_info: KeyInfo,
        metadata: dict,
        speaker_mapping: dict[str, str],
        metrics: Any | None,
    ) -> CalibrationResult:
        if not chunks:
            return CalibrationResult(
                polished_text="",
                detail=CalibrationDetail(mode="plain_text"),
                warnings=["calibration_input_empty"],
            )
        max_workers = min(DEFAULT_CALIBRATION_MAX_WORKERS, len(chunks))
        results: dict[int, tuple[str, CalibrationChunkStats]] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._calibrate_plain_chunk,
                    chunk,
                    terms,
                    key_info,
                    metadata,
                    speaker_mapping,
                    metrics,
                ): chunk.index
                for chunk in chunks
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception:
                    chunk = chunks[index]
                    results[index] = (
                        chunk.text,
                        CalibrationChunkStats(
                            index=index,
                            status="fallback",
                            attempts=0,
                            input_count=len(chunk.text),
                            output_count=len(chunk.text),
                            warning_codes=["calibration_chunk_failed"],
                        ),
                    )

        ordered = [results[index] for index in sorted(results)]
        outputs = [text.strip() for text, _stats in ordered if text.strip()]
        stats = [chunk_stats for _text, chunk_stats in ordered]
        detail = _calibration_detail("plain_text", stats)
        warnings = _collect_warning_codes(stats)
        return CalibrationResult(
            polished_text="\n\n".join(outputs),
            detail=detail,
            validation=_validation_detail(self.settings.llm_validation_enabled, stats),
            warnings=warnings,
        )

    def _calibrate_plain_chunk(
        self,
        chunk: LLMChunk,
        terms: list[Term],
        key_info: KeyInfo,
        metadata: dict,
        speaker_mapping: dict[str, str],
        metrics: Any | None,
    ) -> tuple[str, CalibrationChunkStats]:
        deadline = time.monotonic() + self.settings.llm_chunk_time_budget_seconds
        warnings: list[str] = []
        best_text = ""
        validation_score: float | None = None
        attempts = 0
        for attempt in range(1, self.settings.llm_calibration_max_retries + 1):
            attempts = attempt
            try:
                purpose = "calibration" if attempt == 1 else "calibration_retry"
                now = time.monotonic()
                text = chat_text(
                    self.client,
                    model=self.settings.llm_model,
                    messages=[
                        {"role": "system", "content": PLAIN_CALIBRATION_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": build_plain_calibration_user_prompt(
                                text=chunk.text,
                                metadata=metadata,
                                terms=terms,
                                key_info=key_info,
                                speaker_mapping=speaker_mapping,
                            ),
                        },
                    ],
                    purpose=purpose,
                    metrics=metrics,
                    timeout=safe_timeout(
                        self.settings.llm_chat_timeout_seconds,
                        deadline,
                        now,
                    ),
                ).strip()
            except AppError as exc:
                warning_code = _calibration_app_error_warning(exc)
                if warning_code not in warnings:
                    warnings.append(warning_code)
                if _should_retry_calibration_app_error(
                    exc,
                    attempt=attempt,
                    max_attempts=self.settings.llm_calibration_max_retries,
                ):
                    continue
                break
            except Exception:
                warnings.append("calibration_chunk_failed")
                continue
            if len(text) > len(best_text):
                best_text = text
            local_warnings = self.quality.validate_text_ratio(
                original_text=chunk.text,
                polished_text=text,
            )
            if "polished_text_empty" in local_warnings or "polished_text_too_short" in local_warnings:
                warnings.extend(code for code in local_warnings if code not in warnings)
                continue
            validation = self.validator.validate(
                original_text=chunk.text,
                polished_text=text,
                mode="plain_text",
                metrics=metrics,
                deadline=deadline,
                monotonic_now=time.monotonic(),
            )
            validation_score = validation.score
            warnings.extend(code for code in validation.warnings if code not in warnings)
            if validation.accepted:
                return (
                    text,
                    CalibrationChunkStats(
                        index=chunk.index,
                        status="success",
                        attempts=attempts,
                        input_count=len(chunk.text),
                        output_count=len(text),
                        warning_codes=warnings,
                        validation_score=validation_score,
                    ),
                )
        fallback = best_text.strip() or chunk.text
        status = "fallback"
        if not fallback.strip():
            status = "failed"
        if not warnings:
            warnings.append("calibration_fallback")
        return (
            fallback,
            CalibrationChunkStats(
                index=chunk.index,
                status=status,
                attempts=attempts,
                input_count=len(chunk.text),
                output_count=len(fallback),
                warning_codes=warnings,
                validation_score=validation_score,
            ),
        )

    def _calibrate_dialog_chunks(
        self,
        chunks: list[LLMDialogChunk],
        *,
        terms: list[Term],
        key_info: KeyInfo,
        metadata: dict,
        speaker_mapping: dict[str, str],
        metrics: Any | None,
    ) -> CalibrationResult:
        max_workers = min(DEFAULT_CALIBRATION_MAX_WORKERS, len(chunks))
        results: dict[int, tuple[list[DialogItem], CalibrationChunkStats]] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._calibrate_dialog_chunk,
                    chunk,
                    terms,
                    key_info,
                    metadata,
                    speaker_mapping,
                    metrics,
                ): chunk.index
                for chunk in chunks
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception:
                    chunk = chunks[index]
                    fallback_items = _fallback_dialog_items(chunk.items)
                    results[index] = (
                        fallback_items,
                        CalibrationChunkStats(
                            index=index,
                            status="fallback",
                            attempts=0,
                            input_count=len(chunk.items),
                            output_count=len(fallback_items),
                            warning_codes=["calibration_chunk_failed"],
                        ),
                    )
        ordered = [results[index] for index in sorted(results)]
        items = [item for item_list, _stats in ordered for item in item_list]
        stats = [chunk_stats for _items, chunk_stats in ordered]
        detail = _calibration_detail("structured_dialog", stats)
        return CalibrationResult(
            polished_text=format_dialog_items(items),
            structured_transcript=items,
            detail=detail,
            validation=_validation_detail(self.settings.llm_validation_enabled, stats),
            warnings=_collect_warning_codes(stats),
        )

    def _calibrate_dialog_chunk(
        self,
        chunk: LLMDialogChunk,
        terms: list[Term],
        key_info: KeyInfo,
        metadata: dict,
        speaker_mapping: dict[str, str],
        metrics: Any | None,
    ) -> tuple[list[DialogItem], CalibrationChunkStats]:
        if chunk.fallback_only:
            items = _fallback_dialog_items(chunk.items)
            return (
                items,
                CalibrationChunkStats(
                    index=chunk.index,
                    status="fallback",
                    attempts=0,
                    input_count=len(chunk.items),
                    output_count=len(items),
                    warning_codes=list(chunk.warning_codes),
                ),
            )
        deadline = time.monotonic() + self.settings.llm_chunk_time_budget_seconds
        warnings: list[str] = []
        attempts = 0
        validation_score: float | None = None
        for attempt in range(1, self.settings.llm_calibration_max_retries + 1):
            attempts = attempt
            try:
                purpose = "calibration" if attempt == 1 else "calibration_retry"
                data = chat_json(
                    self.client,
                    model=self.settings.llm_model,
                    messages=[
                        {"role": "system", "content": STRUCTURED_CALIBRATION_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": build_structured_calibration_user_prompt(
                                dialogs=chunk.items,
                                metadata=metadata,
                                terms=terms,
                                key_info=key_info,
                                speaker_mapping=speaker_mapping,
                            ),
                        },
                    ],
                    purpose=purpose,
                    metrics=metrics,
                    timeout=safe_timeout(
                        self.settings.llm_chat_timeout_seconds,
                        deadline,
                        time.monotonic(),
                    ),
                )
                dialogs = data.get("calibrated_dialogs")
                local_warnings = self.quality.validate_dialog_payload(
                    original_items=chunk.items,
                    payload=dialogs,
                )
                if local_warnings:
                    warnings.extend(code for code in local_warnings if code not in warnings)
                    continue
                assert isinstance(dialogs, list)
                items = _merge_dialog_output(chunk.items, dialogs)
                polished_text = format_dialog_items(items)
                validation = self.validator.validate(
                    original_text=format_dialog_items(chunk.items),
                    polished_text=polished_text,
                    mode="structured_dialog",
                    metrics=metrics,
                    deadline=deadline,
                    monotonic_now=time.monotonic(),
                )
                validation_score = validation.score
                warnings.extend(code for code in validation.warnings if code not in warnings)
                if not validation.accepted:
                    continue
                return (
                    items,
                    CalibrationChunkStats(
                        index=chunk.index,
                        status="success",
                        attempts=attempts,
                        input_count=len(chunk.items),
                        output_count=len(items),
                        warning_codes=warnings,
                        validation_score=validation_score,
                    ),
                )
            except AppError as exc:
                warning_code = _calibration_app_error_warning(exc)
                if warning_code not in warnings:
                    warnings.append(warning_code)
                if _should_retry_calibration_app_error(
                    exc,
                    attempt=attempt,
                    max_attempts=self.settings.llm_calibration_max_retries,
                ):
                    continue
                break
            except Exception:
                warnings.append("calibration_chunk_failed")
                continue
        fallback_items = _fallback_dialog_items(chunk.items)
        if not warnings:
            warnings.append("calibration_fallback")
        return (
            fallback_items,
            CalibrationChunkStats(
                index=chunk.index,
                status="fallback",
                attempts=attempts,
                input_count=len(chunk.items),
                output_count=len(fallback_items),
                warning_codes=warnings,
                validation_score=validation_score,
            ),
        )


def format_dialog_items(items: list[DialogItem]) -> str:
    lines = []
    for item in items:
        speaker = item.speaker_name or item.speaker_label
        text = item.text.strip()
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def _merge_dialog_output(original_items: list[DialogItem], output: list[dict[str, Any]]) -> list[DialogItem]:
    items: list[DialogItem] = []
    for original, value in zip(original_items, output):
        text = str(value.get("text") or "").strip()
        items.append(
            DialogItem(
                start=original.start,
                end=original.end,
                speaker_label=original.speaker_label,
                speaker_name=original.speaker_name,
                text=text,
                original_text=original.original_text or original.text,
            )
        )
    return items


def _fallback_dialog_items(original_items: list[DialogItem]) -> list[DialogItem]:
    return [
        DialogItem(
            start=item.start,
            end=item.end,
            speaker_label=item.speaker_label,
            speaker_name=item.speaker_name,
            text=item.original_text or item.text,
            original_text=item.original_text or item.text,
        )
        for item in original_items
    ]


def _calibration_detail(mode: str, stats: list[CalibrationChunkStats]) -> CalibrationDetail:
    return CalibrationDetail(
        mode=mode,
        total_chunks=len(stats),
        success_count=sum(1 for item in stats if item.status == "success"),
        fallback_count=sum(1 for item in stats if item.status == "fallback"),
        failed_count=sum(1 for item in stats if item.status == "failed"),
        chunks=stats,
    )


def _validation_detail(enabled: bool, stats: list[CalibrationChunkStats]) -> ValidationDetail:
    warnings = sorted({code for stat in stats for code in stat.warning_codes if code.startswith("quality_validation")})
    return ValidationDetail(
        enabled=enabled,
        validated_chunks=sum(1 for item in stats if item.validation_score is not None),
        failed_chunks=sum(1 for item in stats if any(code.startswith("quality_validation") for code in item.warning_codes)),
        warning_codes=warnings,
    )


def _collect_warning_codes(stats: list[CalibrationChunkStats]) -> list[str]:
    seen: set[str] = set()
    warnings: list[str] = []
    for stat in stats:
        for code in stat.warning_codes:
            if code not in seen:
                seen.add(code)
                warnings.append(code)
    return warnings


def _calibration_app_error_warning(exc: AppError) -> str:
    if "budget" in exc.message.lower():
        return "chunk_time_budget_exhausted"
    return "calibration_chunk_failed"


def _should_retry_calibration_app_error(exc: AppError, *, attempt: int, max_attempts: int) -> bool:
    if attempt >= max_attempts:
        return False
    if _calibration_app_error_warning(exc) == "chunk_time_budget_exhausted":
        return False
    return exc.code == "llm_failed"
