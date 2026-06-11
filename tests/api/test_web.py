from __future__ import annotations

from fastapi.testclient import TestClient


def test_web_routes_return_spa_entry(client: TestClient) -> None:
    for path in ["/", "/settings", "/metrics"]:
        response = client.get(path)

        assert response.status_code == 200
        assert "YC 音视频转录" in response.text
        assert 'id="root"' in response.text


def test_jobs_web_page_is_not_exposed(client: TestClient) -> None:
    assert client.get("/jobs").status_code == 404
    assert client.get("/jobs/job_1").status_code == 404


def test_terms_api_can_save_terms_json(client: TestClient) -> None:
    response = client.put(
        "/api/settings/terms",
        json={"terms": [{"incorrect": "deep seek", "correct": "DeepSeek", "context": "AI 平台"}]},
    )

    assert response.status_code == 200
    terms = client.get("/api/settings/terms").json()
    assert terms["terms"][0]["correct"] == "DeepSeek"


def test_terms_api_starts_with_editable_examples(client: TestClient) -> None:
    terms = client.get("/api/settings/terms").json()

    assert [term["correct"] for term in terms["terms"]] == [
        "DeepSeek",
        "Claude",
        "飞书妙记",
        "Bilibili",
    ]
    assert terms["terms"][0]["context"] == "AI 平台"


def test_terms_examples_can_be_deleted(client: TestClient) -> None:
    response = client.put("/api/settings/terms", json={"terms": []})

    assert response.status_code == 200
    assert client.get("/api/settings/terms").json() == {"terms": []}
