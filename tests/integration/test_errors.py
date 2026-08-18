from uuid import UUID

import pytest
from app.core.config import DEVELOPMENT_JWT_SECRET, Settings
from app.core.errors import AppError
from app.main import create_app
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError


def client_with_routes() -> TestClient:
    app = create_app()

    @app.get("/api/app-error")
    async def app_error() -> None:
        raise AppError("quota_exceeded", "Quota exceeded", 429, retryable=True)

    @app.get("/api/http-error")
    async def http_error() -> None:
        raise HTTPException(status_code=400, detail="secret database password")

    @app.get("/api/boom")
    async def boom() -> None:
        raise RuntimeError("secret stack trace")

    return TestClient(app, raise_server_exceptions=False)


def assert_error_response(response, status_code: int, code: str) -> dict:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "request_id", "retryable"}
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]
    UUID(body["error"]["request_id"])
    return body["error"]


def test_default_jwt_secret_is_allowed_in_development():
    settings = Settings(environment="development")
    assert settings.jwt_secret.get_secret_value() == DEVELOPMENT_JWT_SECRET


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_default_jwt_secret_is_rejected_outside_development_and_test(environment: str):
    with pytest.raises(ValidationError, match="JWT_SECRET must be configured"):
        Settings(environment=environment)


def test_non_default_jwt_secret_is_allowed_in_production():
    settings = Settings(environment="production", jwt_secret="production-secret")
    assert settings.jwt_secret.get_secret_value() == "production-secret"


def test_app_error_uses_public_error_contract():
    error = assert_error_response(client_with_routes().get("/api/app-error"), 429, "quota_exceeded")
    assert error["message"] == "Quota exceeded"
    assert error["retryable"] is True


def test_missing_route_uses_safe_error_envelope():
    error = assert_error_response(client_with_routes().get("/api/not-present"), 404, "not_found")
    assert error["message"] == "Resource not found"
    assert error["retryable"] is False


def test_validation_error_uses_public_error_contract():
    app = create_app()

    @app.get("/api/items/{item_id}")
    async def item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    error = assert_error_response(TestClient(app).get("/api/items/not-an-int"), 422, "validation_error")
    assert error["message"] == "Request validation failed"


def test_http_exception_does_not_echo_detail():
    error = assert_error_response(client_with_routes().get("/api/http-error"), 400, "http_error")
    assert error["message"] == "Request failed"
    assert "secret" not in str(error)


def test_unexpected_exception_is_safe_and_consistent():
    error = assert_error_response(client_with_routes().get("/api/boom"), 500, "internal_error")
    assert error["message"] == "Internal server error"
    assert "secret" not in str(error)


@pytest.mark.parametrize("request_id", ["invalid request id", "12345678123442348234123456789012"])
def test_invalid_client_request_id_is_replaced(request_id: str):
    response = client_with_routes().get("/api/not-present", headers={"X-Request-ID": request_id})
    error = assert_error_response(response, 404, "not_found")
    assert error["request_id"] != request_id


def test_valid_client_request_id_is_preserved():
    request_id = "12345678-1234-4234-8234-123456789012"
    response = client_with_routes().get("/api/not-present", headers={"X-Request-ID": request_id})
    error = assert_error_response(response, 404, "not_found")
    assert error["request_id"] == request_id


def test_error_models_are_published_in_openapi():
    schemas = create_app().openapi()["components"]["schemas"]
    assert "ErrorEnvelope" in schemas
    assert schemas["ErrorEnvelope"]["required"] == ["error"]
    assert "PublicError" in schemas
    assert schemas["PublicError"]["required"] == ["code", "message", "request_id", "retryable"]
