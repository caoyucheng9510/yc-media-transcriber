from __future__ import annotations

import re

from app.schemas import Segment


TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2}\.\d{3})"
)
TAG_RE = re.compile(r"<[^>]+>")


def parse_vtt(content: str) -> list[Segment]:
    lines = content.replace("\ufeff", "").splitlines()
    segments: list[Segment] = []
    index = 0
    while index < len(lines):
        match = TIMESTAMP_RE.search(lines[index])
        if not match:
            index += 1
            continue
        start = _parse_timestamp(match.group("start"))
        end = _parse_timestamp(match.group("end"))
        index += 1
        text_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(TAG_RE.sub("", lines[index]).strip())
            index += 1
        text = " ".join(line for line in text_lines if line).strip()
        if text:
            segments.append(Segment(start=start, end=end, speaker=None, text=text))
        index += 1
    return _dedupe_segments(segments)


def _parse_timestamp(raw: str) -> float:
    hours, minutes, rest = raw.split(":")
    seconds, millis = rest.split(".")
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis) / 1000.0
    )


def _dedupe_segments(segments: list[Segment]) -> list[Segment]:
    deduped: list[Segment] = []
    last_text = None
    for segment in segments:
        if segment.text == last_text:
            continue
        deduped.append(segment)
        last_text = segment.text
    return deduped
