from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Final
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agent.router import router as agent_router
from app.core.config import Settings
from app.core.errors import AppError, ErrorEnvelope, PublicError
from app.db.session import create_database_engine, create_session_factory
from app.documents.router import router as documents_router
from app.identity.router import router as auth_router
from app.jobs.router import router as jobs_router
from app.knowledge.promotion_router import router as promotion_router
from app.knowledge.router import router as knowledge_router
from app.projects.router import router as projects_router
from app.providers.factory import build_provider
from app.quality.router import router as quality_router
from app.reviews.router import router as reviews_router

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
            details=error.details,
        )
    )
    return JSONResponse(
        status_code=error.status_code,
        content=envelope.model_dump(mode="json", exclude_none=True),
        headers={"X-Request-ID": str(request_id)},
    )


def _public_http_error(status_code: int) -> AppError:
    code, message = HTTP_ERROR_MESSAGES.get(
        status_code, ("http_error", "Request failed")
    )
    return AppError(code, message, status_code)


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="Doc Agent",
        version="0.1.0",
        description=(
            "文档质量工作台 API：项目与文档、Agent 对话、知识库检索与晋升治理、"
            "写作契约与质量门、评审工作流。\n\n"
            "鉴权：除 `/api/auth/login` 与 `/api/health` 外，所有接口需要 "
            "`Authorization: Bearer <token>`。\n\n"
            "错误：统一返回 `{\"error\": {\"code\", \"message\", \"request_id\", "
            "\"retryable\", \"details\"}}`；`code` 为稳定机器码，`retryable` "
            "表示可否安全重试。"
        ),
        openapi_tags=[
            {"name": "authentication", "description": "登录与当前用户"},
            {"name": "projects", "description": "项目与成员"},
            {"name": "documents", "description": "文档与不可变版本"},
            {"name": "agent", "description": "Agent 对话"},
            {"name": "jobs", "description": "后台任务"},
            {"name": "knowledge", "description": "知识库检索、空间与晋升治理"},
            {"name": "quality", "description": "版本对比、写作契约与质量门"},
            {"name": "reviews", "description": "评审工作流"},
        ],
    )
    app.state.settings = settings or Settings()
    app.state.database_engine = create_database_engine(app.state.settings.database_url)
    app.state.session_factory = create_session_factory(app.state.database_engine)
    app.state.agent_provider = build_provider(app.state.settings)

    # 默认不开放跨域（前端经 Vite 代理同源访问）；集团内部接入方可在环境变量中列入白名单
    if app.state.settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app.state.settings.cors_allowed_origins,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )

    @app.middleware("http")
    async def add_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = _select_request_id(
            request.headers.get("X-Request-ID")
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request.state.request_id)
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            request, AppError("validation_error", "Request validation failed", 422)
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return _error_response(request, _public_http_error(exc.status_code))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception request_id=%s", _request_id(request))
        return _error_response(
            request, AppError("internal_error", "Internal server error", 500)
        )

    @app.get("/api/health", responses=ERROR_RESPONSES)
    async def health() -> dict[str, str]:
        return {"status": "ready"}

    app.include_router(auth_router)
    app.include_router(projects_router)
    app.include_router(documents_router)
    app.include_router(agent_router)
    app.include_router(jobs_router)
    app.include_router(knowledge_router)
    app.include_router(promotion_router)
    app.include_router(quality_router)
    app.include_router(reviews_router)
    return app
