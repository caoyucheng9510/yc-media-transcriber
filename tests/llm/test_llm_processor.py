from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.errors import AppError
from app.llm.base import LLMChatResult
from app.llm.processor import LLMProcessor
from app.schemas import JobOptions, Segment, Term, TermsPayload
from app.terminology import TerminologyStore


def test_llm_missing_key_error(tmp_path: Path) -> None:
    settings = Settings(app_data_dir=tmp_path, terms_path=tmp_path / "terms.json")
    terms = TerminologyStore(settings.terms_path)
    processor = LLMProcessor(settings, terms)
    with pytest.raises(AppError) as exc:
        processor.process(metadata={}, raw_transcript="hello", options=JobOptions())
    assert exc.value.code == "llm_provider_not_configured"


def test_terms_match_and_fake_llm(tmp_path: Path) -> None:
    class FakeClient:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            prompt = messages[-1]["content"]
            if "names、places" in prompt:
                return '{"technical_terms":["DeepSeek"]}'
            if "固定输出 Markdown" in prompt:
                return "## 总结\n校对后文本\n\n## 关键要点\n- 观点一"
            return "校对后文本"

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_api_key="dummy",
        llm_summary_min_chars=0,
    )
    terms = TerminologyStore(settings.terms_path)
    terms.save(TermsPayload(terms=[Term(incorrect="deep seek", correct="DeepSeek", context="AI 平台")]))
    processor = LLMProcessor(settings, terms, client=FakeClient())
    result = processor.process(
        metadata={"title": "deep seek 发布"},
        raw_transcript="deep seek 很强",
        options=JobOptions(),
    )
    assert result["polished_text"] == "校对后文本"
    assert result["key_points"] == ["观点一"]
    assert result["llm_detail"]["key_info"]["technical_terms"] == ["DeepSeek"]


def test_llm_long_text_is_split_and_merged_in_order(tmp_path: Path) -> None:
    class RecordingClient:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def __init__(self) -> None:
            self.calibration_calls = 0

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            prompt = messages[-1]["content"]
            if "names、places" in prompt:
                return "{}"
            self.calibration_calls += 1
            return f"chunk-{self.calibration_calls}"

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_api_key="dummy",
        llm_segment_size=12,
        llm_quality_min_ratio=0.0,
        llm_quality_max_ratio=100.0,
    )
    client = RecordingClient()
    processor = LLMProcessor(settings, TerminologyStore(settings.terms_path), client=client)
    result = processor.process(
        metadata={"title": "long"},
        raw_transcript="第一段内容很长。第二段内容也很长。第三段内容继续很长。",
        options=JobOptions(summary=False),
    )

    assert client.calibration_calls > 1
    assert result["polished_text"] == "\n\n".join(
        f"chunk-{index}" for index in range(1, client.calibration_calls + 1)
    )
    assert result["llm_detail"]["calibration"]["total_chunks"] == client.calibration_calls


def test_speaker_inference_adds_mapping_and_structured_transcript(tmp_path: Path) -> None:
    class SpeakerClient:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            prompt = messages[-1]["content"]
            if "names、places" in prompt:
                return "{}"
            if "speaker_mapping" in prompt:
                return '{"speaker_mapping":{"Speaker1":"张三"},"confidence":{"Speaker1":0.9},"source_labels":["Speaker1"]}'
            if "calibrated_dialogs" in prompt:
                return '{"calibrated_dialogs":[{"speaker_label":"Speaker1","text":"你好。"}]}'
            return "unexpected"

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_api_key="dummy",
        llm_quality_min_ratio=0.0,
        llm_quality_max_ratio=100.0,
    )
    processor = LLMProcessor(settings, TerminologyStore(settings.terms_path), client=SpeakerClient())
    result = processor.process(
        metadata={"title": "访谈"},
        raw_transcript="Speaker1: 你好",
        segments=[Segment(start=0, end=1, speaker="Speaker1", text="你好")],
        options=JobOptions(summary=False),
    )

    assert result["speaker_mapping"] == {"Speaker1": "张三"}
    assert result["structured_transcript"][0]["speaker_label"] == "Speaker1"
    assert result["structured_transcript"][0]["speaker_name"] == "张三"
    assert result["structured_transcript"][0]["text"] == "你好。"
    assert result["polished_text"] == "张三: 你好。"
    assert result["llm_detail"]["calibration"]["mode"] == "structured_dialog"


