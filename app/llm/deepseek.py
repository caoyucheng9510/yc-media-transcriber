from __future__ import annotations

from app.config import Settings
from app.llm.openai_compatible import OpenAICompatibleClient


class DeepSeekClient(OpenAICompatibleClient):
    def __init__(self, settings: Settings):
        super().__init__(
            provider_name="deepseek",
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            missing_key_name="LLM_API_KEY",
            structured_output_mode=settings.llm_structured_output_mode,
        )
