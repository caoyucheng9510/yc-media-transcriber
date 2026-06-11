from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def temp_settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        app_data_dir=data_dir,
        asr_engine="mock",
        asr_model_dir=data_dir / "models",
        terms_path=data_dir / "terms.json",
        app_process_jobs_inline=True,
        asr_mock_text="测试转录文本",
    )


@pytest.fixture
def client(temp_settings: Settings) -> TestClient:
    app = create_app(temp_settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def sample_wav(tmp_path: Path) -> Path:
    path = tmp_path / "sample.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=0.5",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return path
