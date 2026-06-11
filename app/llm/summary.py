from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.llm.base import LLMClient
from app.llm.prompts import (
    SUMMARY_MULTI_SPEAKER_SYSTEM_PROMPT,
    SUMMARY_SINGLE_SPEAKER_SYSTEM_PROMPT,
    build_summary_chunk_user_prompt,
    build_summary_user_prompt,
)
from app.llm.segmenter import LLMSegmenter
from app.llm.utils import chat_text


@dataclass
class SummaryResult:
    summary: str | None = None
    key_points: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SummaryChunkResult:
    text: str
    warnings: list[str] = field(default_factory=list)


class SummaryProcessor:
    def __init__(self, settings: Settings, client: LLMClient):
        self.settings = settings
        self.client = client
        self.segmenter = LLMSegmenter(
            threshold=settings.llm_segment_enable_threshold,
            segment_size=max(1, min(settings.llm_segment_size, settings.llm_summary_chunk_threshold)),
            overlap=0,
        )

    def summarize(
        self,
        *,
        text: str,
        metadata: dict,
        speaker_mapping: dict[str, str],
        has_multiple_speakers: bool,
        metrics: Any | None = None,
    ) -> SummaryResult:
        source = text.strip()
        if len(source) < self.settings.llm_summary_min_chars:
            return SummaryResult(warnings=["summary_skipped_short_text"])
        summary_source = source
        chunk_warnings: list[str] = []
        used_chunk_summaries = False
        if len(source) > self.settings.llm_summary_chunk_threshold:
            chunk_result = self._summarize_chunks(source, metadata, metrics)
            chunk_warnings = chunk_result.warnings
            summary_source = chunk_result.text.strip()
            used_chunk_summaries = bool(summary_source)
            if not used_chunk_summaries:
                return SummaryResult(warnings=chunk_warnings)

        try:
            summary = chat_text(
                self.client,
                model=self.settings.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            SUMMARY_MULTI_SPEAKER_SYSTEM_PROMPT
                            if has_multiple_speakers
                            else SUMMARY_SINGLE_SPEAKER_SYSTEM_PROMPT
                        ),
                    },
                    {
                        "role": "user",
                        "content": build_summary_user_prompt(
                            text=summary_source,
                            metadata=metadata,
                            speaker_mapping=speaker_mapping,
                        ),
                    },
                ],
                purpose="summary",
                metrics=metrics,
                timeout=self.settings.llm_chat_timeout_seconds,
            ).strip()
        except Exception:
            if used_chunk_summaries:
                warnings = _dedupe(
                    [
                        *chunk_warnings,
                        "summary_final_failed",
                        "summary_fallback_to_chunk_summaries",
                    ]
                )
                return SummaryResult(
                    summary=summary_source,
                    key_points=_extract_key_points(summary_source),
                    warnings=warnings,
                )
            return SummaryResult(warnings=["summary_failed"])
        if not summary:
            if used_chunk_summaries:
                warnings = _dedupe(
                    [
                        *chunk_warnings,
                        "summary_final_empty",
                        "summary_fallback_to_chunk_summaries",
                    ]
                )
                return SummaryResult(
                    summary=summary_source,
                    key_points=_extract_key_points(summary_source),
                    warnings=warnings,
                )
            return SummaryResult(warnings=["summary_failed"])
        return SummaryResult(
            summary=summary,
            key_points=_extract_key_points(summary),
            warnings=_dedupe(chunk_warnings),
        )

    def _summarize_chunks(self, text: str, metadata: dict, metrics: Any | None) -> SummaryChunkResult:
        chunks = self.segmenter.build_plain_text_chunks(text)
        summaries: list[str] = []
        warnings: list[str] = []
        for chunk in chunks:
            try:
                content = chat_text(
                    self.client,
                    model=self.settings.llm_model,
                    messages=[
                        {"role": "system", "content": SUMMARY_SINGLE_SPEAKER_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": build_summary_chunk_user_prompt(text=chunk.text, metadata=metadata),
                        },
                    ],
                    purpose="summary_chunk",
                    metrics=metrics,
                    timeout=self.settings.llm_chat_timeout_seconds,
                ).strip()
            except Exception:
                warnings.append("summary_chunk_failed")
                continue
            if content:
                summaries.append(content)
            else:
                warnings.append("summary_chunk_empty")
        if not summaries:
            warnings.append("summary_failed")
            return SummaryChunkResult(text="", warnings=_dedupe(warnings))
        if warnings:
            warnings.append("summary_partial_chunks")
        return SummaryChunkResult(text="\n\n".join(summaries), warnings=_dedupe(warnings))


def _extract_key_points(summary: str) -> list[str]:
    return [
        line[1:].strip()
        for line in summary.splitlines()
        if line.strip().startswith("-") and line[1:].strip()
    ]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