def test_structured_dialog_summary_uses_strict_text_and_public_text_is_merged(tmp_path: Path) -> None:
    class DialogClient:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def __init__(self) -> None:
            self.summary_prompt = ""

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            prompt = messages[-1]["content"]
            if "names、places" in prompt:
                return "{}"
            if "speaker_mapping" in prompt:
                return '{"speaker_mapping":{"Speaker1":"张三"},"confidence":{"Speaker1":0.9},"source_labels":["Speaker1"]}'
            if "calibrated_dialogs" in prompt:
                return (
                    '{"calibrated_dialogs":['
                    '{"speaker_label":"Speaker1","text":"你好。"},'
                    '{"speaker_label":"Speaker1","text":"继续。"}'
                    ']}'
                )
            if "固定输出 Markdown" in prompt:
                self.summary_prompt = prompt
                return "## 总结\n总结\n\n## 关键要点\n- A"
            return "unexpected"

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_api_key="dummy",
        llm_model="deepseek-test-model",
        llm_summary_min_chars=0,
        llm_quality_min_ratio=0.0,
        llm_quality_max_ratio=100.0,
    )
    client = DialogClient()
    processor = LLMProcessor(settings, TerminologyStore(settings.terms_path), client=client)
    result = processor.process(
        metadata={"title": "访谈"},
        raw_transcript="Speaker1: 你好\nSpeaker1: 继续",
        segments=[
            Segment(start=0.0, end=0.5, speaker="Speaker1", text="你好"),
            Segment(start=0.6, end=1.0, speaker="Speaker1", text="继续"),
        ],
        options=JobOptions(llm_polish=True, summary=True),
    )

    assert len(result["structured_transcript"]) == 2
    assert result["polished_text"] == "张三: 你好。继续。"
    assert "张三: 你好。\n张三: 继续。" in client.summary_prompt
    assert "张三: 你好。继续。" not in client.summary_prompt


def test_speaker_inference_invalid_json_keeps_original_speaker(tmp_path: Path) -> None:
    class InvalidSpeakerClient:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            prompt = messages[-1]["content"]
            if "names、places" in prompt:
                return "{}"
            if "speaker_mapping" in prompt:
                return "not json"
            if "calibrated_dialogs" in prompt:
                return '{"calibrated_dialogs":[{"speaker_label":"Speaker1","text":"你好"}]}'
            return "Speaker1: 你好"

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_api_key="dummy",
        llm_quality_min_ratio=0.0,
        llm_quality_max_ratio=100.0,
    )
    processor = LLMProcessor(settings, TerminologyStore(settings.terms_path), client=InvalidSpeakerClient())
    result = processor.process(
        metadata={},
        raw_transcript="Speaker1: 你好",
        segments=[Segment(start=0, end=1, speaker="Speaker1", text="你好")],
        options=JobOptions(summary=False),
    )

    assert result["speaker_mapping"] == {}
    assert "speaker_mapping_invalid_json" in result["quality_warnings"]


def test_speaker_inference_accepts_scalar_confidence_as_uncertain(tmp_path: Path) -> None:
    class ScalarConfidenceClient:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            prompt = messages[-1]["content"]
            if "names、places" in prompt:
                return "{}"
            if "speaker_mapping" in prompt:
                return '{"speaker_mapping":{},"confidence":0,"source_labels":["Speaker1"]}'
            if "calibrated_dialogs" in prompt:
                return '{"calibrated_dialogs":[{"speaker_label":"Speaker1","text":"你好"}]}'
            return "Speaker1: 你好"

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_api_key="dummy",
        llm_quality_min_ratio=0.0,
        llm_quality_max_ratio=100.0,
    )
    processor = LLMProcessor(settings, TerminologyStore(settings.terms_path), client=ScalarConfidenceClient())
    result = processor.process(
        metadata={},
        raw_transcript="Speaker1: 你好",
        segments=[Segment(start=0, end=1, speaker="Speaker1", text="你好")],
        options=JobOptions(summary=False),
    )

    assert result["speaker_mapping"] == {}
    assert "speaker_mapping_invalid_json" not in result["quality_warnings"]
    assert result["llm_detail"]["speaker_inference"]["source_labels"] == ["Speaker1"]


def test_empty_calibration_falls_back_to_raw_text(tmp_path: Path) -> None:
    class EmptyClient:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            prompt = messages[-1]["content"]
            if "names、places" in prompt:
                return "{}"
            return ""

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_api_key="dummy",
    )
    processor = LLMProcessor(settings, TerminologyStore(settings.terms_path), client=EmptyClient())
    result = processor.process(metadata={}, raw_transcript="hello", options=JobOptions(summary=False))

    assert result["polished_text"] == "hello"
    assert result["llm_detail"]["calibration"]["fallback_count"] == 1
    assert "polished_text_empty" in result["quality_warnings"]


