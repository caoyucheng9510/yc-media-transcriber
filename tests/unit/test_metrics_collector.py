from __future__ import annotations

import time
from pathlib import Path

from app.config import Settings
from app.metrics import JobMetricsCollector
from app.storage import SQLiteStore


def test_metrics_collector_flushes_stage_and_usage(tmp_path: Path) -> None:
    settings = Settings(app_data_dir=tmp_path, terms_path=tmp_path / "terms.json")
    store = SQLiteStore(tmp_path / "app.sqlite")
    job = store.create_job("job_1", "upload", "/tmp/a.wav", {"llm_polish": False})
    collector = JobMetricsCollector("job_1", store, settings)

    collector.start(created_at=job.created_at, source_type=job.source_type)
    with collector.stage("transcribing"):
        time.sleep(0.001)
    collector.record_media_info(duration_seconds=2.0, size_bytes=1024)
    collector.record_http_request(
        provider="direct_media",
        method="GET",
        endpoint="cdn.example.com.mp3",
        status_code=200,
        duration_ms=50,
        request_kind="media_download",
        bytes_received=1024,
    )
    collector.record_tikhub_call(endpoint="/api/test")
    collector.record_llm_usage(
        provider="deepseek",
        model="deepseek-v4-flash",
        purpose="summary",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        duration_ms=100,
    )
    collector.record_cache_hit(False)
    collector.finish(status="completed", metadata={"platform": "local_file"})

    metrics = store.list_job_metrics()
    assert len(metrics) == 1
    item = metrics[0]
    assert item["job_id"] == "job_1"
    assert item["status"] == "completed"
    assert item["platform"] == "local_file"
    assert item["media_duration_seconds"] == 2.0
    assert item["media_size_bytes"] == 1024
    assert item["download_bytes"] == 1024
    assert item["http_requests_total"] == 1
    assert item["tikhub_calls_total"] == 1
    assert item["llm_calls_total"] == 1
    assert item["llm_total_tokens"] == 15
    assert item["cache_hit"] is False
    assert item["asr_rtf"] is not None


def test_metrics_collector_disabled_does_not_write(tmp_path: Path) -> None:
    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        metrics_enabled=False,
    )
    store = SQLiteStore(tmp_path / "app.sqlite")
    job = store.create_job("job_1", "upload", "/tmp/a.wav", {})
    collector = JobMetricsCollector("job_1", store, settings)

    collector.start(created_at=job.created_at, source_type=job.source_type)
    collector.record_cache_hit(True)
    collector.finish(status="completed", metadata={})

    assert store.list_job_metrics() == []


def test_metrics_flush_failure_does_not_raise(tmp_path: Path) -> None:
    class FailingStore:
        def upsert_job_metrics(self, record: dict) -> None:
            raise RuntimeError("db unavailable")

    settings = Settings(app_data_dir=tmp_path, terms_path=tmp_path / "terms.json")
    collector = JobMetricsCollector("job_1", FailingStore(), settings)  # type: ignore[arg-type]

    collector.start(created_at="2026-01-01T00:00:00+00:00", source_type="upload")
    collector.finish(status="failed", metadata={}, error={"code": "x", "stage": "processing"})
