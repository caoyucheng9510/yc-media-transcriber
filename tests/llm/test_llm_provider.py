from __future__ import annotations

from pathlib import Path

import pytest

from app.capabilities import build_capabilities
from app.config import Settings
from app.llm.openai_compatible import OpenAICompatibleClient, httpx
from app.llm.providers import create_llm_client


def test_llm_provider_factory_deepseek_uses_compatible_key(tmp_path: Path) -> None:
    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_provider="deepseek",
        llm_api_key="generic-key",
    )
    client = create_llm_client(settings)
    assert client.provider_name == "deepseek"
    assert client.available is True


def test_llm_provider_factory_deepseek_requires_llm_api_key(tmp_path: Path) -> None:
    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_provider="deepseek",
    )
    client = create_llm_client(settings)
    assert client.available is False
    assert client.missing_configuration_reason == "需要配置 LLM_API_KEY"


def test_llm_provider_factory_openai_compatible_uses_llm_api_key(tmp_path: Path) -> None:
    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_provider="openai_compatible",
        llm_api_key="generic-key",
        llm_base_url="https://llm.example.com",
    )
    client = create_llm_client(settings)
    assert client.provider_name == "openai_compatible"
    assert client.available is True


def test_capabilities_reports_selected_llm_provider(tmp_path: Path) -> None:
    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_provider="openai_compatible",
        llm_api_key="generic-key",
        llm_model="deepseek-test-model",
    )
    payload = build_capabilities(settings)
    assert payload["llm"]["provider"] == "openai_compatible"
    assert payload["llm"]["available"] is True
    assert payload["llm"]["model"] == "deepseek-test-model"


def test_openai_compatible_chat_preserves_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": " hello "}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "prompt_cache_hit_tokens": 3,
                },
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url: str, json: dict, headers: dict) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = OpenAICompatibleClient(
        provider_name="openai_compatible",
        api_key="key",
        base_url="https://llm.example.com",
    )

    result = client.chat(model="model", messages=[{"role": "user", "content": "hi"}])

    assert result.content == "hello"
    assert result.provider == "openai_compatible"
    assert result.model == "model"
    assert result.usage["prompt_tokens"] == 10
    assert result.usage["completion_tokens"] == 5
    assert result.usage["total_tokens"] == 15
    assert result.usage["prompt_cache_hit_tokens"] == 3


def test_openai_compatible_chat_defaults_missing_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url: str, json: dict, headers: dict) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = OpenAICompatibleClient(
        provider_name="openai_compatible",
        api_key="key",
        base_url="https://llm.example.com",
    )

    result = client.chat(model="model", messages=[{"role": "user", "content": "hi"}])

    assert result.usage == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def test_openai_compatible_chat_json_parses_code_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": '```json\n{"ok": true}\n```'}}],
                "usage": {"total_tokens": 3},
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url: str, json: dict, headers: dict) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = OpenAICompatibleClient(
        provider_name="openai_compatible",
        api_key="key",
        base_url="https://llm.example.com",
    )

    result = client.chat_json(model="model", messages=[{"role": "user", "content": "hi"}])

    assert result.data == {"ok": True}
    assert result.usage["total_tokens"] == 3


def test_openai_compatible_chat_json_auto_falls_back_when_response_format_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __init__(self, *, ok: bool):
            self.ok = ok
            self.status_code = 400 if not ok else 200
            self.text = "response_format is not supported" if not ok else ""

        def raise_for_status(self) -> None:
            if self.ok:
                return None
            request = httpx.Request("POST", "https://llm.example.com/v1/chat/completions")
            response = httpx.Response(400, text=self.text, request=request)
            raise httpx.HTTPStatusError("bad request", request=request, response=response)

        def json(self) -> dict:
            return {"choices": [{"message": {"content": '{"fallback": true}'}}]}

    class FakeClient:
        payloads: list[dict] = []

        def __init__(self, *args, **kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url: str, json: dict, headers: dict) -> FakeResponse:
            self.payloads.append(json)
            return FakeResponse(ok=len(self.payloads) > 1)

    FakeClient.payloads = []
    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = OpenAICompatibleClient(
        provider_name="openai_compatible",
        api_key="key",
        base_url="https://llm.example.com",
        structured_output_mode="auto",
    )

    result = client.chat_json(model="model", messages=[{"role": "user", "content": "hi"}])

    assert result.data == {"fallback": True}
    assert "response_format" in FakeClient.payloads[0]
    assert "response_format" not in FakeClient.payloads[1]
