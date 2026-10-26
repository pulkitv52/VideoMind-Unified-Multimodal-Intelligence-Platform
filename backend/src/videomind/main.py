import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from celery import Celery
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from videomind.embeddings.client import Client
from videomind.retrieval.routes import router as search
from videomind.embeddings.routes import router as indexes
from videomind.evidence.media_routes import router as media
from videomind.evidence.routes import router as evidence
from videomind.assets.routes import router as assets
from videomind.connectors.routes import router as connectors
from videomind.config import Settings, get_settings
from videomind.identity.routes import router as identity
from videomind.identity.self_service import router as self_service
from videomind.identity.analytics import router as analytics
from videomind.infrastructure.database import database
from videomind.infrastructure.services import object_client, redis_client

from videomind.infrastructure.telemetry import correlation_id, trace_id

LOGGER = logging.getLogger("videomind")


def create_app(settings: Settings | None = None):
    @asynccontextmanager
    async def lifespan(app):
        LOGGER.setLevel(logging.INFO)
        if not LOGGER.handlers:
            LOGGER.addHandler(logging.StreamHandler())
        LOGGER.propagate = False
        app.state.settings = settings or get_settings()
        app.state.db = database(app.state.settings.database_url.get_secret_value())
        app.state.redis = redis_client(app.state.settings)
        app.state.objects = object_client(app.state.settings)
        app.state.worker = Celery(
            "readiness", broker=app.state.settings.redis_url.get_secret_value()
        )
        app.state.worker.conf.broker_connection_timeout = 2
        yield
        app.state.worker.close()
        app.state.redis.close()
        app.state.db.dispose()

    app = FastAPI(
        title="VideoMind",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = correlation_id(request.headers.get("X-Request-ID"))
        started = time.perf_counter()
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin not in request.app.state.settings.allowed_origins:
                return JSONResponse(
                    {"detail": "Origin not allowed"},
                    403,
                    headers={"X-Request-ID": request_id},
                )
        token = trace_id.set(request_id)
        try:
            response = await call_next(request)
        except Exception:
            # Exception strings can contain connection credentials or imported content.
            LOGGER.error(
                json.dumps({"event": "request_failed", "request_id": request_id})
            )
            response = JSONResponse({"detail": "Service unavailable"}, 503)
        trace_id.reset(token)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        LOGGER.info(
            json.dumps(
                {
                    "event": "request",
                    "request_id": request_id,
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # FastAPI's default validation response can echo submitted credentials.
        return JSONResponse({"detail": "Invalid request"}, 422)

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready(request: Request):
        def probe():
            checks = {}
            for name, check in {
                "worker": lambda: _worker_ready(
                    request.app.state.worker, request.app.state.db
                ),
                "postgres": lambda: _database_ready(request.app.state.db),
                "redis": request.app.state.redis.ping,
                "storage": lambda: request.app.state.objects.bucket_exists(
                    request.app.state.settings.minio_bucket
                ),
            }.items():
                try:
                    checks[name] = bool(check())
                except Exception:
                    checks[name] = False
            return checks

        try:
            checks = await asyncio.wait_for(asyncio.to_thread(probe), timeout=8)
        except TimeoutError:
            checks = {
                "postgres": False,
                "redis": False,
                "storage": False,
                "worker": False,
            }
        healthy = all(checks.values())
        try:
            model = await asyncio.wait_for(
                asyncio.to_thread(Client().health), timeout=2
            )
            search_available = healthy and bool(model.get("profile"))
        except Exception:
            search_available = False
        return JSONResponse(
            {
                "ready": healthy,
                "dependencies": checks,
                "retrieval_ready": search_available,
                "retrieval_scope": "Service capability; workspace active-index readiness is authorized at /api/workspaces/{w}/search/facets",
            },
            200 if healthy else 503,
        )

    app.include_router(identity, prefix="/api")
    app.include_router(self_service, prefix="/api")
    app.include_router(analytics, prefix="/api")
    app.include_router(assets, prefix="/api")
    app.include_router(connectors, prefix="/api")
    app.include_router(evidence, prefix="/api")
    app.include_router(media, prefix="/api")
    app.include_router(indexes, prefix="/api")
    app.include_router(search, prefix="/api")
    return app


def _worker_ready(worker, engine):
    if worker.control.ping(timeout=1):
        return True
    # A solo worker cannot answer control messages during a task. The parent
    # emits fenced heartbeats while its resource-bounded document parser runs.
    with engine.connect() as conn:
        return conn.execute(text("SELECT app.document_worker_active()")).scalar_one()


def _database_ready(engine):
    with engine.connect() as conn:
        # Readiness also requires the initial migration and the restricted role.
        return conn.execute(
            text(
                "SELECT EXISTS(SELECT FROM public.alembic_version) AND NOT rolsuper AND NOT rolbypassrls FROM pg_roles WHERE rolname=current_user"
            )
        ).scalar_one()


app = create_app()
