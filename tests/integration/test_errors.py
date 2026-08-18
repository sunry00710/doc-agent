from fastapi.testclient import TestClient

from app.main import create_app


def test_missing_route_uses_safe_error_envelope():
    response = TestClient(create_app()).get("/api/not-present")

    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "not_found"
    assert body["request_id"]
    assert body["retryable"] is False
