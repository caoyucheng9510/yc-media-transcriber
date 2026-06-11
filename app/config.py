from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


TRUE_VALUES = {"1", "true", "yes", "on"}
DEFAULT_MEDIA_FAKE_IP_CIDRS = ("198.18.0.0/15",)
DEFAULT_TRUSTED_MEDIA_HOST_SUFFIXES = (
    "acgvideo.com",
    "bilivideo.com",
    "bytecdn.cn",
    "bytefcdn.com",
    "byteimg.com",
    "douyinpic.com",
    "douyinvod.com",
    "douyinstatic.com",
    "ggpht.com",
    "googlevideo.com",
    "hdslb.com",
    "pstatp.com",
    "rednotecdn.com",
    "snssdk.com",
    "xhscdn.com",
    "xyzcdn.net",
    "youtube.com",
    "ytimg.com",
    "zjcdn.com",
)


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _merged_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    runtime_env = dict(env or os.environ)
    candidate_files = []
    candidate_files.append(Path.home() / ".yc-media-transcriber" / ".env")
    candidate_files.append(Path.cwd() / ".env")
    if runtime_env.get("APP_ENV_FILE"):
        candidate_files.append(Path(runtime_env["APP_ENV_FILE"]).expanduser())

    merged: dict[str, str] = {}
    for path in candidate_files:
        merged.update(_parse_env_file(path))
    merged.update(runtime_env)
    return merged