def test_llm_processor_records_usage_by_purpose(tmp_path: Path) -> None:
    class UsageClient:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0):
            prompt = messages[-1]["content"]
            if "names、places" in prompt:
                content = "{}"
            elif "固定输出 Markdown" in prompt:
                content = "## 总结\n总结\n\n## 关键要点\n- A"
            else:
                content = "校对后文本"
            return LLMChatResult(
                content=content,
                provider="fake",
                model=model,
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                duration_ms=100,
            )

    class RecordingMetrics:
        def __init__(self) -> None:
            self.items: list[dict] = []

        def record_llm_usage(self, **kwargs) -> None:
            self.items.append(kwargs)

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_api_key="dummy",
        llm_model="deepseek-test-model",
        llm_summary_min_chars=0,
        llm_quality_min_ratio=0.0,
        llm_quality_max_ratio=100.0,
    )
    metrics = RecordingMetrics()
    processor = LLMProcessor(settings, TerminologyStore(settings.terms_path), client=UsageClient())

    result = processor.process(
        metadata={},
        raw_transcript="hello",
        options=JobOptions(llm_polish=True, summary=True),
        metrics=metrics,
    )

    assert result["summary"] == "## 总结\n总结\n\n## 关键要点\n- A"
    assert [item["purpose"] for item in metrics.items] == ["key_info", "calibration", "summary"]
    assert {item["model"] for item in metrics.items} == {"deepseek-test-model"}
    assert sum(item["total_tokens"] for item in metrics.items) == 45
    assert result["llm_detail"]["models"] == {"model": "deepseek-test-model"}


def test_summary_only_does_not_trigger_calibration(tmp_path: Path) -> None:
    class SummaryOnlyClient:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def __init__(self) -> None:
            self.prompts: list[str] = []

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            prompt = messages[-1]["content"]
            self.prompts.append(prompt)
            if "names、places" in prompt:
                return "{}"
            if "固定输出 Markdown" in prompt:
                return "## 总结\n总结\n\n## 关键要点\n- A"
            return "校对不应发生"

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_api_key="dummy",
        llm_summary_min_chars=0,
    )
    client = SummaryOnlyClient()
    processor = LLMProcessor(settings, TerminologyStore(settings.terms_path), client=client)
    result = processor.process(
        metadata={"title": "访谈"},
        raw_transcript="原始内容。",
        options=JobOptions(llm_polish=False, summary=True),
    )

    assert result["polished_text"] == "原始内容。"
    assert result["summary"]
    assert all("待校对文本" not in prompt for prompt in client.prompts)
    assert result["llm_detail"]["calibration"]["mode"] == "none"


def test_llm_processor_keeps_summary_when_summary_chunk_partially_fails(tmp_path: Path) -> None:
    class PartialSummaryChunkClient:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def __init__(self) -> None:
            self.summary_chunk_calls = 0

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            prompt = messages[-1]["content"]
            if "names、places" in prompt:
                return "{}"
            if "转录片段" in prompt:
                self.summary_chunk_calls += 1
                if self.summary_chunk_calls == 2:
                    raise RuntimeError("summary chunk failed")
                return f"- chunk {self.summary_chunk_calls}"
            if "固定输出 Markdown" in prompt:
                return "## 总结\n最终总结\n\n## 关键要点\n- A"
            return "unexpected"

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_api_key="dummy",
        llm_summary_min_chars=0,
        llm_summary_chunk_threshold=20,
        llm_segment_size=10,
    )
    client = PartialSummaryChunkClient()
    processor = LLMProcessor(settings, TerminologyStore(settings.terms_path), client=client)
    result = processor.process(
        metadata={"title": "访谈"},
        raw_transcript="第一段内容很长。第二段内容也很长。第三段内容继续很长。第四段内容还是很长。",
        options=JobOptions(llm_polish=False, summary=True),
    )

    assert result["summary"] == "## 总结\n最终总结\n\n## 关键要点\n- A"
    assert "summary_chunk_failed" in result["quality_warnings"]
    assert "summary_partial_chunks" in result["quality_warnings"]
    assert "summary_failed" not in result["quality_warnings"]
    assert result["llm_detail"]["calibration"]["mode"] == "none"


def test_llm_processor_carries_summary_final_fallback_warnings(tmp_path: Path) -> None:
    class FinalSummaryFailureClient:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def __init__(self) -> None:
            self.summary_chunk_calls = 0

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            prompt = messages[-1]["content"]
            if "names、places" in prompt:
                return "{}"
            if "转录片段" in prompt:
                self.summary_chunk_calls += 1
                if self.summary_chunk_calls == 1:
                    raise RuntimeError("summary chunk failed")
                return f"- chunk {self.summary_chunk_calls}"
            if "固定输出 Markdown" in prompt:
                raise RuntimeError("summary final failed")
            return "unexpected"

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_api_key="dummy",
        llm_summary_min_chars=0,
        llm_summary_chunk_threshold=20,
        llm_segment_size=10,
    )
    processor = LLMProcessor(settings, TerminologyStore(settings.terms_path), client=FinalSummaryFailureClient())
    result = processor.process(
        metadata={"title": "访谈"},
        raw_transcript="第一段内容很长。第二段内容也很长。第三段内容继续很长。第四段内容还是很长。",
        options=JobOptions(llm_polish=False, summary=True),
    )

    assert result["summary"] == "- chunk 2\n\n- chunk 3\n\n- chunk 4"
    assert result["quality_warnings"] == [
        "summary_chunk_failed",
        "summary_partial_chunks",
        "summary_final_failed",
        "summary_fallback_to_chunk_summaries",
    ]
    assert "summary_failed" not in result["quality_warnings"]
