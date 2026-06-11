from __future__ import annotations

from dataclasses import dataclass, field

from app.llm.structured import DialogItem
from app.schemas import Segment


@dataclass(frozen=True)
class LLMChunk:
    index: int
    text: str
    segments: list[Segment] = field(default_factory=list)
    start: float | None = None
    end: float | None = None
    speaker_set: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class LLMDialogChunk:
    index: int
    items: list[DialogItem]
    fallback_only: bool = False
    warning_codes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(item.text for item in self.items)


def format_segments_for_llm(
    segments: list[Segment],
    speaker_mapping: dict[str, str] | None = None,
) -> str:
    mapping = speaker_mapping or {}
    lines: list[str] = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        if segment.speaker:
            speaker_name = mapping.get(segment.speaker, "").strip()
            if speaker_name and speaker_name != segment.speaker:
                prefix = f"{speaker_name}({segment.speaker})"
            else:
                prefix = segment.speaker
            lines.append(f"{prefix}: {text}")
        else:
            lines.append(text)
    return "\n".join(lines)


class LLMSegmenter:
    def __init__(
        self,
        *,
        threshold: int,
        segment_size: int,
        overlap: int = 0,
        dialog_min_chars: int = 300,
        dialog_preferred_chars: int = 800,
        dialog_max_chars: int = 1500,
    ):
        self.threshold = max(1, threshold)
        self.segment_size = max(1, segment_size)
        self.overlap = max(0, min(overlap, self.segment_size - 1))
        self.dialog_min_chars = max(1, dialog_min_chars)
        self.dialog_max_chars = max(1, dialog_max_chars)
        self.dialog_preferred_chars = min(max(1, dialog_preferred_chars), self.dialog_max_chars)

    def build_chunks(
        self,
        *,
        raw_transcript: str,
        segments: list[Segment] | None = None,
        speaker_mapping: dict[str, str] | None = None,
    ) -> list[LLMChunk]:
        normalized_segments = [segment for segment in (segments or []) if segment.text.strip()]
        if normalized_segments:
            text = format_segments_for_llm(normalized_segments, speaker_mapping)
            if len(text) <= self.threshold:
                return [self._chunk_from_segments(0, text, normalized_segments)]
            return self._chunk_segments(normalized_segments, speaker_mapping)

        text = raw_transcript.strip()
        if not text:
            return []
        if len(text) <= self.threshold:
            return [LLMChunk(index=0, text=text)]
        return [
            LLMChunk(index=index, text=chunk_text)
            for index, chunk_text in enumerate(self._split_text(text))
        ]

    def build_plain_text_chunks(self, raw_transcript: str) -> list[LLMChunk]:
        text = raw_transcript.strip()
        if not text:
            return []
        if len(text) <= self.segment_size:
            return [LLMChunk(index=0, text=text)]
        return [
            LLMChunk(index=index, text=chunk_text)
            for index, chunk_text in enumerate(self._split_text(text))
        ]

    def build_dialog_chunks(
        self,
        segments: list[Segment],
        speaker_mapping: dict[str, str] | None = None,
    ) -> list[LLMDialogChunk]:
        mapping = speaker_mapping or {}
        chunks: list[LLMDialogChunk] = []
        current: list[DialogItem] = []
        current_chars = 0

        def flush() -> None:
            nonlocal current, current_chars
            if not current:
                return
            chunks.append(LLMDialogChunk(index=len(chunks), items=current))
            current = []
            current_chars = 0

        for segment in segments:
            text = segment.text.strip()
            speaker_label = (segment.speaker or "").strip()
            if not text or not speaker_label:
                continue
            item = DialogItem(
                start=segment.start,
                end=segment.end,
                speaker_label=speaker_label,
                speaker_name=mapping.get(speaker_label) or None,
                text=text,
                original_text=text,
            )
            item_size = len(text)
            if item_size > self.dialog_max_chars:
                flush()
                chunks.append(
                    LLMDialogChunk(
                        index=len(chunks),
                        items=[item],
                        fallback_only=True,
                        warning_codes=["dialog_segment_too_long"],
                    )
                )
                continue
            if current and current_chars + item_size > self.dialog_max_chars:
                flush()
            current.append(item)
            current_chars += item_size
            if current_chars >= self.dialog_preferred_chars:
                flush()
        flush()
        return self._merge_short_tail(chunks)

    def _chunk_segments(
        self,
        segments: list[Segment],
        speaker_mapping: dict[str, str] | None,
    ) -> list[LLMChunk]:
        chunks: list[LLMChunk] = []
        current_segments: list[Segment] = []
        current_lines: list[str] = []

        def flush() -> None:
            nonlocal current_segments, current_lines
            if not current_lines:
                return
            chunks.append(
                self._chunk_from_segments(
                    len(chunks),
                    "\n".join(current_lines).strip(),
                    current_segments,
                )
            )
            current_segments = []
            current_lines = []

        for segment in segments:
            line = format_segments_for_llm([segment], speaker_mapping).strip()
            if not line:
                continue
            if len(line) > self.segment_size:
                flush()
                for part in self._split_text(line):
                    chunks.append(
                        self._chunk_from_segments(
                            len(chunks),
                            part,
                            [segment],
                        )
                    )
                continue
            next_size = len("\n".join([*current_lines, line]))
            if current_lines and next_size > self.segment_size:
                flush()
            current_lines.append(line)
            current_segments.append(segment)
        flush()
        return chunks

    def _chunk_from_segments(
        self,
        index: int,
        text: str,
        segments: list[Segment],
    ) -> LLMChunk:
        speakers = {segment.speaker for segment in segments if segment.speaker}
        starts = [segment.start for segment in segments]
        ends = [segment.end for segment in segments]
        return LLMChunk(
            index=index,
            text=text,
            segments=list(segments),
            start=min(starts) if starts else None,
            end=max(ends) if ends else None,
            speaker_set=set(speakers),
        )

    def _split_text(self, text: str) -> list[str]:
        chunks: list[str] = []
        start = 0
        length = len(text)
        while start < length:
            end = min(start + self.segment_size, length)
            if end < length:
                split_at = self._find_split_point(text, start, end)
                if split_at > start:
                    end = split_at
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= length:
                break
            start = max(end - self.overlap, end if self.overlap == 0 else start + 1)
        return chunks

    def _find_split_point(self, text: str, start: int, end: int) -> int:
        window = text[start:end]
        min_offset = max(1, self.segment_size // 2)
        candidates = [window.rfind(mark) for mark in ("\n", "。", "！", "？", "!", "?", "；", ";", "，", ",", " ")]
        best = max(candidates)
        if best >= min_offset:
            return start + best + 1
        return end

    def _merge_short_tail(self, chunks: list[LLMDialogChunk]) -> list[LLMDialogChunk]:
        if len(chunks) < 2:
            return chunks
        tail = chunks[-1]
        previous = chunks[-2]
        if tail.fallback_only or previous.fallback_only:
            return chunks
        tail_chars = sum(len(item.text) for item in tail.items)
        previous_chars = sum(len(item.text) for item in previous.items)
        if tail_chars >= self.dialog_min_chars or previous_chars + tail_chars > self.dialog_max_chars:
            return chunks
        merged = LLMDialogChunk(index=previous.index, items=[*previous.items, *tail.items])
        updated = [*chunks[:-2], merged]
        return [
            LLMDialogChunk(
                index=index,
                items=chunk.items,
                fallback_only=chunk.fallback_only,
                warning_codes=chunk.warning_codes,
            )
            for index, chunk in enumerate(updated)
        ]
