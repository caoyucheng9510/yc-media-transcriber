from __future__ import annotations

from typing import Any

from app.errors import AppError
from app.llm.base import LLMChatResult, LLMClient, LLMJsonResult, LLMMessage
from app.llm.openai_compatible import parse_json_object


def record_llm_usage(metrics: Any | None, result: object, *, purpose: str) -> None:
    if metrics is None or not isinstance(result, (LLMChatResult, LLMJsonResult)):
        return
    usage = result.usage or {}
    metrics.record_llm_usage(
        provider=result.provider,
        model=result.model,
        purpose=purpose,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
        duration_ms=result.duration_ms,
        extra_usage={
            key: value
            for key, value in usage.items()
            if key not in {"prompt_tokens", "completion_tokens", "total_tokens"}
        },
    )


def chat_text(
    client: LLMClient,
    *,
    model: str,
    messages: list[LLMMessage],
    purpose: str,
    metrics: Any | None = None,
    timeout: float = 60.0,
) -> str:
    result = client.chat(model=model, messages=messages, timeout=timeout)
    record_llm_usage(metrics, result, purpose=purpose)
    if isinstance(result, LLMChatResult):
        return result.content
    return str(result)


def chat_json(
    client: LLMClient,
    *,
    model: str,
    messages: list[LLMMessage],
    purpose: str,
    metrics: Any | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    if hasattr(client, "chat_json"):
        result = client.chat_json(model=model, messages=messages, timeout=timeout)
        record_llm_usage(metrics, result, purpose=purpose)
        if isinstance(result, LLMJsonResult):
            return result.data
        if isinstance(result, dict):
            return result
    result = client.chat(model=model, messages=messages, timeout=timeout)
    record_llm_usage(metrics, result, purpose=purpose)
    content = result.content if isinstance(result, LLMChatResult) else str(result)
    return parse_json_object(content)


def safe_timeout(timeout: float, deadline: float | None, monotonic_now: float) -> float:
    if deadline is None:
        return max(1.0, timeout)
    remaining = deadline - monotonic_now
    if remaining <= 0:
        raise AppError("llm_failed", "LLM chunk time budget exhausted.", "llm_processing")
    return max(1.0, min(timeout, remaining))
