from __future__ import annotations

from app.config import Settings
from app.errors import AppError
from typing import Any

from app.llm.base import LLMChatResult, LLMJsonResult, LLMMessage
from app.llm.deepseek import DeepSeekClient
from app.llm.openai_compatible import OpenAICompatibleClient


class UnavailableLLMClient:
    def __init__(self, provider_name: str, reason: str):
        self.provider_name = provider_name
        self.missing_configuration_reason = reason

    @property
    def available(self) -> bool:
        return False

    def chat(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        timeout: float = 60.0,
    ) -> LLMChatResult:
        raise AppError(
            "llm_provider_not_configured",
            self.missing_configuration_reason,
            "llm_processing",
        )

    def chat_json(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        schema: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> LLMJsonResult:
        raise AppError(
            "llm_provider_not_configured",
            self.missing_configuration_reason,
            "llm_processing",
        )


def create_llm_client(settings: Settings):
    provider = settings.llm_provider.strip().lower()
    if provider == "deepseek":
        return DeepSeekClient(settings)
    if provider == "openai_compatible":
        return OpenAICompatibleClient(
            provider_name="openai_compatible",
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            missing_key_name="LLM_API_KEY",
            structured_output_mode=settings.llm_structured_output_mode,
        )
    return UnavailableLLMClient(
        provider_name=provider or "unknown",
        reason=f"不支持的 LLM_PROVIDER：{provider or '(empty)'}。",
    )
