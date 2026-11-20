"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.ai.base import AIError
from app.api.v1 import api_router
from app.core.config import get_settings
from app.db.session import get_engine

logger = logging.getLogger("feedbackmind")


def _configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    # HTTP client libraries can log request URLs/headers at DEBUG; keep them quiet so keys never reach logs.
    for noisy in ("httpx", "httpcore", "anthropic", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    settings = get_settings()
    logger.info(
        "Starting %s %s (%s), AI provider: %s, embedded worker: %s",
        settings.app_name,
        __version__,
        settings.environment,
        settings.ai_provider,
        settings.embedded_worker,
    )
    started = False
    if settings.embedded_worker and settings.environment != "test":
        from app.services.jobs import start_embedded_workers

        start_embedded_workers()
        started = True
    yield
    if started:
        from app.services.jobs import stop_embedded_workers

        stop_embedded_workers()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="FeedbackMind AI API",
        version=__version__,
        description=(
            "AI-powered customer feedback intelligence. All routes are versioned under /api/v1. "
            "Workspace-scoped routes require a Bearer token and the X-Workspace-ID header."
        ),
        docs_url="/api/docs" if settings.docs_enabled else None,
        redoc_url="/api/redoc" if settings.docs_enabled else None,
        openapi_url="/api/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,  # bearer tokens, no cookies -> no CSRF surface
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Workspace-ID"],
        expose_headers=["Content-Disposition"],
        max_age=600,
    )

    max_body = settings.max_import_bytes + 1024 * 1024  # largest legitimate request: an import upload

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next):
        # Reject oversized requests before reading the body (Content-Length is set by browsers and HTTP clients).
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > max_body:
            return JSONResponse(status_code=413, content={"detail": f"Request is larger than the {settings.max_import_mb} MB limit."})
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if not request.url.path.startswith(("/api/docs", "/api/redoc")):
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if settings.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.url.path.startswith("/api/v1"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        # Return field errors without echoing submitted values (which may contain passwords or feedback text).
        errors = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        first = errors[0] if errors else {}
        field = ".".join(str(p) for p in (first.get("loc") or [])[1:]) or "request"
        return JSONResponse(status_code=422, content={"detail": f"Invalid {field}: {first.get('msg', 'invalid value')}", "errors": errors})

    @app.exception_handler(AIError)
    async def ai_error_handler(request: Request, exc: AIError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        if isinstance(exc, HTTPException):
            raise exc
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred. Please try again."})

    @app.get("/health", tags=["health"])
    @app.get("/api/v1/health", tags=["health"], include_in_schema=False)
    def health() -> dict:
        return {"status": "ok", "version": __version__, "storage": settings.storage_mode}

    @app.get("/health/ready", tags=["health"])
    @app.get("/api/v1/health/ready", tags=["health"], include_in_schema=False)
    def ready() -> JSONResponse:
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
                conn.execute(text("SELECT 1 FROM alembic_version LIMIT 1"))
        except Exception:  # noqa: BLE001
            return JSONResponse(status_code=503, content={"status": "unavailable", "database": "error"})
        return JSONResponse(
            {
                "status": "ok",
                "database": "ok",
                "storage": settings.storage_mode,
                "worker": "embedded" if settings.embedded_worker else "external",
            }
        )

    app.include_router(api_router)
    return app


app = create_app()
