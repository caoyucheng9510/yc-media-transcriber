from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request, status

from app.config import Settings
from app.errors import http_error
from app.storage import SQLiteStore


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> SQLiteStore:
    return request.app.state.store


def require_api_token(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if not settings.api_auth_token:
        return
    expected = f"Bearer {settings.api_auth_token}"
    if authorization != expected:
        raise http_error(
            status.HTTP_401_UNAUTHORIZED,
            "unauthorized",
            "API_AUTH_TOKEN 校验失败。",
        )
