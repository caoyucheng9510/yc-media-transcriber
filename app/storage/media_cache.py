from __future__ import annotations

import hashlib
import json
import logging
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config import Settings
from app.schemas import JobOptions, Segment

if TYPE_CHECKING:
    from app.storage.sqlite import SQLiteStore


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MediaCacheRecord:
    cache_key: str
    source_fingerprint: str
    metadata: dict[str, Any]
    segments: list[Segment]
    raw_transcript: str
    cache_dir: Path
    segments_path: Path
    raw_transcript_path: Path
    asr_engine: str
    speaker_diarization: bool


def build_media_cache_key(
    source_fingerprint: str,
    options: JobOptions,
    settings: Settings,
) -> str:
    payload = {
        "source_fingerprint": source_fingerprint,
        "asr_engine": options.asr_engine or settings.asr_engine,
        "speaker_diarization": bool(options.speaker_diarization),
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class MediaCacheStore:
    def __init__(self, settings: Settings, store: SQLiteStore):
        self.settings = settings
        self.store = store
        self.media_root = settings.cache_dir / "media"

    def get(self, cache_key: str) -> MediaCacheRecord | None:
        try:
            record = self.store.get_media_cache_record(cache_key)
            if record is None:
                return None
            return self._load_record(record)
        except Exception as exc:
            logger.warning("Ignoring invalid media cache record %s: %s", cache_key, exc)
            try:
                self.store.delete_media_cache(cache_key)
            except Exception:
                logger.exception("Failed to delete invalid media cache record %s", cache_key)
            return None

    def save(
        self,
        *,
        cache_key: str,
        source_fingerprint: str,
        options: JobOptions,
        metadata: dict[str, Any],
        segments: list[Segment],
        raw_transcript: str,
        source_identity: str | None = None,
        platform: str | None = None,
        media_id: str | None = None,
    ) -> None:
        self.media_root.mkdir(parents=True, exist_ok=True)
        target_dir = self.media_root / cache_key
        temp_dir = self.media_root / f".{cache_key}.{uuid.uuid4().hex}.tmp"
        segment_payloads = [segment.model_dump(mode="json") for segment in segments]
        metadata_payload = dict(metadata)
        metadata_payload.pop("cache", None)

        try:
            temp_dir.mkdir(parents=True, exist_ok=False)
            segments_path = temp_dir / "transcript.raw.json"
            raw_transcript_path = temp_dir / "raw_transcript.txt"
            llm_dir = temp_dir / "llm"
            llm_dir.mkdir(parents=True, exist_ok=True)

            segments_path.write_text(
                json.dumps(segment_payloads, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            raw_transcript_path.write_text(raw_transcript, encoding="utf-8")

            if target_dir.exists():
                shutil.rmtree(target_dir)
            temp_dir.rename(target_dir)

            effective = _effective_asr_options(options, self.settings)
            self.store.upsert_media_cache(
                {
                    "cache_key": cache_key,
                    "source_fingerprint": source_fingerprint,
                    "source_identity": source_identity,
                    "platform": platform,
                    "media_id": media_id,
                    "asr_engine": effective["asr_engine"],
                    "speaker_diarization": effective["speaker_diarization"],
                    "cache_dir": str(target_dir),
                    "segments_path": str(target_dir / "transcript.raw.json"),
                    "raw_transcript_path": str(target_dir / "raw_transcript.txt"),
                    "metadata": metadata_payload,
                }
            )
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    def _load_record(self, record: dict[str, Any]) -> MediaCacheRecord:
        cache_dir = self._path_in_media_root(record["cache_dir"], must_exist=True)
        segments_path = self._path_in_media_root(record["segments_path"], must_exist=True)
        raw_transcript_path = self._path_in_media_root(
            record["raw_transcript_path"],
            must_exist=True,
        )

        payload = json.loads(segments_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("transcript.raw.json must be a JSON array")
        segments = [Segment.model_validate(item) for item in payload]
        raw_transcript = raw_transcript_path.read_text(encoding="utf-8")

        return MediaCacheRecord(
            cache_key=record["cache_key"],
            source_fingerprint=record["source_fingerprint"],
            metadata=dict(record.get("metadata") or {}),
            segments=segments,
            raw_transcript=raw_transcript,
            cache_dir=cache_dir,
            segments_path=segments_path,
            raw_transcript_path=raw_transcript_path,
            asr_engine=record["asr_engine"],
            speaker_diarization=bool(record["speaker_diarization"]),
        )

    def _path_in_media_root(self, raw_path: str, *, must_exist: bool) -> Path:
        root = self.media_root.resolve()
        path = Path(raw_path).resolve()
        if path != root and root not in path.parents:
            raise ValueError(f"cache path is outside media cache root: {path}")
        if must_exist and not path.exists():
            raise FileNotFoundError(path)
        return path


def _effective_asr_options(options: JobOptions, settings: Settings) -> dict[str, Any]:
    return {
        "asr_engine": options.asr_engine or settings.asr_engine,
        "speaker_diarization": bool(options.speaker_diarization),
    }
