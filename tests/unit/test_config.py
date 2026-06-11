from __future__ import annotations

from pathlib import Path

from app.config import (
    DEFAULT_MEDIA_FAKE_IP_CIDRS,
    DEFAULT_TRUSTED_MEDIA_HOST_SUFFIXES,
    Settings,
    load_settings,
)


def test_load_settings_reads_user_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "APP_DATA_DIR=/tmp/fmt-data",
                "ASR_ENGINE=mock",
                "ASR_MODEL=custom-asr",
                "ASR_MODEL_REVISION=v1",
                "ASR_VAD_MODEL=custom-vad",
                "ASR_VAD_MODEL_REVISION=v2",
                "ASR_PUNC_MODEL=custom-punc",
                "ASR_PUNC_MODEL_REVISION=v3",
                "ASR_SPK_MODEL=custom-spk",
                "ASR_SPK_MODEL_REVISION=v4",
                "MODELSCOPE_CACHE=/tmp/fmt-cache",
                "LLM_PROVIDER=openai_compatible",
                "LLM_API_KEY=generic-secret",
                "LLM_MODEL=deepseek-test-model",
                "LLM_SEGMENT_SIZE=1234",
                "TASK_QUEUE_MAX_CONCURRENCY=3",
                "APP_PROCESS_JOBS_INLINE=true",
                "APP_TRUSTED_MEDIA_HOST_SUFFIXES=Example.COM, rednotecdn.com",
                "APP_MEDIA_FAKE_IP_CIDRS=198.18.0.0/15, 203.0.113.0/24",
                "TIKHUB_REQUEST_MIN_INTERVAL_SECONDS=1.5",
                "TIKHUB_REQUEST_MAX_INTERVAL_SECONDS=3.5",
                "CREATOR_PREVIEW_TTL_SECONDS=120",
                "CREATOR_PREVIEW_MAX_ITEMS=20",
            ]
        ),
        encoding="utf-8",
    )
    settings = load_settings({"APP_ENV_FILE": str(env_file)})
    assert settings.app_data_dir == Path("/tmp/fmt-data")
    assert settings.asr_engine == "mock"
    assert settings.asr_model == "custom-asr"
    assert settings.asr_model_revision == "v1"
    assert settings.asr_vad_model == "custom-vad"
    assert settings.asr_vad_model_revision == "v2"
    assert settings.asr_punc_model == "custom-punc"
    assert settings.asr_punc_model_revision == "v3"
    assert settings.asr_spk_model == "custom-spk"
    assert settings.asr_spk_model_revision == "v4"
    assert settings.modelscope_cache_dir == Path("/tmp/fmt-cache")
    assert settings.llm_provider == "openai_compatible"
    assert settings.llm_api_key == "generic-secret"
    assert settings.llm_model == "deepseek-test-model"
    assert settings.llm_segment_size == 1234
    assert settings.task_queue_max_concurrency == 3
    assert settings.app_process_jobs_inline is True
    assert settings.app_trusted_media_host_suffixes == ("example.com", "rednotecdn.com")
    assert settings.app_media_fake_ip_cidrs == ("198.18.0.0/15", "203.0.113.0/24")
    assert settings.tikhub_request_min_interval_seconds == 1.5
    assert settings.tikhub_request_max_interval_seconds == 3.5
    assert settings.creator_preview_ttl_seconds == 120
    assert settings.creator_preview_max_items == 20


def test_load_settings_defaults_media_fake_ip_policy() -> None:
    settings = Settings()
    assert "rednotecdn.com" in settings.app_trusted_media_host_suffixes
    assert "douyinvod.com" in settings.app_trusted_media_host_suffixes
    assert "bilivideo.com" in settings.app_trusted_media_host_suffixes
    assert "googlevideo.com" in settings.app_trusted_media_host_suffixes
    assert settings.app_media_fake_ip_cidrs == DEFAULT_MEDIA_FAKE_IP_CIDRS
    assert settings.app_trusted_media_host_suffixes == DEFAULT_TRUSTED_MEDIA_HOST_SUFFIXES
