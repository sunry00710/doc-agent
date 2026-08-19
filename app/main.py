from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Final
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import Settings
from app.core.errors import AppError, ErrorEnvelope, PublicError
from app.identity.router import router as auth_router

logger = logging.getLogger(__name__)

ERROR_RESPONSES: Final = {
    400: {"model": ErrorEnvelope, "description": "Bad request"},
    404: {"model": ErrorEnvelope, "description": "Resource not found"},
    422: {"model": ErrorEnvelope, "description": "Request validation failed"},
    500: {"model": ErrorEnvelope, "description": "Internal server error"},
}
HTTP_ERROR_MESSAGES: Final = {
    400: ("http_error", "Request failed"),
    401: ("unauthorized", "Authentication required"),
    403: ("forbidden", "Access denied"),
    404: ("not_found", "Resource not found"),
    405: ("method_not_allowed", "Method not allowed"),
    409: ("conflict", "Request conflict"),
    413: ("payload_too_large", "Request payload too large"),
    415: ("unsupported_media_type", "Unsupported media type"),
    429: ("rate_limited", "Too many requests"),
    503: ("service_unavailable", "Service unavailable"),
}


def _select_request_id(raw_request_id: str | None) -> UUID:
    if raw_request_id is not None and len(raw_request_id) == 36:
        try:
            request_id = UUID(raw_request_id)
            if str(request_id) == raw_request_id.lower():
                return request_id
        except ValueError:
            pass
    return uuid4()


def _request_id(request: Request) -> UUID:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, UUID):
        return request_id
    request_id = uuid4()
    request.state.request_id = request_id
    return request_id


def _error_response(request: Request, error: AppError) -> JSONResponse:
    request_id = _request_id(request)
    envelope = ErrorEnvelope(
        error=PublicError(
            code=error.code,
            message=error.message,
            request_id=request_id,
            retryable=error.retryable,
        )
    )
    return JSONResponse(
        status_code=error.status_code,
        content=envelope.model_dump(mode="json"),
        headers={"X-Request-ID": str(request_id)},
    )


def _public_http_error(status_code: int) -> AppError:
    code, message = HTTP_ERROR_MESSAGES.get(status_code, ("http_error", "Request failed"))
    return AppError(code, message, status_code)


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Doc Agent")
    app.state.settings = settings or Settings()

    @app.middleware("http")
    async def add_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = _select_request_id(request.headers.get("X-Request-ID"))
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request.state.request_id)
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(request, AppError("validation_error", "Request validation failed", 422))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error_response(request, _public_http_error(exc.status_code))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception request_id=%s", _request_id(request))
        return _error_response(request, AppError("internal_error", "Internal server error", 500))

    @app.get("/api/health", responses=ERROR_RESPONSES)
    async def health() -> dict[str, str]:
        return {"status": "ready"}

    app.include_router(auth_router)
    return app
