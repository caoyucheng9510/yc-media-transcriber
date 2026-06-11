from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.llm.summary import SummaryProcessor


class ScriptedSummaryClient:
    available = True
    provider_name = "fake"
    missing_configuration_reason = None

    def __init__(
        self,
        *,
        chunk_results: list[object] | None = None,
        final_result: object = "## 总结\n最终总结\n\n## 关键要点\n- A",
    ) -> None:
        self.chunk_results = list(chunk_results or [])
        self.final_result = final_result
        self.chunk_calls = 0
        self.final_calls = 0
        self.prompts: list[str] = []

    def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
        prompt = messages[-1]["content"]
        self.prompts.append(prompt)
        if "转录片段" in prompt:
            self.chunk_calls += 1
            result = self.chunk_results.pop(0) if self.chunk_results else "- chunk point"
        else:
            self.final_calls += 1
            result = self.final_result
        if isinstance(result, Exception):
            raise result
        return str(result)


def _chunk_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_summary_min_chars=0,
        llm_summary_chunk_threshold=20,
        llm_segment_size=10,
    )


def _long_text() -> str:
    return "第一段内容很长。第二段内容也很长。第三段内容继续很长。第四段内容还是很长。"


def test_summary_uses_single_speaker_prompt(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def __init__(self) -> None:
            self.system_prompts: list[str] = []

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            self.system_prompts.append(messages[0]["content"])
            return "## 总结\n单人总结\n\n## 关键要点\n- A"

    settings = Settings(app_data_dir=tmp_path, terms_path=tmp_path / "terms.json", llm_summary_min_chars=0)
    client = Client()
    result = SummaryProcessor(settings, client).summarize(
        text="文本",
        metadata={},
        speaker_mapping={},
        has_multiple_speakers=False,
    )

    assert result.summary
    assert "单人转录稿" in client.system_prompts[0]


def test_summary_uses_multi_speaker_prompt(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def __init__(self) -> None:
            self.system_prompts: list[str] = []

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            self.system_prompts.append(messages[0]["content"])
            return "## 总结\n多人总结\n\n## 关键要点\n- A"

    settings = Settings(app_data_dir=tmp_path, terms_path=tmp_path / "terms.json", llm_summary_min_chars=0)
    client = Client()
    SummaryProcessor(settings, client).summarize(
        text="文本",
        metadata={},
        speaker_mapping={"Speaker1": "张三", "Speaker2": "李四"},
        has_multiple_speakers=True,
    )

    assert "多人对话转录稿" in client.system_prompts[0]


def test_short_summary_is_skipped(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            raise AssertionError("summary should be skipped")

    settings = Settings(app_data_dir=tmp_path, terms_path=tmp_path / "terms.json", llm_summary_min_chars=100)
    result = SummaryProcessor(settings, Client()).summarize(
        text="短文本",
        metadata={},
        speaker_mapping={},
        has_multiple_speakers=False,
    )

    assert result.summary is None
    assert result.warnings == ["summary_skipped_short_text"]


def test_long_summary_runs_chunk_then_final_summary(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def __init__(self) -> None:
            self.prompts: list[str] = []

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            prompt = messages[-1]["content"]
            self.prompts.append(prompt)
            if "转录片段" in prompt:
                return "- chunk point"
            return "## 总结\n最终总结\n\n## 关键要点\n- A"

    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        llm_summary_min_chars=0,
        llm_summary_chunk_threshold=20,
        llm_segment_size=10,
    )
    client = Client()
    result = SummaryProcessor(settings, client).summarize(
        text="第一段很长。第二段很长。第三段很长。第四段很长。",
        metadata={},
        speaker_mapping={},
        has_multiple_speakers=False,
    )

    assert result.summary == "## 总结\n最终总结\n\n## 关键要点\n- A"
    assert any("转录片段" in prompt for prompt in client.prompts)
    assert client.prompts[-1].count("chunk point") >= 1


def test_long_summary_chunk_failure_continues_and_final_summary_succeeds(tmp_path: Path) -> None:
    client = ScriptedSummaryClient(
        chunk_results=[
            "- chunk 1",
            RuntimeError("chunk failed"),
            "- chunk 3",
            "- chunk 4",
        ],
    )
    result = SummaryProcessor(_chunk_settings(tmp_path), client).summarize(
        text=_long_text(),
        metadata={},
        speaker_mapping={},
        has_multiple_speakers=False,
    )

    assert result.summary == "## 总结\n最终总结\n\n## 关键要点\n- A"
    assert client.chunk_calls == 4
    assert client.final_calls == 1
    assert result.warnings == ["summary_chunk_failed", "summary_partial_chunks"]


def test_long_summary_empty_chunk_continues_and_final_summary_succeeds(tmp_path: Path) -> None:
    client = ScriptedSummaryClient(
        chunk_results=[
            "",
            "- chunk 2",
            "- chunk 3",
            "- chunk 4",
        ],
    )
    result = SummaryProcessor(_chunk_settings(tmp_path), client).summarize(
        text=_long_text(),
        metadata={},
        speaker_mapping={},
        has_multiple_speakers=False,
    )

    assert result.summary == "## 总结\n最终总结\n\n## 关键要点\n- A"
    assert client.chunk_calls == 4
    assert client.final_calls == 1
    assert "- chunk 2" in client.prompts[-1]
    assert result.warnings == ["summary_chunk_empty", "summary_partial_chunks"]


def test_long_summary_all_chunks_fail_returns_summary_failed_without_final_call(tmp_path: Path) -> None:
    client = ScriptedSummaryClient(
        chunk_results=[
            RuntimeError("chunk failed"),
            RuntimeError("chunk failed"),
            RuntimeError("chunk failed"),
            RuntimeError("chunk failed"),
        ],
    )
    result = SummaryProcessor(_chunk_settings(tmp_path), client).summarize(
        text=_long_text(),
        metadata={},
        speaker_mapping={},
        has_multiple_speakers=False,
    )

    assert result.summary is None
    assert client.chunk_calls == 4
    assert client.final_calls == 0
    assert result.warnings == ["summary_chunk_failed", "summary_failed"]


def test_long_summary_all_chunks_empty_returns_summary_failed_without_final_call(tmp_path: Path) -> None:
    client = ScriptedSummaryClient(chunk_results=[" ", "", "\n", "\t"])
    result = SummaryProcessor(_chunk_settings(tmp_path), client).summarize(
        text=_long_text(),
        metadata={},
        speaker_mapping={},
        has_multiple_speakers=False,
    )

    assert result.summary is None
    assert client.chunk_calls == 4
    assert client.final_calls == 0
    assert result.warnings == ["summary_chunk_empty", "summary_failed"]


def test_long_summary_final_failure_falls_back_to_chunk_summaries(tmp_path: Path) -> None:
    client = ScriptedSummaryClient(
        chunk_results=["- chunk 1", "- chunk 2", "- chunk 3", "- chunk 4"],
        final_result=RuntimeError("final failed"),
    )
    result = SummaryProcessor(_chunk_settings(tmp_path), client).summarize(
        text=_long_text(),
        metadata={},
        speaker_mapping={},
        has_multiple_speakers=False,
    )

    assert result.summary == "- chunk 1\n\n- chunk 2\n\n- chunk 3\n\n- chunk 4"
    assert result.warnings == ["summary_final_failed", "summary_fallback_to_chunk_summaries"]
    assert "summary_failed" not in result.warnings


def test_long_summary_final_empty_falls_back_to_chunk_summaries(tmp_path: Path) -> None:
    client = ScriptedSummaryClient(
        chunk_results=["- chunk 1", "- chunk 2", "- chunk 3", "- chunk 4"],
        final_result=" ",
    )
    result = SummaryProcessor(_chunk_settings(tmp_path), client).summarize(
        text=_long_text(),
        metadata={},
        speaker_mapping={},
        has_multiple_speakers=False,
    )

    assert result.summary == "- chunk 1\n\n- chunk 2\n\n- chunk 3\n\n- chunk 4"
    assert result.warnings == ["summary_final_empty", "summary_fallback_to_chunk_summaries"]
    assert "summary_failed" not in result.warnings


def test_long_summary_chunk_warnings_are_deduped_in_first_seen_order(tmp_path: Path) -> None:
    client = ScriptedSummaryClient(
        chunk_results=[
            RuntimeError("chunk failed"),
            RuntimeError("chunk failed"),
            "",
            "- chunk 4",
        ],
    )
    result = SummaryProcessor(_chunk_settings(tmp_path), client).summarize(
        text=_long_text(),
        metadata={},
        speaker_mapping={},
        has_multiple_speakers=False,
    )

    assert result.summary == "## 总结\n最终总结\n\n## 关键要点\n- A"
    assert result.warnings == [
        "summary_chunk_failed",
        "summary_chunk_empty",
        "summary_partial_chunks",
    ]


def test_summary_failure_returns_warning(tmp_path: Path) -> None:
    class Client:
        available = True
        provider_name = "fake"
        missing_configuration_reason = None

        def chat(self, *, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
            raise RuntimeError("boom")

    settings = Settings(app_data_dir=tmp_path, terms_path=tmp_path / "terms.json", llm_summary_min_chars=0)
    result = SummaryProcessor(settings, Client()).summarize(
        text="文本",
        metadata={},
        speaker_mapping={},
        has_multiple_speakers=False,
    )

    assert result.summary is None
    assert result.warnings == ["summary_failed"]
