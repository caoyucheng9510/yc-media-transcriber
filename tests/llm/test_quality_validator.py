from __future__ import annotations

import time
from pathlib import Path

from app.config import Settings
from app.llm.quality import LLMQualityChecker, LLMQualityValidator
from app.llm.structured import DialogItem


def test_local_dialog_validation_rejects_count_or_speaker_mismatch() -> None:
    checker = LLMQualityChecker(min_ratio=0.5, max_ratio=2.0)
    original = [DialogItem(start=0, end=1, speaker_label="Speaker1", text="你好")]

    assert checker.validate_dialog_payload(original_items=original, payload=[]) == ["dialog_count_mismatch"]
    assert checker.validate_dialog_payload(
        original_items=original,
        payload=[{"speaker_label": "Speaker2", "text": "你好"}],
    ) == ["speaker_label_mismatch"]


def test_llm_validation_disabled_does_not_call_client(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            raise AssertionError("validator should not be called")

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_validation_enabled=False,
    )
    result = LLMQualityValidator(settings, Client()).validate(
        original_text="原文",
        polished_text="校对",
        mode="plain_text",
        monotonic_now=time.monotonic(),
    )

    assert result.score is None
    assert result.accepted is True


def test_llm_validation_records_score_when_enabled(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            return '{"accuracy":0.9,"completeness":0.8,"fluency":0.7,"format":1.0}'

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_validation_enabled=True,
    )
    result = LLMQualityValidator(settings, Client()).validate(
        original_text="原文",
        polished_text="校对",
        mode="plain_text",
        monotonic_now=time.monotonic(),
    )

    assert result.score == 0.84
    assert result.accepted is True
    assert result.warnings == []


def test_llm_validation_failure_keeps_candidate_with_warning(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            return "not json"

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_validation_enabled=True,
    )
    result = LLMQualityValidator(settings, Client()).validate(
        original_text="原文",
        polished_text="校对",
        mode="plain_text",
        monotonic_now=time.monotonic(),
    )

    assert result.accepted is True
    assert result.warnings == ["quality_validation_failed"]
