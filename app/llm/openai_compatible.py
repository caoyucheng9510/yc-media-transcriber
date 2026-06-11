from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.errors import AppError
from app.llm.base import LLMChatResult, LLMJsonResult, LLMMessage


STRUCTURED_OUTPUT_MODES = {"auto", "json_object", "plain"}


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        provider_name: str,
        api_key: str,
        base_url: str,
        missing_key_name: str = "LLM_API_KEY",
        structured_output_mode: str = "auto",
    ):
        self.provider_name = provider_name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.missing_key_name = missing_key_name
        self.structured_output_mode = (
            structured_output_mode if structured_output_mode in STRUCTURED_OUTPUT_MODES else "auto"
        )
        self.missing_configuration_reason = (
            None if self.api_key else f"需要配置 {self.missing_key_name}"
        )

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def chat(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        timeout: float = 60.0,
    ) -> LLMChatResult:
        if not self.api_key:
            raise AppError(
                "llm_provider_not_configured",
                f"{self.provider_name} 需要配置 {self.missing_key_name}。",
                "llm_processing",
            )
        url = f"{self.base_url}/v1/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AppError(
                "llm_failed",
                f"{self.provider_name} 调用失败：{exc}",
                "llm_processing",
            ) from exc
        data = response.json()
        try:
            content = str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise AppError(
                "llm_failed",
                f"{self.provider_name} 返回结构不符合预期。",
                "llm_processing",
            ) from exc
        return LLMChatResult(
            content=content,
            provider=self.provider_name,
            model=model,
            usage=_usage_from_payload(data.get("usage")),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    def chat_json(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        schema: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> LLMJsonResult:
        if not self.api_key:
            raise AppError(
                "llm_provider_not_configured",
                f"{self.provider_name} 需要配置 {self.missing_key_name}。",
                "llm_processing",
            )

        started = time.perf_counter()
        mode = self.structured_output_mode
        try:
            data = self._post_chat_json(
                model=model,
                messages=messages,
                timeout=timeout,
                use_response_format=mode in {"auto", "json_object"},
            )
        except httpx.HTTPStatusError as exc:
            if mode == "auto" and _response_format_not_supported(exc):
                data = self._post_chat_json(
                    model=model,
                    messages=_with_plain_json_instruction(messages),
                    timeout=timeout,
                    use_response_format=False,
                )
            else:
                raise AppError(
                    "llm_failed",
                    f"{self.provider_name} 调用失败：{exc}",
                    "llm_processing",
                ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                "llm_failed",
                f"{self.provider_name} 调用失败：{exc}",
                "llm_processing",
            ) from exc

        try:
            content = str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise AppError(
                "llm_failed",
                f"{self.provider_name} 返回结构不符合预期。",
                "llm_processing",
            ) from exc
        parsed = parse_json_object(content)
        return LLMJsonResult(
            data=parsed,
            raw_content=content,
            provider=self.provider_name,
            model=model,
            usage=_usage_from_payload(data.get("usage")),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    def _post_chat_json(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        timeout: float,
        use_response_format: bool,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/v1/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
        }
        if use_response_format:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        return response.json()


def _usage_from_payload(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    usage: dict[str, int] = {}
    for key, raw in value.items():
        if not isinstance(key, str):
            continue
        try:
            usage[key] = max(0, int(raw or 0))
        except (TypeError, ValueError):
            continue
    usage.setdefault("prompt_tokens", 0)
    usage.setdefault("completion_tokens", 0)
    usage.setdefault("total_tokens", 0)
    return usage


def parse_json_object(content: str) -> dict[str, Any]:
    text = _strip_json_fence(content)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise AppError("llm_failed", "LLM 返回 JSON 不符合预期。", "llm_processing")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AppError("llm_failed", "LLM 返回 JSON 不符合预期。", "llm_processing") from exc
    if not isinstance(parsed, dict):
        raise AppError("llm_failed", "LLM 返回 JSON 不符合预期。", "llm_processing")
    return parsed


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _with_plain_json_instruction(messages: list[LLMMessage]) -> list[LLMMessage]:
    if not messages:
        return [{"role": "user", "content": "只输出 JSON object。"}]
    updated = list(messages)
    last = dict(updated[-1])
    last["content"] = f"{last.get('content', '')}\n\n只输出 JSON object，不要使用 markdown code fence。"
    updated[-1] = last
    return updated


def _response_format_not_supported(exc: httpx.HTTPStatusError) -> bool:
    response = exc.response
    status_code = getattr(response, "status_code", 0)
    if status_code not in {400, 422}:
        return False
    try:
        text = response.text.lower()
    except Exception:
        text = ""
    return "response_format" in text or "json_object" in text
