from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schemas import JobRecord


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


NON_TERMINAL_STATUSES = ("queued", "downloading", "normalizing", "transcribing", "llm_processing")

MEDIA_CACHE_COLUMNS = {
    "cache_key",
    "source_fingerprint",
    "source_identity",
    "platform",
    "media_id",
    "asr_engine",
    "speaker_diarization",
    "cache_dir",
    "segments_path",
    "raw_transcript_path",
    "metadata_json",
    "created_at",
    "updated_at",
}


class SQLiteStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    source_value TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    options_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    error_json TEXT,
                    result_json TEXT,
                    source_fingerprint TEXT,
                    title TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
                CREATE INDEX IF NOT EXISTS idx_jobs_source_fingerprint
                    ON jobs(source_fingerprint);

                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT 'text/plain',
                    created_at TEXT NOT NULL,
                    UNIQUE(job_id, type),
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_metrics (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    platform TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL,

                    queue_wait_ms INTEGER,
                    total_duration_ms INTEGER,

                    media_duration_seconds REAL,
                    media_size_bytes INTEGER,

                    download_seconds REAL,
                    download_bytes INTEGER,
                    download_mb_per_second REAL,

                    normalizing_seconds REAL,
                    normalizing_rtf REAL,

                    transcribing_seconds REAL,
                    asr_rtf REAL,

                    llm_seconds REAL,
                    llm_calls_total INTEGER NOT NULL DEFAULT 0,
                    llm_prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    llm_completion_tokens INTEGER NOT NULL DEFAULT 0,
                    llm_total_tokens INTEGER NOT NULL DEFAULT 0,
                    llm_tokens_per_second REAL,

                    http_requests_total INTEGER NOT NULL DEFAULT 0,
                    tikhub_calls_total INTEGER NOT NULL DEFAULT 0,
                    tikhub_http_attempts_total INTEGER NOT NULL DEFAULT 0,
                    yt_dlp_invocations INTEGER NOT NULL DEFAULT 0,

                    cache_hit INTEGER,

                    stage_durations_json TEXT NOT NULL DEFAULT '{}',
                    http_requests_json TEXT NOT NULL DEFAULT '{}',
                    llm_usage_json TEXT NOT NULL DEFAULT '{}',
                    detail_json TEXT NOT NULL DEFAULT '{}',

                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_job_metrics_created_at
                    ON job_metrics(created_at);
                CREATE INDEX IF NOT EXISTS idx_job_metrics_status
                    ON job_metrics(status);
                CREATE INDEX IF NOT EXISTS idx_job_metrics_platform
                    ON job_metrics(platform);
                """
            )
            self._init_media_cache_schema(conn)

    def _init_media_cache_schema(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'media_cache'"
        ).fetchone()
        if row is not None:
            columns = {
                item["name"]
                for item in conn.execute("PRAGMA table_info(media_cache)").fetchall()
            }
            if columns != MEDIA_CACHE_COLUMNS:
                conn.execute("DROP TABLE media_cache")

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS media_cache (
                cache_key TEXT PRIMARY KEY,
                source_fingerprint TEXT NOT NULL,
                source_identity TEXT,
                platform TEXT,
                media_id TEXT,
                asr_engine TEXT NOT NULL,
                speaker_diarization INTEGER NOT NULL DEFAULT 0,
                cache_dir TEXT NOT NULL,
                segments_path TEXT NOT NULL,
                raw_transcript_path TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_media_cache_source_fingerprint
                ON media_cache(source_fingerprint);

            CREATE INDEX IF NOT EXISTS idx_media_cache_source_identity
                ON media_cache(source_identity);
            """
        )

    def create_job(
        self,
        job_id: str,
        source_type: str,
        source_value: str,
        options: dict[str, Any],
        source_fingerprint: str | None = None,
        metadata: dict[str, Any] | None = None,
        title: str | None = None,
    ) -> JobRecord:
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, source_type, source_value, status, progress, options_json,
                    metadata_json, source_fingerprint, title, created_at, updated_at
                )
                VALUES (?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    source_type,
                    source_value,
                    _json_dump(options),
                    _json_dump(metadata or {}),
                    source_fingerprint,
                    title,
                    now,
                    now,
                ),
            )
        return self.get_job(job_id)

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        metadata: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        source_fingerprint: str | None = None,
        title: str | None = None,
    ) -> None:
        fields: list[str] = ["updated_at = ?"]
        values: list[Any] = [utc_now()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if progress is not None:
            fields.append("progress = ?")
            values.append(progress)
        if metadata is not None:
            fields.append("metadata_json = ?")
            values.append(_json_dump(metadata))
        if error is not None:
            fields.append("error_json = ?")
            values.append(_json_dump(error))
        if result is not None:
            fields.append("result_json = ?")
            values.append(_json_dump(result))
        if source_fingerprint is not None:
            fields.append("source_fingerprint = ?")
            values.append(source_fingerprint)
        if title is not None:
            fields.append("title = ?")
            values.append(title)
        values.append(job_id)
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)

    def get_job(self, job_id: str) -> JobRecord:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._row_to_job(row)

    def list_jobs(
        self,
        *,
        status: str | None = None,
        keyword: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JobRecord]:
        where: list[str] = []
        values: list[Any] = []
        if status:
            where.append("status = ?")
            values.append(status)
        if keyword:
            where.append("(title LIKE ? OR source_value LIKE ?)")
            values.extend([f"%{keyword}%", f"%{keyword}%"])
        sql = "SELECT * FROM jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        values.extend([limit, offset])
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, values).fetchall()
        return [self._row_to_job(row) for row in rows]

    def save_artifact(
        self,
        job_id: str,
        artifact_type: str,
        path: Path,
        mime_type: str = "text/plain",
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (job_id, type, path, mime_type, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(job_id, type)
                DO UPDATE SET path = excluded.path, mime_type = excluded.mime_type
                """,
                (job_id, artifact_type, str(path), mime_type, utc_now()),
            )

    def list_artifacts(self, job_id: str) -> dict[str, dict[str, str]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT type, path, mime_type FROM artifacts WHERE job_id = ?",
                (job_id,),
            ).fetchall()
        return {
            row["type"]: {"path": row["path"], "mime_type": row["mime_type"]}
            for row in rows
        }

    def get_artifact(self, job_id: str, artifact_type: str) -> dict[str, str] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT type, path, mime_type FROM artifacts WHERE job_id = ? AND type = ?",
                (job_id, artifact_type),
            ).fetchone()
        if row is None:
            return None
        return {"type": row["type"], "path": row["path"], "mime_type": row["mime_type"]}

    def reset_job_for_retry(self, job_id: str) -> JobRecord:
        now = utc_now()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            conn.execute("DELETE FROM artifacts WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM job_metrics WHERE job_id = ?", (job_id,))
            conn.execute(
                """
                UPDATE jobs
                SET status = 'queued',
                    progress = 0,
                    metadata_json = '{}',
                    error_json = NULL,
                    result_json = NULL,
                    source_fingerprint = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, job_id),
            )
        return self.get_job(job_id)

    def delete_job(self, job_id: str) -> None:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        if cursor.rowcount == 0:
            raise KeyError(job_id)

    def upsert_media_cache(self, record: dict[str, Any]) -> None:
        now = utc_now()
        metadata_json = _json_dump(record.get("metadata") or {})
        values = {
            "cache_key": record["cache_key"],
            "source_fingerprint": record["source_fingerprint"],
            "source_identity": record.get("source_identity"),
            "platform": record.get("platform"),
            "media_id": record.get("media_id"),
            "asr_engine": record["asr_engine"],
            "speaker_diarization": 1 if record.get("speaker_diarization") else 0,
            "cache_dir": record["cache_dir"],
            "segments_path": record["segments_path"],
            "raw_transcript_path": record["raw_transcript_path"],
            "metadata_json": metadata_json,
            "created_at": record.get("created_at") or now,
            "updated_at": now,
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO media_cache (
                    cache_key, source_fingerprint, source_identity, platform, media_id,
                    asr_engine, speaker_diarization, cache_dir,
                    segments_path, raw_transcript_path, metadata_json, created_at,
                    updated_at
                )
                VALUES (
                    :cache_key, :source_fingerprint, :source_identity, :platform,
                    :media_id, :asr_engine, :speaker_diarization,
                    :cache_dir, :segments_path, :raw_transcript_path, :metadata_json,
                    :created_at, :updated_at
                )
                ON CONFLICT(cache_key) DO UPDATE SET
                    source_fingerprint = excluded.source_fingerprint,
                    source_identity = excluded.source_identity,
                    platform = excluded.platform,
                    media_id = excluded.media_id,
                    asr_engine = excluded.asr_engine,
                    speaker_diarization = excluded.speaker_diarization,
                    cache_dir = excluded.cache_dir,
                    segments_path = excluded.segments_path,
                    raw_transcript_path = excluded.raw_transcript_path,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                values,
            )

    def get_media_cache_record(self, cache_key: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM media_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_media_cache_record(row)

    def list_media_cache_records(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM media_cache ORDER BY created_at DESC").fetchall()
        return [self._row_to_media_cache_record(row) for row in rows]

    def _row_to_media_cache_record(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "cache_key": row["cache_key"],
            "source_fingerprint": row["source_fingerprint"],
            "source_identity": row["source_identity"],
            "platform": row["platform"],
            "media_id": row["media_id"],
            "asr_engine": row["asr_engine"],
            "speaker_diarization": bool(row["speaker_diarization"]),
            "cache_dir": row["cache_dir"],
            "segments_path": row["segments_path"],
            "raw_transcript_path": row["raw_transcript_path"],
            "metadata": _json_load(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def delete_media_cache(self, cache_key: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM media_cache WHERE cache_key = ?", (cache_key,))

    def recover_interrupted_jobs(self) -> int:
        error = {
            "code": "job_interrupted",
            "message": "任务在上次服务退出时中断。",
            "stage": "processing",
        }
        now = utc_now()
        placeholders = ", ".join("?" for _ in NON_TERMINAL_STATUSES)
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE jobs
                SET status = 'failed',
                    progress = 100,
                    error_json = ?,
                    updated_at = ?
                WHERE status IN ({placeholders})
                """,
                (_json_dump(error), now, *NON_TERMINAL_STATUSES),
            )
        return int(cursor.rowcount or 0)

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE
                SET value_json = excluded.value_json, updated_at = excluded.updated_at
                """,
                (key, _json_dump(value), utc_now()),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return _json_load(row["value_json"], default)

    def upsert_job_metrics(self, record: dict[str, Any]) -> None:
        values = dict(record)
        for key in (
            "stage_durations_json",
            "http_requests_json",
            "llm_usage_json",
            "detail_json",
        ):
            values[key] = _json_dump(values.get(key) or {})
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO job_metrics (
                    job_id, status, source_type, platform, created_at, started_at,
                    finished_at, updated_at, queue_wait_ms, total_duration_ms,
                    media_duration_seconds, media_size_bytes, download_seconds,
                    download_bytes, download_mb_per_second, normalizing_seconds,
                    normalizing_rtf, transcribing_seconds, asr_rtf, llm_seconds,
                    llm_calls_total, llm_prompt_tokens, llm_completion_tokens,
                    llm_total_tokens, llm_tokens_per_second, http_requests_total,
                    tikhub_calls_total, tikhub_http_attempts_total, yt_dlp_invocations,
                    cache_hit, stage_durations_json, http_requests_json,
                    llm_usage_json, detail_json
                )
                VALUES (
                    :job_id, :status, :source_type, :platform, :created_at,
                    :started_at, :finished_at, :updated_at, :queue_wait_ms,
                    :total_duration_ms, :media_duration_seconds, :media_size_bytes,
                    :download_seconds, :download_bytes, :download_mb_per_second,
                    :normalizing_seconds, :normalizing_rtf, :transcribing_seconds,
                    :asr_rtf, :llm_seconds, :llm_calls_total, :llm_prompt_tokens,
                    :llm_completion_tokens, :llm_total_tokens, :llm_tokens_per_second,
                    :http_requests_total, :tikhub_calls_total,
                    :tikhub_http_attempts_total, :yt_dlp_invocations, :cache_hit,
                    :stage_durations_json, :http_requests_json, :llm_usage_json,
                    :detail_json
                )
                ON CONFLICT(job_id) DO UPDATE SET
                    status = excluded.status,
                    source_type = excluded.source_type,
                    platform = excluded.platform,
                    created_at = excluded.created_at,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    updated_at = excluded.updated_at,
                    queue_wait_ms = excluded.queue_wait_ms,
                    total_duration_ms = excluded.total_duration_ms,
                    media_duration_seconds = excluded.media_duration_seconds,
                    media_size_bytes = excluded.media_size_bytes,
                    download_seconds = excluded.download_seconds,
                    download_bytes = excluded.download_bytes,
                    download_mb_per_second = excluded.download_mb_per_second,
                    normalizing_seconds = excluded.normalizing_seconds,
                    normalizing_rtf = excluded.normalizing_rtf,
                    transcribing_seconds = excluded.transcribing_seconds,
                    asr_rtf = excluded.asr_rtf,
                    llm_seconds = excluded.llm_seconds,
                    llm_calls_total = excluded.llm_calls_total,
                    llm_prompt_tokens = excluded.llm_prompt_tokens,
                    llm_completion_tokens = excluded.llm_completion_tokens,
                    llm_total_tokens = excluded.llm_total_tokens,
                    llm_tokens_per_second = excluded.llm_tokens_per_second,
                    http_requests_total = excluded.http_requests_total,
                    tikhub_calls_total = excluded.tikhub_calls_total,
                    tikhub_http_attempts_total = excluded.tikhub_http_attempts_total,
                    yt_dlp_invocations = excluded.yt_dlp_invocations,
                    cache_hit = excluded.cache_hit,
                    stage_durations_json = excluded.stage_durations_json,
                    http_requests_json = excluded.http_requests_json,
                    llm_usage_json = excluded.llm_usage_json,
                    detail_json = excluded.detail_json
                """,
                values,
            )

    def list_job_metrics(
        self,
        *,
        status: str | None = None,
        platform: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        values: list[Any] = []
        if status:
            where.append("m.status = ?")
            values.append(status)
        if platform:
            where.append("m.platform = ?")
            values.append(platform)
        sql = """
            SELECT
                m.*,
                j.title AS title,
                j.source_value AS source_value
            FROM job_metrics AS m
            JOIN jobs AS j ON j.id = m.job_id
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY m.created_at DESC LIMIT ? OFFSET ?"
        values.extend([limit, offset])
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, values).fetchall()
        return [self._row_to_job_metrics(row) for row in rows]

    def summarize_recent_metrics(self, *, since: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_24h,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_24h,
                    AVG(CASE WHEN asr_rtf IS NOT NULL THEN asr_rtf END) AS avg_asr_rtf_24h,
                    AVG(CASE WHEN llm_total_tokens > 0 THEN llm_total_tokens END) AS avg_llm_tokens_24h
                FROM job_metrics
                WHERE created_at >= ?
                """,
                (since,),
            ).fetchone()
        return {
            "completed_24h": int(row["completed_24h"] or 0),
            "failed_24h": int(row["failed_24h"] or 0),
            "avg_asr_rtf_24h": row["avg_asr_rtf_24h"],
            "avg_llm_tokens_24h": row["avg_llm_tokens_24h"],
        }

    def _row_to_job(self, row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            id=row["id"],
            status=row["status"],
            source_type=row["source_type"],
            source_value=row["source_value"],
            options=_json_load(row["options_json"], {}),
            metadata=_json_load(row["metadata_json"], {}),
            error=_json_load(row["error_json"], None),
            result=_json_load(row["result_json"], None),
            progress=row["progress"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_job_metrics(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "title": row["title"],
            "source_value": row["source_value"],
            "status": row["status"],
            "source_type": row["source_type"],
            "platform": row["platform"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "updated_at": row["updated_at"],
            "queue_wait_ms": row["queue_wait_ms"],
            "total_duration_ms": row["total_duration_ms"],
            "media_duration_seconds": row["media_duration_seconds"],
            "media_size_bytes": row["media_size_bytes"],
            "download_seconds": row["download_seconds"],
            "download_bytes": row["download_bytes"],
            "download_mb_per_second": row["download_mb_per_second"],
            "normalizing_seconds": row["normalizing_seconds"],
            "normalizing_rtf": row["normalizing_rtf"],
            "transcribing_seconds": row["transcribing_seconds"],
            "asr_rtf": row["asr_rtf"],
            "llm_seconds": row["llm_seconds"],
            "llm_calls_total": row["llm_calls_total"],
            "llm_prompt_tokens": row["llm_prompt_tokens"],
            "llm_completion_tokens": row["llm_completion_tokens"],
            "llm_total_tokens": row["llm_total_tokens"],
            "llm_tokens_per_second": row["llm_tokens_per_second"],
            "http_requests_total": row["http_requests_total"],
            "tikhub_calls_total": row["tikhub_calls_total"],
            "tikhub_http_attempts_total": row["tikhub_http_attempts_total"],
            "yt_dlp_invocations": row["yt_dlp_invocations"],
            "cache_hit": None if row["cache_hit"] is None else bool(row["cache_hit"]),
            "stage_durations": _json_load(row["stage_durations_json"], {}),
            "http_requests": _json_load(row["http_requests_json"], {}),
            "llm_usage": _json_load(row["llm_usage_json"], {}),
            "detail": _json_load(row["detail_json"], {}),
        }
