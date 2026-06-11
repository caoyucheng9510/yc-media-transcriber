from __future__ import annotations

import time
import random
import threading
from typing import Any

import httpx

from app.config import Settings
from app.errors import AppError


class _TikHubAuthError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code


class _TikHubRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._next_request_at = 0.0

    def wait(self, settings: Settings) -> None:
        min_interval = max(0.0, settings.tikhub_request_min_interval_seconds)
        max_interval = max(min_interval, settings.tikhub_request_max_interval_seconds)
        if max_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait_seconds = max(0.0, self._next_request_at - now)
            interval = random.uniform(min_interval, max_interval)
            self._next_request_at = max(now, self._next_request_at) + interval
        _sleep(wait_seconds)


_rate_limiter = _TikHubRateLimiter()


class TikHubClient:
    def __init__(self, settings: Settings, metrics: Any | None = None):
        self.settings = settings
        self.metrics = metrics

    def request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        metrics: Any | None = None,
    ) -> dict[str, Any]:
        recorder = metrics or self.metrics
        if recorder is not None:
            recorder.record_tikhub_call(endpoint=endpoint)
        keys = _unique_keys(
            [
                self.settings.tikhub_api_key,
                self.settings.tikhub_alternate_api_key,
            ]
        )
        if not keys:
            raise AppError(
                "platform_provider_not_configured",
                "TikHub 解析需要配置 TIKHUB_API_KEY。",
                "downloading",
            )

        last_auth_status: int | None = None
        for api_key in keys:
            try:
                return self._request_with_key(api_key, endpoint, params or {}, metrics=recorder)
            except _TikHubAuthError as exc:
                last_auth_status = exc.status_code
                continue
        status = f"HTTP {last_auth_status}" if last_auth_status else "鉴权失败"
        raise AppError("download_failed", f"TikHub 授权失败：{status}。", "downloading")

    def _request_with_key(
        self,
        api_key: str,
        endpoint: str,
        params: dict[str, Any],
        metrics: Any | None = None,
    ) -> dict[str, Any]:
        url = f"{self.settings.tikhub_base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }
        attempts = max(0, self.settings.tikhub_max_retries) + 1
        retry_delay = max(0.0, self.settings.tikhub_retry_delay)
        last_error: str | None = None

        for attempt in range(attempts):
            _rate_limiter.wait(self.settings)
            started = time.perf_counter()
            status_code: int | None = None
            error_code: str | None = None
            try:
                with httpx.Client(timeout=self.settings.tikhub_timeout) as client:
                    response = client.get(url, params=params, headers=headers)
                status_code = response.status_code
                if response.status_code in {401, 403}:
                    raise _TikHubAuthError(response.status_code)
                if response.status_code == 404:
                    raise AppError("download_failed", f"TikHub endpoint 不存在：HTTP 404。", "downloading")
                if response.status_code >= 500 or response.status_code == 429:
                    last_error = f"HTTP {response.status_code}"
                    if attempt < attempts - 1:
                        _sleep(_retry_delay(retry_delay, attempt, response))
                        continue
                response.raise_for_status()
                return self._validate_envelope(response.json())
            except _TikHubAuthError:
                raise
            except AppError:
                raise
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                error_code = "HTTPStatusError"
                message = _http_error_summary(exc.response)
                raise AppError("download_failed", f"TikHub 请求失败：{message}", "downloading") from exc
            except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as exc:
                last_error = exc.__class__.__name__
                error_code = last_error
                if attempt < attempts - 1:
                    _sleep(_retry_delay(retry_delay, attempt))
                    continue
                raise AppError("download_failed", f"TikHub 请求失败：{last_error}", "downloading") from exc
            except ValueError as exc:
                error_code = "invalid_json"
                raise AppError("download_failed", "TikHub 返回不是有效 JSON。", "downloading") from exc
            finally:
                if metrics is not None:
                    metrics.record_http_request(
                        provider="tikhub",
                        method="GET",
                        endpoint=endpoint,
                        status_code=status_code,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                        request_kind="api",
                        retry_attempt=attempt + 1,
                        error_code=error_code,
                    )

        raise AppError("download_failed", f"TikHub 请求失败：{last_error or '未知错误'}", "downloading")

    def _validate_envelope(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise AppError("download_failed", "TikHub 返回结构不符合预期。", "downloading")
        code = payload.get("code")
        if code is not None and str(code) != "200":
            message = _safe_message(payload.get("message_zh") or payload.get("message") or "接口返回非 200。")
            raise AppError("download_failed", f"TikHub 接口返回失败：{message}", "downloading")
        return payload


def _unique_keys(values: list[str]) -> list[str]:
    keys: list[str] = []
    for value in values:
        key = value.strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def _http_error_summary(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        message = payload.get("message_zh") or payload.get("message")
        if message:
            return f"HTTP {response.status_code}，{_safe_message(message)}"
    return f"HTTP {response.status_code}"


def _safe_message(value: Any, limit: int = 160) -> str:
    text = str(value).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _retry_delay(base_delay: float, attempt: int, response: httpx.Response | None = None) -> float:
    retry_after = _retry_after_seconds(response)
    if retry_after is not None:
        return retry_after
    if base_delay <= 0:
        return 0.0
    backoff = base_delay * (2**attempt)
    jitter = random.uniform(0.0, base_delay)
    return min(60.0, backoff + jitter)


def _retry_after_seconds(response: httpx.Response | None) -> float | None:
    if response is None:
        return None
    raw_value = getattr(response, "headers", {}).get("Retry-After")
    if not raw_value:
        return None
    try:
        return max(0.0, min(120.0, float(raw_value)))
    except ValueError:
        return None


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
