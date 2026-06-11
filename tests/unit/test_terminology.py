from __future__ import annotations

from app.schemas import Term, TermsPayload
from app.terminology import TerminologyStore


def test_term_context_does_not_trigger_matching(tmp_path) -> None:
    store = TerminologyStore(tmp_path / "terms.json")
    store.save(
        TermsPayload(
            terms=[
                Term(incorrect="deep seek", correct="DeepSeek", context="AI 平台"),
                Term(incorrect="claud", correct="Claude", context="AI 模型"),
            ]
        )
    )

    matches = store.match_terms(title="这是一段 AI 平台介绍", transcript_preview="没有提到具体术语")

    assert matches == []


def test_terms_match_on_incorrect_or_correct_text(tmp_path) -> None:
    store = TerminologyStore(tmp_path / "terms.json")
    store.save(
        TermsPayload(
            terms=[
                Term(incorrect="deep seek", correct="DeepSeek", context="AI 平台"),
                Term(incorrect="claud", correct="Claude", context="AI 模型"),
            ]
        )
    )

    matches = store.match_terms(title="deep seek 使用体验", transcript_preview="也会提到 Claude")

    assert [term.correct for term in matches] == ["DeepSeek", "Claude"]
