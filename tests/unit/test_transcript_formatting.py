from __future__ import annotations

from app.llm.structured import DialogItem
from app.schemas import StructuredTranscriptItem
from app.transcript import (
    format_dialog_items_for_display,
    merge_dialog_items_for_display,
)


def _item(
    text: str,
    *,
    speaker_label: str = "Speaker1",
    speaker_name: str | None = None,
    start: float | None = 0.0,
    end: float | None = 0.5,
) -> dict:
    item = {
        "speaker_label": speaker_label,
        "speaker_name": speaker_name,
        "text": text,
    }
    if start is not None:
        item["start"] = start
    if end is not None:
        item["end"] = end
    return item


def test_same_speaker_short_items_merge_and_prefix_once() -> None:
    text = format_dialog_items_for_display(
        [
            _item("嗯，", start=0.0, end=0.4),
            _item("那今天你主持啊，", start=0.5, end=1.1),
            _item("没问题，", start=1.1, end=1.8),
        ]
    )

    assert text == "Speaker1: 嗯，那今天你主持啊，没问题，"


def test_speaker_switch_does_not_merge() -> None:
    text = format_dialog_items_for_display(
        [
            _item("你好。", speaker_label="Speaker1", start=0.0, end=0.5),
            _item("你好。", speaker_label="Speaker2", start=0.6, end=1.0),
        ]
    )

    assert text == "Speaker1: 你好。\nSpeaker2: 你好。"


def test_different_speaker_name_does_not_merge() -> None:
    text = format_dialog_items_for_display(
        [
            _item("第一句。", speaker_name="张三", start=0.0, end=0.5),
            _item("第二句。", speaker_name="李四", start=0.6, end=1.0),
        ]
    )

    assert text == "张三: 第一句。\n李四: 第二句。"


def test_normal_timestamp_gap_blocks_merge() -> None:
    text = format_dialog_items_for_display(
        [
            _item("第一句。", start=0.0, end=1.0),
            _item("第二句。", start=2.6, end=3.0),
        ]
    )

    assert text == "Speaker1: 第一句。\nSpeaker1: 第二句。"


def test_abnormal_or_missing_timestamps_do_not_block_merge() -> None:
    reversed_time = format_dialog_items_for_display(
        [
            _item("第一句，", start=1.0, end=2.0),
            _item("第二句。", start=1.5, end=3.0),
        ]
    )
    missing_time = format_dialog_items_for_display(
        [
            _item("第三句，", start=None, end=None),
            _item("第四句。", start=None, end=None),
        ]
    )
    invalid_duration = format_dialog_items_for_display(
        [
            _item("第五句，", start=3.0, end=2.0),
            _item("第六句。", start=10.0, end=9.0),
        ]
    )

    assert reversed_time == "Speaker1: 第一句，第二句。"
    assert missing_time == "Speaker1: 第三句，第四句。"
    assert invalid_duration == "Speaker1: 第五句，第六句。"


def test_soft_max_chars_splits_after_terminal_punctuation() -> None:
    long_sentence = "甲" * 121 + "。"
    text = format_dialog_items_for_display(
        [
            _item(long_sentence, start=0.0, end=0.5),
            _item("下一句。", start=0.6, end=1.0),
        ]
    )

    assert text == f"Speaker1: {long_sentence}\nSpeaker1: 下一句。"


def test_hard_max_chars_blocks_cross_segment_merge() -> None:
    first = "a" * 255
    second = "bbbbbb"
    merged = merge_dialog_items_for_display(
        [
            _item(first, start=0.0, end=0.5),
            _item(second, start=0.6, end=1.0),
        ]
    )

    assert [item["text"] for item in merged] == [first, second]


def test_chinese_joins_directly_and_ascii_boundaries_get_spaces() -> None:
    chinese = format_dialog_items_for_display(
        [
            _item("你好，", start=0.0, end=0.5),
            _item("世界。", start=0.6, end=1.0),
        ]
    )
    english = format_dialog_items_for_display(
        [
            _item("hello", start=0.0, end=0.5),
            _item("world", start=0.6, end=1.0),
            _item("123", start=1.0, end=1.2),
            _item("456", start=1.2, end=1.4),
        ]
    )

    assert chinese == "Speaker1: 你好，世界。"
    assert english == "Speaker1: hello world 123 456"


def test_empty_text_items_are_skipped() -> None:
    text = format_dialog_items_for_display(
        [
            _item("第一句，", start=0.0, end=0.5),
            _item("   ", start=0.6, end=0.7),
            _item("第二句。", start=0.8, end=1.0),
        ]
    )

    assert text == "Speaker1: 第一句，第二句。"


def test_single_item_over_hard_limit_is_not_split_or_dropped() -> None:
    long_text = "很长" * 140
    merged = merge_dialog_items_for_display([_item(long_text)])

    assert len(merged) == 1
    assert merged[0]["text"] == long_text


def test_formatter_accepts_dialog_item_structured_item_and_dict() -> None:
    text = format_dialog_items_for_display(
        [
            DialogItem(
                start=0.0,
                end=0.5,
                speaker_label="Speaker1",
                speaker_name="张三",
                text="你好，",
            ),
            StructuredTranscriptItem(
                start=0.6,
                end=1.0,
                speaker_label="Speaker1",
                speaker_name="张三",
                text="世界。",
            ),
            {
                "start": 1.1,
                "end": 1.5,
                "speaker_label": "Speaker2",
                "speaker_name": None,
                "text": "我来了。",
            },
        ]
    )

    assert text == "张三: 你好，世界。\nSpeaker2: 我来了。"
