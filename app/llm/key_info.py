from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.config import Settings
from app.errors import AppError
from app.llm.base import LLMClient
from app.llm.prompts import KEY_INFO_SYSTEM_PROMPT, build_key_info_user_prompt
from app.llm.structured import KeyInfo
from app.llm.utils import chat_json
from app.schemas import Term


@dataclass
class KeyInfoResult:
    key_info: KeyInfo = field(default_factory=KeyInfo)
    warnings: list[str] = field(default_factory=list)


class KeyInfoExtractor:
    def __init__(self, settings: Settings, client: LLMClient):
        self.settings = settings
        self.client = client

    def extract(self, *, metadata: dict, metrics: Any | None = None) -> KeyInfoResult:
        try:
            data = chat_json(
                self.client,
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": KEY_INFO_SYSTEM_PROMPT},
                    {"role": "user", "content": build_key_info_user_prompt(metadata)},
                ],
                purpose="key_info",
                metrics=metrics,
                timeout=self.settings.llm_chat_timeout_seconds,
            )
            return KeyInfoResult(key_info=KeyInfo.model_validate(data))
        except (AppError, ValidationError, TypeError, ValueError):
            return KeyInfoResult(key_info=KeyInfo(), warnings=["key_info_failed"])


def merge_reference_terms(key_info: KeyInfo, matched_terms: list[Term]) -> list[Term]:
    terms = list(matched_terms)
    seen = {term.correct.strip().lower() for term in terms if term.correct.strip()}
    for value in _flatten_key_info(key_info):
        normalized = value.strip()
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        terms.append(Term(correct=normalized, context="LLM key info"))
    return terms


def _flatten_key_info(key_info: KeyInfo) -> list[str]:
    values: list[str] = []
    for field_name in (
        "names",
        "places",
        "technical_terms",
        "brands",
        "abbreviations",
        "foreign_terms",
        "other_entities",
    ):
        field_values = getattr(key_info, field_name)
        values.extend(item for item in field_values if isinstance(item, str))
    return values
