from __future__ import annotations

import sqlite3
from pathlib import Path

from app.storage import SQLiteStore


def test_sqlite_store_persists_jobs_and_artifacts(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "app.sqlite")
    store.create_job(
        "job_1",
        "upload",
        "/tmp/a.wav",
        {"llm_polish": False},
        metadata={"creator_import": {"work_id": "note_1"}},
        title="queued title",
    )
    assert store.get_job("job_1").metadata["creator_import"]["work_id"] == "note_1"
    assert store.get_job("job_1").title == "queued title"
    store.update_job("job_1", status="completed", progress=100, result={"ok": True}, title="A")
    artifact = tmp_path / "document.md"
    artifact.write_text("# A", encoding="utf-8")
    store.save_artifact("job_1", "document_md", artifact, "text/markdown")

    job = store.get_job("job_1")
    assert job.status == "completed"
    assert job.result == {"ok": True}
    assert store.list_jobs(keyword="A")[0].id == "job_1"
    assert store.get_artifact("job_1", "document_md")["path"] == str(artifact)


def test_recover_interrupted_jobs_marks_non_terminal_failed(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "app.sqlite")
    store.create_job("job_queued", "upload", "/tmp/a.wav", {"llm_polish": False})
    store.create_job("job_running", "upload", "/tmp/b.wav", {"llm_polish": False})
    store.create_job("job_done", "upload", "/tmp/c.wav", {"llm_polish": False})
    store.update_job("job_running", status="transcribing", progress=50)
    store.update_job("job_done", status="completed", progress=100, result={"ok": True})

    recovered = store.recover_interrupted_jobs()

    assert recovered == 2
    assert store.get_job("job_queued").status == "failed"
    assert store.get_job("job_running").status == "failed"
    assert store.get_job("job_running").error.code == "job_interrupted"
    assert store.get_job("job_done").status == "completed"


def test_reset_job_for_retry_clears_failure_state_and_artifacts(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "app.sqlite")
    artifact = tmp_path / "document.md"
    artifact.write_text("# A", encoding="utf-8")
    store.create_job("job_1", "upload", "/tmp/a.wav", {"llm_polish": False})
    store.update_job(
        "job_1",
        status="failed",
        progress=100,
        metadata={"title": "A"},
        error={"code": "asr_failed", "message": "failed", "stage": "transcribing"},
        result={"ok": False},
        source_fingerprint="fingerprint",
    )
    store.save_artifact("job_1", "document_md", artifact, "text/markdown")

    retried = store.reset_job_for_retry("job_1")

    assert retried.status == "queued"
    assert retried.progress == 0
    assert retried.metadata == {}
    assert retried.error is None
    assert retried.result is None
    assert store.get_artifact("job_1", "document_md") is None


def test_delete_job_removes_record_and_artifacts(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "app.sqlite")
    artifact = tmp_path / "document.md"
    artifact.write_text("# A", encoding="utf-8")
    store.create_job("job_1", "upload", "/tmp/a.wav", {"llm_polish": False})
    store.save_artifact("job_1", "document_md", artifact, "text/markdown")

    store.delete_job("job_1")

    try:
        store.get_job("job_1")
    except KeyError:
        pass
    else:
        raise AssertionError("job_1 should have been deleted")
    assert store.get_artifact("job_1", "document_md") is None


def test_sqlite_store_rebuilds_legacy_media_cache_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE media_cache (
                cache_key TEXT PRIMARY KEY,
                source_fingerprint TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )

    SQLiteStore(db_path)

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(media_cache)").fetchall()}
    assert "artifact_path" not in columns
    assert "cache_dir" in columns
    assert "segments_path" in columns
    assert "raw_transcript_path" in columns
    assert "transcript_txt_path" not in columns
    assert "transcript_srt_path" not in columns
    assert "updated_at" in columns
