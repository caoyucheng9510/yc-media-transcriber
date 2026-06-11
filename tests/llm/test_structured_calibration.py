from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.errors import AppError
from app.llm.calibration import CalibrationProcessor
from app.llm.quality import LLMQualityChecker
from app.llm.structured import KeyInfo
from app.schemas import Segment


def _processor(settings: Settings, client: object) -> CalibrationProcessor:
    return CalibrationProcessor(
        settings,
        client,  # type: ignore[arg-type]
        LLMQualityChecker(
            min_ratio=settings.llm_quality_min_ratio,
            max_ratio=settings.llm_quality_max_ratio,
        ),
    )


def test_structured_dialog_calibration_success_preserves_time_and_speaker(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            return '{"calibrated_dialogs":[{"speaker_label":"Speaker1","text":"你好。"}]}'

    settings = Settings(app_data_dir=tmp_path, terms_path=tmp_path / "terms.json")
    result = _processor(settings, Client()).calibrate(
        raw_transcript="Speaker1: 你好",
        segments=[Segment(start=1.0, end=2.0, speaker="Speaker1", text="你好")],
        speaker_mapping={"Speaker1": "张三"},
        terms=[],
        key_info=KeyInfo(),
        metadata={},
    )

    assert result.detail.mode == "structured_dialog"
    assert result.structured_transcript[0].start == 1.0
    assert result.structured_transcript[0].end == 2.0
    assert result.structured_transcript[0].speaker_label == "Speaker1"
    assert result.structured_transcript[0].speaker_name == "张三"
    assert result.structured_transcript[0].text == "你好。"
    assert result.polished_text == "张三: 你好。"


def test_structured_dialog_polished_text_remains_strict_item_text(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            return (
                '{"calibrated_dialogs":['
                '{"speaker_label":"Speaker1","text":"你好。"},'
                '{"speaker_label":"Speaker1","text":"继续。"}'
                ']}'
            )

    settings = Settings(app_data_dir=tmp_path, terms_path=tmp_path / "terms.json")
    result = _processor(settings, Client()).calibrate(
        raw_transcript="Speaker1: 你好\nSpeaker1: 继续",
        segments=[
            Segment(start=0.0, end=0.5, speaker="Speaker1", text="你好"),
            Segment(start=0.6, end=1.0, speaker="Speaker1", text="继续"),
        ],
        speaker_mapping={"Speaker1": "张三"},
        terms=[],
        key_info=KeyInfo(),
        metadata={},
    )

    assert len(result.structured_transcript) == 2
    assert result.polished_text == "张三: 你好。\n张三: 继续。"


def test_structured_dialog_retries_count_mismatch(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def __init__(self) -> None:
            self.calls = 0

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            self.calls += 1
            if self.calls == 1:
                return '{"calibrated_dialogs":[]}'
            return '{"calibrated_dialogs":[{"speaker_label":"Speaker1","text":"你好。"}]}'

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_calibration_max_retries=2,
    )
    client = Client()
    result = _processor(settings, client).calibrate(
        raw_transcript="Speaker1: 你好",
        segments=[Segment(start=0, end=1, speaker="Speaker1", text="你好")],
        speaker_mapping={},
        terms=[],
        key_info=KeyInfo(),
        metadata={},
    )

    assert client.calls == 2
    assert result.detail.chunks[0].attempts == 2
    assert result.structured_transcript[0].text == "你好。"
    assert "dialog_count_mismatch" in result.detail.chunks[0].warning_codes


def test_structured_dialog_retries_llm_failed_app_error(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def __init__(self) -> None:
            self.calls = 0

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            self.calls += 1
            if self.calls == 1:
                raise AppError("llm_failed", "fake 调用失败：timeout", "llm_processing")
            return '{"calibrated_dialogs":[{"speaker_label":"Speaker1","text":"你好。"}]}'

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_calibration_max_retries=2,
    )
    client = Client()
    result = _processor(settings, client).calibrate(
        raw_transcript="Speaker1: 你好",
        segments=[Segment(start=0, end=1, speaker="Speaker1", text="你好")],
        speaker_mapping={},
        terms=[],
        key_info=KeyInfo(),
        metadata={},
    )

    assert client.calls == 2
    assert result.detail.fallback_count == 0
    assert result.detail.chunks[0].attempts == 2
    assert result.structured_transcript[0].text == "你好。"


def test_structured_dialog_rejects_speaker_label_change(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            return '{"calibrated_dialogs":[{"speaker_label":"Speaker2","text":"你好。"}]}'

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_calibration_max_retries=1,
    )
    result = _processor(settings, Client()).calibrate(
        raw_transcript="Speaker1: 你好",
        segments=[Segment(start=0, end=1, speaker="Speaker1", text="你好")],
        speaker_mapping={},
        terms=[],
        key_info=KeyInfo(),
        metadata={},
    )

    assert result.structured_transcript[0].text == "你好"
    assert result.polished_text == "Speaker1: 你好"
    assert result.detail.fallback_count == 1
    assert "speaker_label_mismatch" in result.warnings


def test_structured_dialog_invalid_json_falls_back_current_chunk(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            return "not json"

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_calibration_max_retries=1,
    )
    result = _processor(settings, Client()).calibrate(
        raw_transcript="Speaker1: 你好",
        segments=[Segment(start=0, end=1, speaker="Speaker1", text="你好")],
        speaker_mapping={},
        terms=[],
        key_info=KeyInfo(),
        metadata={},
    )

    assert result.structured_transcript[0].text == "你好"
    assert result.detail.fallback_count == 1
    assert "calibration_chunk_failed" in result.warnings


def test_structured_dialog_long_segment_is_not_split_and_falls_back(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            raise AssertionError("LLM should not be called")

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_dialog_max_chunk_chars=10,
    )
    result = _processor(settings, Client()).calibrate(
        raw_transcript="Speaker1: " + "很长" * 20,
        segments=[Segment(start=0, end=1, speaker="Speaker1", text="很长" * 20)],
        speaker_mapping={},
        terms=[],
        key_info=KeyInfo(),
        metadata={},
    )

    assert len(result.structured_transcript) == 1
    assert result.detail.fallback_count == 1
    assert "dialog_segment_too_long" in result.warnings
