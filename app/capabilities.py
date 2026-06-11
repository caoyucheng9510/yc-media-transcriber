from __future__ import annotations

import importlib.util

from app.config import Settings
from app.llm.providers import create_llm_client


def build_capabilities(settings: Settings) -> dict:
    ytdlp_available = importlib.util.find_spec("yt_dlp") is not None
    funasr_available = importlib.util.find_spec("funasr") is not None
    asr_available = settings.asr_engine == "mock" or funasr_available
    llm_client = create_llm_client(settings)
    tikhub_key_available = bool(settings.tikhub_api_key or settings.tikhub_alternate_api_key)
    tikhub_reason = None if tikhub_key_available else "需要配置 TIKHUB_API_KEY"
    youtube_tikhub_available = tikhub_key_available and settings.tikhub_enable_youtube_fallback
    bilibili_tikhub_available = tikhub_key_available and settings.tikhub_enable_bilibili_fallback
    return {
        "inputs": {
            "local_file": {"available": True},
            "direct_media_url": {"available": True},
            "sharing_text": {"available": True},
            "creator_profile": {
                "available": tikhub_key_available,
                "reason": tikhub_reason,
                "platforms": ["douyin", "xiaohongshu"],
                "max_items": settings.creator_preview_max_items,
            },
        },
        "platforms": {
            "youtube": {
                "available": ytdlp_available,
                "reason": None if ytdlp_available else "yt-dlp 未安装",
                "providers": {
                    "yt_dlp": {
                        "available": ytdlp_available,
                        "reason": None if ytdlp_available else "yt-dlp 未安装",
                    },
                    "tikhub_fallback": {
                        "available": youtube_tikhub_available,
                        "reason": _fallback_reason(settings.tikhub_enable_youtube_fallback, tikhub_reason),
                    },
                },
            },
            "bilibili": {
                "available": ytdlp_available,
                "reason": None if ytdlp_available else "yt-dlp 未安装",
                "providers": {
                    "yt_dlp": {
                        "available": ytdlp_available,
                        "reason": None if ytdlp_available else "yt-dlp 未安装",
                    },
                    "tikhub_fallback": {
                        "available": bilibili_tikhub_available,
                        "reason": _fallback_reason(settings.tikhub_enable_bilibili_fallback, tikhub_reason),
                    },
                },
            },
            "xiaoyuzhou": {"available": True, "reason": None},
            "douyin": {
                "available": tikhub_key_available,
                "reason": tikhub_reason,
                "providers": {
                    "tikhub": {
                        "available": tikhub_key_available,
                        "reason": tikhub_reason,
                    },
                },
            },
            "xiaohongshu": {
                "available": tikhub_key_available,
                "reason": tikhub_reason,
                "providers": {
                    "tikhub": {
                        "available": tikhub_key_available,
                        "reason": tikhub_reason,
                    },
                },
            },
        },
        "asr": {
            "engine": settings.asr_engine,
            "available": asr_available,
            "reason": None if asr_available else "FunASR 未安装",
            "language": settings.asr_language,
            "speaker_diarization": {"available": True, "default": False},
        },
        "llm": {
            "provider": llm_client.provider_name,
            "available": llm_client.available,
            "reason": llm_client.missing_configuration_reason,
            "model": settings.llm_model,
        },
        "exports": ["document_md", "document_pdf"],
        "batch_exports": ["document_md", "document_pdf", "spreadsheet_xlsx"],
        "auth": {"enabled": bool(settings.api_auth_token)},
    }


def _fallback_reason(enabled: bool, key_reason: str | None) -> str | None:
    if not enabled:
        return "TikHub fallback 已关闭"
    return key_reason
