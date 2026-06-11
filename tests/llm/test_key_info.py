from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.llm.key_info import KeyInfoExtractor, merge_reference_terms
from app.llm.structured import KeyInfo
from app.schemas import Term


def test_key_info_extracts_metadata_entities(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            return '{"names":["张三"],"technical_terms":["DeepSeek"]}'

    settings = Settings(app_data_dir=tmp_path, terms_path=tmp_path / "terms.json")
    result = KeyInfoExtractor(settings, Client()).extract(metadata={"title": "DeepSeek 访谈"})

    assert result.key_info.names == ["张三"]
    assert result.key_info.technical_terms == ["DeepSeek"]
    assert result.warnings == []


def test_key_info_invalid_json_falls_back(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            return "not json"

    settings = Settings(app_data_dir=tmp_path, terms_path=tmp_path / "terms.json")
    result = KeyInfoExtractor(settings, Client()).extract(metadata={})

    assert result.key_info == KeyInfo()
    assert result.warnings == ["key_info_failed"]


def test_local_terms_take_priority_when_merging_key_info() -> None:
    terms = [Term(incorrect="deep seek", correct="DeepSeek", context="local")]
    key_info = KeyInfo(technical_terms=["DeepSeek", "FunASR"])

    merged = merge_reference_terms(key_info, terms)

    assert [term.correct for term in merged] == ["DeepSeek", "FunASR"]
    assert merged[0].context == "local"