def _env_bool(values: Mapping[str, str], key: str, default: bool = False) -> bool:
    raw = values.get(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in TRUE_VALUES


def _env_int(values: Mapping[str, str], key: str, default: int) -> int:
    raw = values.get(key)
    if raw is None or raw == "":
        return default
    return int(raw)


def _env_float(values: Mapping[str, str], key: str, default: float) -> float:
    raw = values.get(key)
    if raw is None or raw == "":
        return default
    return float(raw)


def _env_tuple(
    values: Mapping[str, str],
    key: str,
    default: tuple[str, ...] = (),
) -> tuple[str, ...]:
    raw = values.get(key)
    if raw is None:
        return default
    return tuple(item.strip().lower() for item in raw.split(",") if item.strip())


def _container_data_dir_or_mac_fallback(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path == Path("/app/data") and not os.access("/app", os.W_OK):
        return Path.home() / ".yc-media-transcriber" / "data"
    return path


def _path_under_data_dir(raw_path: str, data_dir: Path, default_suffix: str) -> Path:
    raw = Path(raw_path).expanduser()
    if raw == Path(f"/app/data/{default_suffix}") and data_dir != Path("/app/data"):
        return data_dir / default_suffix
    return raw


def _path_at_data_dir(raw_path: str, data_dir: Path) -> Path:
    raw = Path(raw_path).expanduser()
    if raw == Path("/app/data") and data_dir != Path("/app/data"):
        return data_dir
    return raw


@dataclass(frozen=True)
class Settings:
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_data_dir: Path = Path("/app/data")
    app_max_upload_mb: int = 2048
    app_process_jobs_inline: bool = False
    task_queue_max_concurrency: int = 1
    app_allow_private_urls: bool = False
    app_private_url_allowlist: tuple[str, ...] = ()
    app_trusted_media_host_suffixes: tuple[str, ...] = DEFAULT_TRUSTED_MEDIA_HOST_SUFFIXES
    app_media_fake_ip_cidrs: tuple[str, ...] = DEFAULT_MEDIA_FAKE_IP_CIDRS
    app_temp_retention_hours: int = 24

    asr_engine: str = "funasr_paraformer"
    asr_language: str = "auto"
    asr_model: str = "paraformer-zh"
    asr_model_revision: str = "v2.0.4"
    asr_vad_model: str = "fsmn-vad"
    asr_vad_model_revision: str = "v2.0.4"
    asr_punc_model: str = "ct-punc-c"
    asr_punc_model_revision: str = "v2.0.4"
    asr_spk_model: str = "cam++"
    asr_spk_model_revision: str = "v2.0.2"
    asr_model_dir: Path = Path("/app/data/models")
    modelscope_cache_dir: Path = Path("/app/data")
    asr_device: str = "cpu"
    asr_mock_text: str = "这是一段用于测试的本地转录文本。"

    bilibili_backend: str = "yt-dlp"
    bilibili_bbdown_path: str = ""

    llm_provider: str = "deepseek"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    llm_structured_output_mode: str = "auto"
    llm_prompt_version: str = "reference_style_v1"
    llm_segment_enable_threshold: int = 5000
    llm_segment_size: int = 3000
    llm_segment_overlap: int = 0
    llm_calibration_max_retries: int = 2
    llm_chunk_time_budget_seconds: float = 300.0
    llm_chat_timeout_seconds: float = 60.0
    llm_dialog_min_chunk_chars: int = 300
    llm_dialog_preferred_chunk_chars: int = 800
    llm_dialog_max_chunk_chars: int = 1500
    llm_validation_enabled: bool = False
    llm_summary_min_chars: int = 500
    llm_summary_chunk_threshold: int = 8000
    llm_quality_min_ratio: float = 0.5
    llm_quality_max_ratio: float = 1.8

    terms_path: Path = Path("/app/data/terms.json")

    tikhub_api_key: str = ""
    tikhub_alternate_api_key: str = ""
    tikhub_base_url: str = "https://api.tikhub.io"
    tikhub_max_retries: int = 3
    tikhub_retry_delay: float = 5.0
    tikhub_timeout: float = 30.0
    tikhub_request_min_interval_seconds: float = 2.0
    tikhub_request_max_interval_seconds: float = 7.0
    tikhub_enable_youtube_fallback: bool = True
    tikhub_enable_bilibili_fallback: bool = True

    creator_preview_ttl_seconds: int = 3600
    creator_preview_max_items: int = 50

    metrics_enabled: bool = True
    metrics_resource_snapshot_enabled: bool = True
    metrics_sample_interval_seconds: float = 5.0
    metrics_record_http_details: bool = False

    api_auth_token: str = ""

    def __post_init__(self) -> None:
        if (
            self.modelscope_cache_dir == Path("/app/data")
            and self.app_data_dir != Path("/app/data")
        ):
            object.__setattr__(self, "modelscope_cache_dir", self.app_data_dir)

    @property
    def db_path(self) -> Path:
        return self.app_data_dir / "db" / "app.sqlite"

    @property
    def upload_dir(self) -> Path:
        return self.app_data_dir / "uploads"

    @property
    def temp_dir(self) -> Path:
        return self.app_data_dir / "temp"

    @property
    def jobs_dir(self) -> Path:
        return self.app_data_dir / "jobs"

    @property
    def cache_dir(self) -> Path:
        return self.app_data_dir / "cache"

    @property
    def logs_dir(self) -> Path:
        return self.app_data_dir / "logs"

    @property
    def max_upload_bytes(self) -> int:
        return self.app_max_upload_mb * 1024 * 1024

    def ensure_directories(self) -> None:
        for path in (
            self.app_data_dir,
            self.db_path.parent,
            self.upload_dir,
            self.temp_dir,
            self.jobs_dir,
            self.cache_dir,
            self.modelscope_cache_dir,
            self.asr_model_dir,
            self.logs_dir,
            self.terms_path.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    values = _merged_env(env)
    private_allowlist = tuple(
        item.strip()
        for item in values.get("APP_PRIVATE_URL_ALLOWLIST", "").split(",")
        if item.strip()
    )
    data_dir = _container_data_dir_or_mac_fallback(values.get("APP_DATA_DIR", "/app/data"))
    tikhub_min_interval = max(0.0, _env_float(values, "TIKHUB_REQUEST_MIN_INTERVAL_SECONDS", 2.0))
    tikhub_max_interval = max(
        tikhub_min_interval,
        _env_float(values, "TIKHUB_REQUEST_MAX_INTERVAL_SECONDS", 7.0),
    )
    return Settings(
        app_host=values.get("APP_HOST", "127.0.0.1"),
        app_port=_env_int(values, "APP_PORT", 8000),
        app_data_dir=data_dir,
        app_max_upload_mb=_env_int(values, "APP_MAX_UPLOAD_MB", 2048),
        app_process_jobs_inline=_env_bool(values, "APP_PROCESS_JOBS_INLINE", False),
        task_queue_max_concurrency=max(1, _env_int(values, "TASK_QUEUE_MAX_CONCURRENCY", 1)),
        app_allow_private_urls=_env_bool(values, "APP_ALLOW_PRIVATE_URLS", False),
        app_private_url_allowlist=private_allowlist,
        app_trusted_media_host_suffixes=_env_tuple(
            values,
            "APP_TRUSTED_MEDIA_HOST_SUFFIXES",
            DEFAULT_TRUSTED_MEDIA_HOST_SUFFIXES,
        ),
        app_media_fake_ip_cidrs=_env_tuple(
            values,
            "APP_MEDIA_FAKE_IP_CIDRS",
            DEFAULT_MEDIA_FAKE_IP_CIDRS,
        ),
        app_temp_retention_hours=max(1, _env_int(values, "APP_TEMP_RETENTION_HOURS", 24)),
        asr_engine=values.get("ASR_ENGINE", "funasr_paraformer"),
        asr_language=values.get("ASR_LANGUAGE", "auto"),
        asr_model=values.get("ASR_MODEL", "paraformer-zh"),
        asr_model_revision=values.get("ASR_MODEL_REVISION", "v2.0.4"),
        asr_vad_model=values.get("ASR_VAD_MODEL", "fsmn-vad"),
        asr_vad_model_revision=values.get("ASR_VAD_MODEL_REVISION", "v2.0.4"),
        asr_punc_model=values.get("ASR_PUNC_MODEL", "ct-punc-c"),
        asr_punc_model_revision=values.get("ASR_PUNC_MODEL_REVISION", "v2.0.4"),
        asr_spk_model=values.get("ASR_SPK_MODEL", "cam++"),
        asr_spk_model_revision=values.get("ASR_SPK_MODEL_REVISION", "v2.0.2"),
        asr_model_dir=_path_under_data_dir(
            values.get("ASR_MODEL_DIR", str(data_dir / "models")),
            data_dir,
            "models",
        ),
        modelscope_cache_dir=_path_at_data_dir(
            values.get("MODELSCOPE_CACHE", str(data_dir)),
            data_dir,
        ),
        asr_device=values.get("ASR_DEVICE", "cpu"),
        asr_mock_text=values.get("ASR_MOCK_TEXT", "这是一段用于测试的本地转录文本。"),
        bilibili_backend=values.get("BILIBILI_BACKEND", "yt-dlp"),
        bilibili_bbdown_path=values.get("BILIBILI_BBDOWN_PATH", ""),
        llm_provider=values.get("LLM_PROVIDER", "deepseek").strip().lower(),
        llm_api_key=values.get("LLM_API_KEY", ""),
        llm_base_url=values.get("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        llm_model=values.get("LLM_MODEL", "deepseek-v4-flash"),
        llm_structured_output_mode=values.get("LLM_STRUCTURED_OUTPUT_MODE", "auto").strip().lower(),
        llm_prompt_version=values.get("LLM_PROMPT_VERSION", "reference_style_v1"),
        llm_segment_enable_threshold=max(
            1,
            _env_int(values, "LLM_SEGMENT_ENABLE_THRESHOLD", 5000),
        ),
        llm_segment_size=max(1, _env_int(values, "LLM_SEGMENT_SIZE", 3000)),
        llm_segment_overlap=max(0, _env_int(values, "LLM_SEGMENT_OVERLAP", 0)),
        llm_calibration_max_retries=max(1, _env_int(values, "LLM_CALIBRATION_MAX_RETRIES", 2)),
        llm_chunk_time_budget_seconds=max(
            1.0,
            _env_float(values, "LLM_CHUNK_TIME_BUDGET_SECONDS", 300.0),
        ),
        llm_chat_timeout_seconds=max(1.0, _env_float(values, "LLM_CHAT_TIMEOUT_SECONDS", 60.0)),
        llm_dialog_min_chunk_chars=max(1, _env_int(values, "LLM_DIALOG_MIN_CHUNK_CHARS", 300)),
        llm_dialog_preferred_chunk_chars=max(
            1,
            _env_int(values, "LLM_DIALOG_PREFERRED_CHUNK_CHARS", 800),
        ),
        llm_dialog_max_chunk_chars=max(1, _env_int(values, "LLM_DIALOG_MAX_CHUNK_CHARS", 1500)),
        llm_validation_enabled=_env_bool(values, "LLM_VALIDATION_ENABLED", False),
        llm_summary_min_chars=max(0, _env_int(values, "LLM_SUMMARY_MIN_CHARS", 500)),
        llm_summary_chunk_threshold=max(1, _env_int(values, "LLM_SUMMARY_CHUNK_THRESHOLD", 8000)),
        llm_quality_min_ratio=max(0.0, _env_float(values, "LLM_QUALITY_MIN_RATIO", 0.5)),
        llm_quality_max_ratio=max(0.0, _env_float(values, "LLM_QUALITY_MAX_RATIO", 1.8)),
        terms_path=_path_under_data_dir(
            values.get("TERMS_PATH", str(data_dir / "terms.json")),
            data_dir,
            "terms.json",
        ),
        tikhub_api_key=values.get("TIKHUB_API_KEY", ""),
        tikhub_alternate_api_key=values.get("TIKHUB_ALTERNATE_API_KEY", ""),
        tikhub_base_url=values.get("TIKHUB_BASE_URL", "https://api.tikhub.io").rstrip("/"),
        tikhub_max_retries=max(0, _env_int(values, "TIKHUB_MAX_RETRIES", 3)),
        tikhub_retry_delay=max(0.0, _env_float(values, "TIKHUB_RETRY_DELAY", 5.0)),
        tikhub_timeout=max(1.0, _env_float(values, "TIKHUB_TIMEOUT", 30.0)),
        tikhub_request_min_interval_seconds=tikhub_min_interval,
        tikhub_request_max_interval_seconds=tikhub_max_interval,
        tikhub_enable_youtube_fallback=_env_bool(values, "TIKHUB_ENABLE_YOUTUBE_FALLBACK", True),
        tikhub_enable_bilibili_fallback=_env_bool(values, "TIKHUB_ENABLE_BILIBILI_FALLBACK", True),
        creator_preview_ttl_seconds=max(60, _env_int(values, "CREATOR_PREVIEW_TTL_SECONDS", 3600)),
        creator_preview_max_items=min(200, max(1, _env_int(values, "CREATOR_PREVIEW_MAX_ITEMS", 50))),
        metrics_enabled=_env_bool(values, "METRICS_ENABLED", True),
        metrics_resource_snapshot_enabled=_env_bool(
            values,
            "METRICS_RESOURCE_SNAPSHOT_ENABLED",
            True,
        ),
        metrics_sample_interval_seconds=max(
            1.0,
            _env_float(values, "METRICS_SAMPLE_INTERVAL_SECONDS", 5.0),
        ),
        metrics_record_http_details=_env_bool(values, "METRICS_RECORD_HTTP_DETAILS", False),
        api_auth_token=values.get("API_AUTH_TOKEN", ""),
    )
