from __future__ import annotations

from typing import Any


TERMINAL_PUNCTUATION = "。！？!?"


def merge_dialog_items_for_display(
    items: list[Any],
    *,
    max_gap_seconds: float = 1.5,
    soft_max_chars: int = 120,
    hard_max_chars: int = 260,
    terminal_punctuation: str = TERMINAL_PUNCTUATION,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    previous_source: dict[str, Any] | None = None

    for raw_item in items:
        item = _normalize_dialog_item(raw_item)
        if not item["text"]:
            continue
        if not merged or previous_source is None:
            merged.append(dict(item))
            previous_source = item
            continue

        current = merged[-1]
        if _can_merge(
            current,
            previous_source,
            item,
            max_gap_seconds=max_gap_seconds,
            soft_max_chars=soft_max_chars,
            hard_max_chars=hard_max_chars,
            terminal_punctuation=terminal_punctuation,
        ):
            current["text"] = _join_text(current["text"], item["text"])
            current["original_text"] = _join_text(
                str(current.get("original_text") or ""),
                str(item.get("original_text") or item["text"]),
            )
            if item["end"] is not None:
                current["end"] = item["end"]
        else:
            merged.append(dict(item))
        previous_source = item

    return merged


def format_dialog_items_for_display(
    items: list[Any],
    *,
    max_gap_seconds: float = 1.5,
    soft_max_chars: int = 120,
    hard_max_chars: int = 260,
    terminal_punctuation: str = TERMINAL_PUNCTUATION,
) -> str:
    merged_items = merge_dialog_items_for_display(
        items,
        max_gap_seconds=max_gap_seconds,
        soft_max_chars=soft_max_chars,
        hard_max_chars=hard_max_chars,
        terminal_punctuation=terminal_punctuation,
    )
    lines: list[str] = []
    for item in merged_items:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        speaker = str(item.get("speaker_name") or item.get("speaker_label") or "").strip()
        lines.append(f"{speaker}: {text}" if speaker else text)
    return "\n".join(lines)


def _normalize_dialog_item(item: Any) -> dict[str, Any]:
    text = str(_item_value(item, "text") or "").strip()
    original_text = _item_value(item, "original_text")
    original_text_value = str(original_text).strip() if original_text is not None else text
    return {
        "start": _to_seconds_or_none(_item_value(item, "start")),
        "end": _to_seconds_or_none(_item_value(item, "end")),
        "speaker_label": str(_item_value(item, "speaker_label") or "").strip(),
        "speaker_name": _normalize_optional_text(_item_value(item, "speaker_name")),
        "text": text,
        "original_text": original_text_value,
    }


def _item_value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    if hasattr(item, key):
        return getattr(item, key)
    raise TypeError(f"Unsupported dialog item type: {type(item).__name__}")


def _normalize_optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _to_seconds_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _can_merge(
    current: dict[str, Any],
    previous_source: dict[str, Any],
    item: dict[str, Any],
    *,
    max_gap_seconds: float,
    soft_max_chars: int,
    hard_max_chars: int,
    terminal_punctuation: str,
) -> bool:
    if current["speaker_label"] != item["speaker_label"]:
        return False
    if (current.get("speaker_name") or "") != (item.get("speaker_name") or ""):
        return False

    current_text = str(current["text"])
    if len(current_text) > soft_max_chars and current_text.endswith(tuple(terminal_punctuation)):
        return False

    next_text = _join_text(current_text, str(item["text"]))
    if len(next_text) > hard_max_chars:
        return False

    gap = _normal_timestamp_gap(previous_source, item)
    if gap is not None and gap > max_gap_seconds:
        return False

    return True


def _normal_timestamp_gap(previous: dict[str, Any], current: dict[str, Any]) -> float | None:
    previous_start = previous.get("start")
    previous_end = previous.get("end")
    current_start = current.get("start")
    current_end = current.get("end")
    if (
        previous_start is None
        or previous_end is None
        or current_start is None
        or current_end is None
    ):
        return None
    if previous_end < previous_start or current_end < current_start:
        return None
    if current_start < previous_end:
        return None
    return current_start - previous_end


def _join_text(left: str, right: str) -> str:
    left_text = left.strip()
    right_text = right.strip()
    if not left_text:
        return right_text
    if not right_text:
        return left_text
    separator = " " if _needs_space(left_text[-1], right_text[0]) else ""
    return f"{left_text}{separator}{right_text}"


def _needs_space(left: str, right: str) -> bool:
    if _is_ascii_alnum(left) and _is_ascii_alnum(right):
        return True
    return left in ".,;:!?" and _is_ascii_alnum(right)


def _is_ascii_alnum(value: str) -> bool:
    return value.isascii() and value.isalnum()
