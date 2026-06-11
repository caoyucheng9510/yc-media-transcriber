from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.errors import AppError
from app.llm.calibration import CalibrationProcessor
from app.llm.quality import LLMQualityChecker
from app.llm.structured import KeyInfo


def _processor(settings: Settings, client: object) -> CalibrationProcessor:
    return CalibrationProcessor(
        settings,
        client,  # type: ignore[arg-type]
        LLMQualityChecker(
            min_ratio=settings.llm_quality_min_ratio,
            max_ratio=settings.llm_quality_max_ratio,
        ),
    )


def test_plain_calibration_splits_and_preserves_order(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def __init__(self) -> None:
            self.calls = 0

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            self.calls += 1
            return f"chunk-{self.calls}"

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_segment_size=10,
        llm_quality_min_ratio=0.0,
        llm_quality_max_ratio=100.0,
    )
    client = Client()
    result = _processor(settings, client).calibrate(
        raw_transcript="第一段内容很长。第二段内容也很长。第三段内容继续很长。",
        segments=[],
        speaker_mapping={},
        terms=[],
        key_info=KeyInfo(),
        metadata={},
    )

    assert result.detail.total_chunks == client.calls
    assert result.polished_text == "\n\n".join(f"chunk-{index}" for index in range(1, client.calls + 1))


def test_plain_calibration_retries_short_output(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def __init__(self) -> None:
            self.calls = 0

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            self.calls += 1
            return "短" if self.calls == 1 else "这是一段足够长的校对结果"

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_calibration_max_retries=2,
        llm_quality_min_ratio=0.8,
        llm_quality_max_ratio=10.0,
    )
    client = Client()
    result = _processor(settings, client).calibrate(
        raw_transcript="这是一段足够长的原始转录文本，用来确认第一次输出过短时会重试。",
        segments=[],
        speaker_mapping={},
        terms=[],
        key_info=KeyInfo(),
        metadata={},
    )

    assert client.calls == 2
    assert result.polished_text == "这是一段足够长的校对结果"
    assert result.detail.chunks[0].attempts == 2


def test_plain_calibration_retries_llm_failed_app_error(tmp_path: Path) -> None:
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
            return "这是一段足够长的校对结果"

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_calibration_max_retries=2,
        llm_quality_min_ratio=0.0,
        llm_quality_max_ratio=10.0,
    )
    client = Client()
    result = _processor(settings, client).calibrate(
        raw_transcript="这是一段足够长的原始转录文本，用来确认 LLM 调用失败时会重试。",
        segments=[],
        speaker_mapping={},
        terms=[],
        key_info=KeyInfo(),
        metadata={},
    )

    assert client.calls == 2
    assert result.polished_text == "这是一段足够长的校对结果"
    assert result.detail.fallback_count == 0
    assert result.detail.chunks[0].attempts == 2


def test_plain_calibration_does_not_retry_provider_configuration_error(tmp_path: Path) -> None:
    class Client:
        available = False
        provider_name = "fake"
        missing_configuration_reason = "需要配置 key"

        def __init__(self) -> None:
            self.calls = 0

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            self.calls += 1
            raise AppError("llm_provider_not_configured", "fake 需要配置 key。", "llm_processing")

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_calibration_max_retries=2,
        llm_quality_min_ratio=0.0,
        llm_quality_max_ratio=10.0,
    )
    client = Client()
    result = _processor(settings, client).calibrate(
        raw_transcript="这是一段足够长的原始转录文本，用来确认配置错误不会重试。",
        segments=[],
        speaker_mapping={},
        terms=[],
        key_info=KeyInfo(),
        metadata={},
    )

    assert client.calls == 1
    assert result.detail.fallback_count == 1
    assert result.detail.chunks[0].attempts == 1


def test_plain_calibration_falls_back_per_failed_chunk(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def __init__(self) -> None:
            self.calls = 0

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("boom")
            return f"ok-{self.calls}"

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_segment_size=8,
        llm_calibration_max_retries=1,
        llm_quality_min_ratio=0.0,
        llm_quality_max_ratio=100.0,
    )
    result = _processor(settings, Client()).calibrate(
        raw_transcript="第一段很长。第二段很长。第三段很长。",
        segments=[],
        speaker_mapping={},
        terms=[],
        key_info=KeyInfo(),
        metadata={},
    )

    assert result.detail.fallback_count == 1
    assert "calibration_chunk_failed" in result.warnings
    assert "第二段很长" in result.polished_text
