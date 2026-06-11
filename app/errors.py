from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException


@dataclass
class AppError(Exception):
    code: str
    message: str
    stage: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": public_error_message(self.message), "stage": self.stage}


def normalize_error(exc: BaseException, stage: str) -> dict[str, str]:
    if isinstance(exc, AppError):
        return exc.to_dict()
    return {"code": "internal_error", "message": "任务处理失败，请查看服务日志。", "stage": stage}


def public_error_message(message: str, limit: int = 120) -> str:
    cleaned = " ".join(message.split()).strip()
    if not cleaned:
        return "任务处理失败。"
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit].rstrip()}..."


def error_response(status: str, error: dict[str, Any]) -> dict[str, Any]:
    return {"status": status, "error": error}


def http_error(status_code: int, code: str, message: str, stage: str = "api") -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "stage": stage},
    )


def app_error_to_http_exception(exc: AppError, status_code: int | None = None) -> HTTPException:
    return HTTPException(
        status_code=status_code or _status_code_for_error(exc.code),
        detail=exc.to_dict(),
    )


def _status_code_for_error(code: str) -> int:
    if code in {"job_not_found", "artifact_not_found", "creator_preview_not_found"}:
        return 404
    if code in {"job_not_retryable", "job_not_deletable"}:
        return 409
    if code == "upload_too_large":
        return 413
    if code in {"unauthorized"}:
        return 401
    return 400
