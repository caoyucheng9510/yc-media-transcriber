from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.downloaders.base import DownloadResult
from app.jobs.processor import JobProcessor
from app.schemas import JobOptions, Segment
from app.source_resolver import ResolvedSource
from app.storage import SQLiteStore


class CountingTranscriber:
    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, audio_path: Path, options: JobOptions) -> list[Segment]:
        self.calls += 1
        assert audio_path.exists()
        return [Segment(start=0, end=1, text=f"transcript-{self.calls}")]


class CountingLLM:
    def __init__(self) -> None:
        self.calls = 0

    def process(
        self,
        *,
        metadata: dict,
        raw_transcript: str,
        options: JobOptions,
        segments: list[Segment],
        metrics: Any | None = None,
    ) -> dict[str, object]:
        self.calls += 1
        return {
            "polished_text": f"polished-{self.calls}: {raw_transcript}",
            "summary": None,
            "key_points": [],
            "speaker_mapping": {},
            "quality_warnings": [],
        }


class FakeDownloader:
    def __init__(self, sample_path: Path, *, source_fingerprint: str | None = None) -> None:
        self.sample_path = sample_path
        self.source_fingerprint = source_fingerprint
        self.calls = 0

    def download(
        self,
        source: ResolvedSource,
        job_temp_dir: Path,
        options: dict,
        metrics: Any | None = None,
    ) -> DownloadResult:
        self.calls += 1
        return DownloadResult(
            source_path=self.sample_path,
            metadata={
                "platform": source.platform,
                "title": f"{source.platform}-title",
                "source_url": source.url,
                "media_id": source.media_id,
            },
            source_fingerprint=self.source_fingerprint or source.fingerprint,
        )


class FakeDownloaderFactory:
    def __init__(self, downloader: FakeDownloader) -> None:
        self.downloader = downloader

    def create(self, platform: str) -> FakeDownloader:
        return self.downloader


def test_upload_job_second_run_uses_asr_cache(tmp_path: Path, sample_wav: Path) -> None:
    settings, store, processor, transcriber, _ = _processor(tmp_path)
    options = JobOptions(llm_polish=False, summary=False)

    first = _process_job(
        store,
        processor,
        "job_1",
        "upload",
        str(sample_wav),
        options,
    )
    second = _process_job(
        store,
        processor,
        "job_2",
        "upload",
        str(sample_wav),
        options,
    )

    assert transcriber.calls == 1
    assert first["metadata"]["cache"]["hit"] is False
    assert second["metadata"]["cache"]["hit"] is True
    assert second["raw_transcript"] == "transcript-1"
    assert (settings.jobs_dir / "job_2" / "sample.wav.md").exists()
    assert (settings.jobs_dir / "job_2" / "sample.wav.pdf").exists()


def test_platform_job_second_run_skips_downloader_when_identity_is_stable(
    tmp_path: Path,
    sample_wav: Path,
) -> None:
    _, store, processor, transcriber, _ = _processor(tmp_path)
    downloader = FakeDownloader(sample_wav)
    processor.downloaders = FakeDownloaderFactory(downloader)
    options = JobOptions(llm_polish=False, summary=False)
    url = "https://www.youtube.com/watch?v=EN7frwQIbKc"

    first = _process_job(store, processor, "job_1", "url", url, options)
    second = _process_job(store, processor, "job_2", "url", url, options)

    assert downloader.calls == 1
    assert transcriber.calls == 1
    assert first["metadata"]["cache"]["hit"] is False
    assert second["metadata"]["cache"]["hit"] is True
    assert second["raw_transcript"] == "transcript-1"


def test_url_job_preserves_initial_creator_metadata(
    tmp_path: Path,
    sample_wav: Path,
) -> None:
    _, store, processor, _, _ = _processor(tmp_path)
    downloader = FakeDownloader(sample_wav)
    processor.downloaders = FakeDownloaderFactory(downloader)
    options = JobOptions(llm_polish=False, summary=False)
    store.create_job(
        "job_1",
        "url",
        "https://www.xiaohongshu.com/explore/0123456789abcdef01234567",
        options.model_dump(),
        metadata={"creator_import": {"work_id": "0123456789abcdef01234567"}},
        title="queued title",
    )

    processor.process("job_1")

    result = store.get_job("job_1").result
    assert result["metadata"]["creator_import"]["work_id"] == "0123456789abcdef01234567"
    assert result["metadata"]["title"] == "xiaohongshu-title"


