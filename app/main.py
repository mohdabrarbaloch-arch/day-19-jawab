"""Jawab — a search engine that shows its work.

FastAPI app: security headers, CORS, rate limiting, static SPA, and the
routers. Everything configurable comes from app.config, which reads env.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.routers import auth, search
from app.schemas import HealthOut

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("jawab")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    log.info("Jawab %s up — env=%s", settings.app_version, settings.environment)
    yield
    log.info("Jawab shutting down")


app = FastAPI(
    title="Jawab",
    version=settings.app_version,
    description=(
        "A conversational search engine that answers with citations. "
        "Every sentence in an answer is traceable to a page it was read from."
    ),
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Headers that cost nothing and close the obvious holes."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if not settings.debug:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Never leak a stack trace to the client."""
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our side."},
    )


app.include_router(auth.router)
app.include_router(search.router)


@app.get("/api/health", response_model=HealthOut, tags=["meta"])
def health() -> HealthOut:
    return HealthOut(
        status="ok",
        version=settings.app_version,
        environment=settings.environment,
        database="sqlite" if settings.is_sqlite else "postgresql",
    )


# --- static SPA ---------------------------------------------------------
# Mounted last so /api/* always wins. The SPA is a single index.html plus
# app.js and styles.css; there is no build step, which is the point.
_static = settings.static_dir
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(str(_static / "index.html"))

    @app.get("/{path:path}", include_in_schema=False)
    def spa_fallback(path: str) -> FileResponse:
        """Any non-API path serves the app shell."""
        candidate = _static / path
        if candidate.is_file() and _static in candidate.resolve().parents:
            return FileResponse(str(candidate))
        return FileResponse(str(_static / "index.html"))
