from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_metrics_overview_and_jobs(client: TestClient, sample_wav: Path) -> None:
    with sample_wav.open("rb") as fh:
        response = client.post(
            "/api/jobs/upload",
            files={"file": ("sample.wav", fh, "audio/wav")},
            data={"options": '{"llm_polish":false,"summary":false}'},
        )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    overview = client.get("/api/metrics/overview")
    assert overview.status_code == 200
    payload = overview.json()
    assert payload["enabled"] is True
    assert payload["queue"]["active_job_count"] == 0
    assert payload["recent"]["completed_24h"] == 1

    jobs = client.get("/api/metrics/jobs")
    assert jobs.status_code == 200
    items = jobs.json()["items"]
    assert items[0]["job_id"] == job_id
    assert items[0]["status"] == "completed"
    assert items[0]["platform"] == "local_file"
    assert items[0]["cache_hit"] is False
    assert items[0]["asr_rtf"] is not None


def test_metrics_api_uses_api_token(tmp_path: Path) -> None:
    settings = Settings(
        app_data_dir=tmp_path / "data",
        asr_engine="mock",
        asr_model_dir=tmp_path / "data" / "models",
        terms_path=tmp_path / "data" / "terms.json",
        api_auth_token="token",
        app_process_jobs_inline=True,
    )
    app = create_app(settings)
    with TestClient(app) as authed:
        assert authed.get("/api/metrics/overview").status_code == 401
        assert authed.get(
            "/api/metrics/overview",
            headers={"Authorization": "Bearer token"},
        ).status_code == 200


def test_metrics_disabled_returns_disabled_payload(tmp_path: Path) -> None:
    settings = Settings(
        app_data_dir=tmp_path / "data",
        asr_engine="mock",
        asr_model_dir=tmp_path / "data" / "models",
        terms_path=tmp_path / "data" / "terms.json",
        app_process_jobs_inline=True,
        metrics_enabled=False,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        overview = test_client.get("/api/metrics/overview").json()
        jobs = test_client.get("/api/metrics/jobs").json()

    assert overview["enabled"] is False
    assert overview["resources"]["reason"] == "metrics_disabled"
    assert jobs == {"enabled": False, "items": []}