def test_xiaohongshu_short_link_second_run_skips_downloader(
    tmp_path: Path,
    sample_wav: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.source_resolver.resolver.resolve_short_url",
        lambda url, *, allowed_platforms, timeout=8.0: (
            "https://www.xiaohongshu.com/explore/0123456789abcdef01234567"
        ),
    )
    _, store, processor, transcriber, _ = _processor(tmp_path)
    downloader = FakeDownloader(sample_wav)
    processor.downloaders = FakeDownloaderFactory(downloader)
    options = JobOptions(llm_polish=False, summary=False)
    url = "https://xhslink.com/o/AtInx9UjfoY"

    first = _process_job(store, processor, "job_1", "text", f"小红书分享 {url}", options)
    second = _process_job(store, processor, "job_2", "text", f"小红书分享 {url}", options)

    assert downloader.calls == 1
    assert transcriber.calls == 1
    assert first["metadata"]["cache"]["hit"] is False
    assert second["metadata"]["cache"]["hit"] is True


def test_douyin_short_link_second_run_skips_downloader(
    tmp_path: Path,
    sample_wav: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.source_resolver.resolver.resolve_short_url",
        lambda url, *, allowed_platforms, timeout=8.0: (
            "https://www.douyin.com/video/7333333333333333333"
        ),
    )
    _, store, processor, transcriber, _ = _processor(tmp_path)
    downloader = FakeDownloader(sample_wav)
    processor.downloaders = FakeDownloaderFactory(downloader)
    options = JobOptions(llm_polish=False, summary=False)
    url = "https://v.douyin.com/example/"

    _process_job(store, processor, "job_1", "url", url, options)
    second = _process_job(store, processor, "job_2", "url", url, options)

    assert downloader.calls == 1
    assert transcriber.calls == 1
    assert second["metadata"]["cache"]["hit"] is True


def test_youtube_short_and_watch_urls_share_cache_identity(
    tmp_path: Path,
    sample_wav: Path,
) -> None:
    _, store, processor, transcriber, _ = _processor(tmp_path)
    downloader = FakeDownloader(sample_wav)
    processor.downloaders = FakeDownloaderFactory(downloader)
    options = JobOptions(llm_polish=False, summary=False)

    _process_job(store, processor, "job_1", "url", "https://youtu.be/EN7frwQIbKc", options)
    second = _process_job(
        store,
        processor,
        "job_2",
        "url",
        "https://www.youtube.com/watch?v=EN7frwQIbKc",
        options,
    )

    assert downloader.calls == 1
    assert transcriber.calls == 1
    assert second["metadata"]["cache"]["hit"] is True


def test_bilibili_page_number_changes_cache_identity(
    tmp_path: Path,
    sample_wav: Path,
) -> None:
    _, store, processor, transcriber, _ = _processor(tmp_path)
    downloader = FakeDownloader(sample_wav)
    processor.downloaders = FakeDownloaderFactory(downloader)
    options = JobOptions(llm_polish=False, summary=False)

    first = _process_job(
        store,
        processor,
        "job_1",
        "url",
        "https://www.bilibili.com/video/BV1vd7D6UEf8/",
        options,
    )
    second = _process_job(
        store,
        processor,
        "job_2",
        "url",
        "https://www.bilibili.com/video/BV1vd7D6UEf8/?p=2",
        options,
    )
    third = _process_job(
        store,
        processor,
        "job_3",
        "url",
        "https://www.bilibili.com/video/BV1vd7D6UEf8/?p=2",
        options,
    )

    assert downloader.calls == 2
    assert transcriber.calls == 2
    assert first["metadata"]["cache"]["hit"] is False
    assert second["metadata"]["cache"]["hit"] is False
    assert third["metadata"]["cache"]["hit"] is True


