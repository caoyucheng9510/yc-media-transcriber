from __future__ import annotations

import json
from pathlib import Path

from app.schemas import Term, TermsPayload


DEFAULT_TERMS = [
    Term(incorrect="deep seek", correct="DeepSeek", context="AI 平台"),
    Term(incorrect="claud", correct="Claude", context="AI 模型"),
    Term(incorrect="飞书妙计", correct="飞书妙记", context="产品名"),
    Term(incorrect="b站", correct="Bilibili", context="平台名"),
]


class TerminologyStore:
    def __init__(self, terms_path: Path):
        self.terms_path = terms_path
        self.terms_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.terms_path.exists():
            self.save(TermsPayload(terms=DEFAULT_TERMS))

    def load(self) -> TermsPayload:
        try:
            payload = json.loads(self.terms_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            payload = {"terms": []}
        except json.JSONDecodeError:
            payload = {"terms": []}
        return TermsPayload.model_validate(payload)

    def save(self, payload: TermsPayload) -> TermsPayload:
        normalized = TermsPayload(terms=payload.terms)
        self.terms_path.write_text(
            normalized.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return normalized

    def replace_terms(self, terms: list[Term]) -> TermsPayload:
        return self.save(TermsPayload(terms=terms))

    def match_terms(
        self,
        *,
        title: str = "",
        description: str = "",
        transcript_preview: str = "",
        limit: int = 20,
    ) -> list[Term]:
        haystack = f"{title}\n{description}\n{transcript_preview}".lower()
        matches: list[Term] = []
        for term in self.load().terms:
            candidates = [term.incorrect, term.correct]
            if any(candidate and candidate.lower() in haystack for candidate in candidates):
                matches.append(term)
            if len(matches) >= limit:
                break
        return matches
