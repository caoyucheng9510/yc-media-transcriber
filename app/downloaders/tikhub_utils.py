from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config import Settings
from app.downloaders.base import DownloadResult
from app.downloaders.direct import DirectMediaDownloader
from app.errors import AppError
from app.source_resolver import ResolvedSource


MEDIA_URL_SCHEMES = ("http://", "https://")


def stable_fingerprint(platform: str, media_id: str) -> str:
    raw = f"{platform}:{media_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def values_at_path(payload: Any, path: str) -> list[Any]:
    values = [payload]
    for part in path.split("."):
        next_values: list[Any] = []
        for value in values:
            if isinstance(value, dict):
                if part in value:
                    next_values.append(value[part])
            elif isinstance(value, list):
                if part.isdigit():
                    index = int(part)
                    if 0 <= index < len(value):
                        next_values.append(value[index])
                else:
                    for item in value:
                        if isinstance(item, dict) and part in item:
                            next_values.append(item[part])
        values = next_values
        if not values:
            break
    return _flatten(values)


def first_value_at_paths(payload: Any, paths: list[str]) -> Any:
    for path in paths:
        values = values_at_path(payload, path)
        for value in values:
            if value not in (None, ""):
                return value
    return None


def first_string_at_paths(payload: Any, paths: list[str]) -> str | None:
    for path in paths:
        for value in values_at_path(payload, path):
            result = first_string(value)
            if result:
                return result
    return None


def collect_urls_from_paths(payload: Any, paths: list[str]) -> list[str]:
    urls: list[str] = []
    for path in paths:
        for value in values_at_path(payload, path):
            if isinstance(value, str) and value.startswith(MEDIA_URL_SCHEMES):
                urls.append(value)
    return dedupe_urls(urls)


def dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        clean = url.strip()
        if clean and clean.startswith(MEDIA_URL_SCHEMES) and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def infer_file_ext(url: str | None, default: str = ".media") -> str:
    if not url:
        return default
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix or default


def download_first_available(
    *,
    settings: Settings,
    urls: list[str],
    source: ResolvedSource,
    job_temp_dir: Path,
    options: dict,
    media_id: str | None = None,
    request_headers: dict[str, str] | None = None,
    metrics: Any | None = None,
) -> DownloadResult:
    candidates = dedupe_urls(urls)
    if not candidates:
        raise AppError("download_failed", "TikHub 返回中未找到可下载音视频地址。", "downloading")

    direct = DirectMediaDownloader(settings, request_headers=request_headers)
    failures: list[AppError] = []
    for index, url in enumerate(candidates):
        target_dir = job_temp_dir if index == 0 else job_temp_dir / f"candidate-{index + 1}"
        media_source = ResolvedSource(
            kind="url",
            platform="direct_media",
            url=url,
            media_id=media_id or source.media_id,
            normalized_url=url,
            original_text=source.original_text,
            input_url=source.input_url,
            display_url=source.display_url,
        )
        try:
            return direct.download(media_source, target_dir, options, metrics=metrics)
        except AppError as exc:
            if exc.code not in {"download_failed", "invalid_source"}:
                raise
            failures.append(exc)
            continue

    if failures and all(error.code == "invalid_source" for error in failures):
        raise AppError("invalid_source", "TikHub 返回的下载地址未通过安全校验。", "downloading")
    raise AppError("download_failed", "所有 TikHub 候选下载地址均下载失败。", "downloading")


def _flatten(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if isinstance(value, list):
            result.extend(_flatten(value))
        else:
            result.append(value)
    return result
