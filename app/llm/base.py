from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


LLMMessage = dict[str, str]


@dataclass(frozen=True)
class LLMChatResult:
    content: str
    provider: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0


@dataclass(frozen=True)
class LLMJsonResult:
    data: dict[str, Any]
    raw_content: str
    provider: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0


class LLMClient(Protocol):
    provider_name: str
    missing_configuration_reason: str | None

    @property
    def available(self) -> bool:
        raise NotImplementedError

    def chat(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        timeout: float = 60.0,
    ) -> LLMChatResult:
        raise NotImplementedError

    def chat_json(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        schema: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> LLMJsonResult:
        raise NotImplementedError
