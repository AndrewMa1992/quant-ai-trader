"""api_gateway/main.py – FastAPI application entry point.

Orchestrates:
- CORS middleware
- Global exception handlers
- Sub-router registration (placeholder routes until services are built)
- Lifespan events (DB connection pool, Redis)
- Health check endpoint
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy import text

from api_gateway.middleware.auth import AuthMiddleware
from api_gateway.middleware.logging_middleware import LoggingMiddleware
from configs.settings import settings
from shared.core.exceptions import QATException
from shared.core.logger import setup_logger
from shared.database.engine import close_engine, get_engine
from shared.redis_client import close_redis, get_redis
from shared.schema import HealthResponse

# Application startup time for uptime tracking
_START_TIME: float = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan handler for startup/shutdown events."""
    # ── Startup ──────────────────────────────────────────────
    setup_logger()
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION} (env={settings.ENV})")

    # Initialize database engine
    try:
        engine = get_engine()
        logger.info("Database engine initialized")
    except Exception as e:
        logger.error(f"Database engine initialization failed: {e}")

    # Initialize Redis
    try:
        redis = await get_redis()
        logger.info("Redis client initialized")
    except Exception as e:
        logger.warning(f"Redis initialization failed (non-fatal): {e}")

    logger.info(f"API Gateway ready on {settings.API_HOST}:{settings.API_PORT}")
    yield

    # ── Shutdown ─────────────────────────────────────────────
    logger.info("Shutting down API Gateway...")
    await close_redis()
    await close_engine()
    logger.info("API Gateway shutdown complete")


# ── FastAPI Application ──────────────────────────────────────
app = FastAPI(
    title=f"{settings.APP_NAME} API Gateway",
    version=settings.APP_VERSION,
    description="Head-of-Quant-Fund grade AI trading system v2",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# ── CORS Middleware ──────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Custom Middleware ────────────────────────────────────────
app.add_middleware(LoggingMiddleware)
app.add_middleware(AuthMiddleware)


# ── Global Exception Handlers ────────────────────────────────
@app.exception_handler(QATException)
async def qat_exception_handler(request: Request, exc: QATException) -> JSONResponse:
    """Catch all QATException subclasses and return structured errors."""
    logger.warning(f"QATException: {exc.code} - {exc.message}")
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch unhandled exceptions and return a generic 500 response."""
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred",
            "status_code": 500,
        },
    )


# ── Health Check ─────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check() -> HealthResponse:
    """Health check endpoint for load balancers and monitoring."""
    db_status = "unknown"
    redis_status = "unknown"

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception:
        db_status = "unhealthy"

    try:
        redis = await get_redis()
        await redis.ping()
        redis_status = "healthy"
    except Exception:
        redis_status = "unhealthy"

    uptime = time.time() - _START_TIME
    return HealthResponse(
        status="healthy" if db_status == "healthy" else "degraded",
        version=settings.APP_VERSION,
        uptime_seconds=round(uptime, 2),
        database=db_status,
        redis=redis_status,
    )


# ── Root ─────────────────────────────────────────────────────
@app.get("/", tags=["System"])
async def root() -> dict:
    """Root endpoint returning API information."""
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "env": settings.ENV,
        "docs": "/docs",
        "health": "/health",
    }


# ── Sub-router Registration (placeholder) ────────────────────
# Full routers will be registered when microservices are built.
# Each service exposes its own FastAPI app; the gateway proxies
# or delegates to them. For now, we include stub health routes.

@app.get("/api/v2/status", tags=["System"])
async def api_status() -> dict:
    """API v2 status with service registry."""
    return {
        "gateway": "running",
        "services": {
            "data": {"port": 8011, "status": "pending"},
            "factor": {"port": 8012, "status": "pending"},
            "model_train": {"port": 8013, "status": "pending"},
            "model_infer": {"port": 8014, "status": "pending"},
            "risk": {"port": 8015, "status": "pending"},
            "execution": {"port": 8016, "status": "pending"},
        },
    }
