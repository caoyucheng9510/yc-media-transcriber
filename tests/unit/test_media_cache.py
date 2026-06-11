from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.schemas import JobOptions, Segment
from app.storage import SQLiteStore
from app.storage.media_cache import MediaCacheStore, build_media_cache_key


def test_media_cache_round_trip(tmp_path: Path) -> None:
    settings, store, cache = _cache_store(tmp_path)
    options = JobOptions(llm_polish=False, summary=False)
    cache_key = build_media_cache_key("source-1", options, settings)
    segments = [Segment(start=0, end=1.5, speaker="Speaker1", text="hello")]

    cache.save(
        cache_key=cache_key,
        source_fingerprint="source-1",
        options=options,
        metadata={"title": "A", "cache": {"hit": False, "cache_key": cache_key}},
        segments=segments,
        raw_transcript="Speaker1: hello",
        source_identity="youtube:abc",
        platform="youtube",
        media_id="abc",
    )

    record = cache.get(cache_key)

    assert record is not None
    assert record.metadata == {"title": "A"}
    assert record.segments == segments
    assert record.raw_transcript == "Speaker1: hello"
    assert record.raw_transcript_path.exists()
    db_record = store.get_media_cache_record(cache_key)
    assert db_record["source_identity"] == "youtube:abc"
    assert db_record["platform"] == "youtube"


def test_media_cache_key_changes_with_speaker_diarization(tmp_path: Path) -> None:
    settings = Settings(
        app_data_dir=tmp_path,
        asr_engine="mock",
        asr_model_dir=tmp_path / "models",
        terms_path=tmp_path / "terms.json",
    )
    without_speaker = build_media_cache_key(
        "source-1",
        JobOptions(speaker_diarization=False),
        settings,
    )
    with_speaker = build_media_cache_key(
        "source-1",
        JobOptions(speaker_diarization=True),
        settings,
    )

    assert without_speaker != with_speaker


def test_invalid_cache_record_falls_back_when_json_is_bad(tmp_path: Path) -> None:
    settings, store, cache = _cache_store(tmp_path)
    options = JobOptions(llm_polish=False, summary=False)
    cache_key = _save_basic_cache(cache, settings, options)
    record = store.get_media_cache_record(cache_key)
    Path(record["segments_path"]).write_text("not json", encoding="utf-8")

    assert cache.get(cache_key) is None
    assert store.get_media_cache_record(cache_key) is None


def test_invalid_cache_record_falls_back_when_file_is_missing(tmp_path: Path) -> None:
    settings, store, cache = _cache_store(tmp_path)
    options = JobOptions(llm_polish=False, summary=False)
    cache_key = _save_basic_cache(cache, settings, options)
    record = store.get_media_cache_record(cache_key)
    Path(record["raw_transcript_path"]).unlink()

    assert cache.get(cache_key) is None
    assert store.get_media_cache_record(cache_key) is None


def test_cache_record_path_outside_cache_dir_is_ignored(tmp_path: Path) -> None:
    settings, store, cache = _cache_store(tmp_path)
    options = JobOptions(llm_polish=False, summary=False)
    cache_key = build_media_cache_key("source-1", options, settings)
    cache_dir = settings.cache_dir / "media" / cache_key
    cache_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.json"
    outside.write_text("[]", encoding="utf-8")

    store.upsert_media_cache(
        {
            "cache_key": cache_key,
            "source_fingerprint": "source-1",
            "source_identity": "youtube:abc",
            "platform": "youtube",
            "media_id": "abc",
            "asr_engine": "mock",
            "speaker_diarization": False,
            "cache_dir": str(cache_dir),
            "segments_path": str(outside),
            "raw_transcript_path": str(outside),
            "metadata": {"title": "A"},
        }
    )

    assert cache.get(cache_key) is None
    assert store.get_media_cache_record(cache_key) is None


def _cache_store(tmp_path: Path) -> tuple[Settings, SQLiteStore, MediaCacheStore]:
    data_dir = tmp_path / "data"
    settings = Settings(
        app_data_dir=data_dir,
        asr_engine="mock",
        asr_model_dir=data_dir / "models",
        terms_path=data_dir / "terms.json",
    )
    settings.ensure_directories()
    store = SQLiteStore(settings.db_path)
    return settings, store, MediaCacheStore(settings, store)


def _save_basic_cache(
    cache: MediaCacheStore,
    settings: Settings,
    options: JobOptions,
) -> str:
    cache_key = build_media_cache_key("source-1", options, settings)
    cache.save(
        cache_key=cache_key,
        source_fingerprint="source-1",
        options=options,
        metadata={"title": "A"},
        segments=[Segment(start=0, end=1, text="hello")],
        raw_transcript="hello",
        source_identity="youtube:abc",
        platform="youtube",
        media_id="abc",
    )
    return cache_key