def test_direct_url_cache_hit_still_downloads_but_skips_asr(
    tmp_path: Path,
    sample_wav: Path,
) -> None:
    _, store, processor, transcriber, _ = _processor(
        tmp_path,
        settings_kwargs={"app_allow_private_urls": True},
    )
    downloader = FakeDownloader(sample_wav, source_fingerprint="content-sha")
    processor.downloaders = FakeDownloaderFactory(downloader)
    options = JobOptions(llm_polish=False, summary=False)
    url = "http://127.0.0.1/audio.mp3"

    first = _process_job(store, processor, "job_1", "url", url, options)
    second = _process_job(store, processor, "job_2", "url", url, options)

    assert downloader.calls == 2
    assert transcriber.calls == 1
    assert first["metadata"]["cache"]["hit"] is False
    assert second["metadata"]["cache"]["hit"] is True


def test_cache_hit_still_runs_llm_when_requested(tmp_path: Path, sample_wav: Path) -> None:
    _, store, processor, transcriber, llm = _processor(tmp_path)

    _process_job(
        store,
        processor,
        "job_1",
        "upload",
        str(sample_wav),
        JobOptions(llm_polish=False, summary=False),
    )
    second = _process_job(
        store,
        processor,
        "job_2",
        "upload",
        str(sample_wav),
        JobOptions(llm_polish=True, summary=False),
    )

    assert transcriber.calls == 1
    assert llm.calls == 1
    assert second["metadata"]["cache"]["hit"] is True
    assert second["polished_text"] == "polished-1: transcript-1"


def test_missing_uploaded_source_file_fails_with_public_error(tmp_path: Path) -> None:
    _, store, processor, transcriber, _ = _processor(tmp_path)
    store.create_job(
        "job_missing",
        "upload",
        str(tmp_path / "missing.wav"),
        JobOptions(llm_polish=False, summary=False).model_dump(),
    )

    processor.process("job_missing")

    job = store.get_job("job_missing")
    assert job.status == "failed"
    assert job.error.code == "source_file_missing"
    assert job.error.stage == "normalizing"
    assert job.error.message == "上传文件不存在，请重新上传后再试。"
    assert transcriber.calls == 0


def test_invalid_cache_record_falls_back_to_transcribe(
    tmp_path: Path,
    sample_wav: Path,
) -> None:
    _, store, processor, transcriber, _ = _processor(tmp_path)
    options = JobOptions(llm_polish=False, summary=False)
    first = _process_job(store, processor, "job_1", "upload", str(sample_wav), options)
    cache_key = first["metadata"]["cache"]["cache_key"]
    record = store.get_media_cache_record(cache_key)
    Path(record["segments_path"]).write_text("not json", encoding="utf-8")

    second = _process_job(store, processor, "job_2", "upload", str(sample_wav), options)

    assert transcriber.calls == 2
    assert second["metadata"]["cache"]["hit"] is False
    assert second["raw_transcript"] == "transcript-2"


def _processor(
    tmp_path: Path,
    *,
    settings_kwargs: dict[str, Any] | None = None,
) -> tuple[Settings, SQLiteStore, JobProcessor, CountingTranscriber, CountingLLM]:
    data_dir = tmp_path / "data"
    settings = Settings(
        app_data_dir=data_dir,
        asr_engine="mock",
        asr_model_dir=data_dir / "models",
        terms_path=data_dir / "terms.json",
        **(settings_kwargs or {}),
    )
    settings.ensure_directories()
    store = SQLiteStore(settings.db_path)
    transcriber = CountingTranscriber()
    llm = CountingLLM()
    processor = JobProcessor(
        settings=settings,
        store=store,
        transcriber=transcriber,
        llm=llm,
    )
    return settings, store, processor, transcriber, llm


def _process_job(
    store: SQLiteStore,
    processor: JobProcessor,
    job_id: str,
    source_type: str,
    source_value: str,
    options: JobOptions,
) -> dict[str, Any]:
    store.create_job(job_id, source_type, source_value, options.model_dump())
    processor.process(job_id)
    job = store.get_job(job_id)
    assert job.status == "completed"
    assert job.result is not None
    return job.result
