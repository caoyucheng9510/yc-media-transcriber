from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.errors import AppError


AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    format_name: str
    size: int
    has_audio: bool
    has_video: bool


def ensure_supported_extension(path: Path) -> None:
    if path.suffix.lower() not in MEDIA_EXTENSIONS:
        raise AppError(
            "media_invalid",
            f"不支持的音视频扩展名：{path.suffix or '(none)'}",
            "normalizing",
        )


def probe_media(path: Path) -> MediaInfo:
    ensure_supported_extension(path)
    if not path.exists() or path.stat().st_size <= 0:
        raise AppError("media_invalid", "媒体文件不存在或为空。", "normalizing")
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise AppError("media_invalid", "未找到 ffprobe，请先安装 ffmpeg。", "normalizing") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or "ffprobe 无法识别该媒体文件。"
        raise AppError("media_invalid", message, "normalizing") from exc

    payload = json.loads(completed.stdout)
    streams = payload.get("streams", [])
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    has_video = any(stream.get("codec_type") == "video" for stream in streams)
    if not has_audio:
        raise AppError("media_invalid", "媒体文件不包含可处理的音频轨。", "normalizing")
    fmt = payload.get("format", {})
    return MediaInfo(
        duration=float(fmt.get("duration") or 0.0),
        format_name=str(fmt.get("format_name") or ""),
        size=int(fmt.get("size") or path.stat().st_size),
        has_audio=has_audio,
        has_video=has_video,
    )


def normalize_audio(source_path: Path, output_path: Path) -> MediaInfo:
    info = probe_media(source_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-sample_fmt",
        "s16",
        str(output_path),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise AppError("media_invalid", "未找到 ffmpeg，请先安装 ffmpeg。", "normalizing") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or "ffmpeg 音频规范化失败。"
        raise AppError("media_invalid", message[-1000:], "normalizing") from exc
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise AppError("media_invalid", "ffmpeg 未生成有效音频文件。", "normalizing")
    return info
