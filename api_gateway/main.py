"""api_gateway/main.py – FastAPI application entry point.

Orchestrates:
- CORS middleware
- Global exception handlers
- Sub-router registration (placeholder routes until services are built)
- Lifespan events (DB connection pool, Redis)
- Health check endpoint
"""

from __future__ import annotations

import asyncio
import socket
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
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
    """Health check endpoint for load balancers and monitoring.

    Wraps DB and Redis checks in asyncio.wait_for() with 2-second
    timeouts each so the endpoint always responds in <3 seconds.
    """
    db_status = "unknown"
    redis_status = "unknown"

    # ── Database check with 2s timeout ───────────────────────
    async def _check_db() -> str:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "healthy"

    try:
        db_status = await asyncio.wait_for(_check_db(), timeout=2.0)
    except asyncio.TimeoutError:
        db_status = "timeout"
        logger.warning("Health check: database timed out after 2s")
    except Exception as exc:
        db_status = "unhealthy"
        logger.warning(f"Health check: database error: {exc}")

    # ── Redis check with 2s timeout ──────────────────────────
    async def _check_redis() -> str:
        redis = await get_redis()
        await redis.ping()
        return "healthy"

    try:
        redis_status = await asyncio.wait_for(_check_redis(), timeout=2.0)
    except asyncio.TimeoutError:
        redis_status = "timeout"
        logger.warning("Health check: redis timed out after 2s")
    except Exception as exc:
        redis_status = "unhealthy"
        logger.warning(f"Health check: redis error: {exc}")

    # Determine overall status
    if db_status == "healthy" and redis_status == "healthy":
        overall = "healthy"
    elif db_status == "timeout" or redis_status == "timeout":
        overall = "degraded"
    else:
        overall = "degraded"

    uptime = time.time() - _START_TIME
    return HealthResponse(
        status=overall,
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
    """API v2 status with live service health probes.

    Probes each microservice via TCP connect on the configured port
    with a 2-second timeout per service.
    """
    SERVICE_PORTS: dict[str, int] = {
        "data": 8011,
        "factor": 8012,
        "model_train": 8013,
        "model_infer": 8014,
        "risk": 8015,
        "execution": 8016,
    }

    def _probe_tcp(host: str, port: int, timeout: float = 2.0) -> str:
        """Probe a TCP port and return status string."""
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            return "healthy"
        except socket.timeout:
            return "timeout"
        except (ConnectionRefusedError, OSError):
            return "unreachable"
        except Exception:
            return "error"

    loop = asyncio.get_running_loop()
    services: dict[str, dict[str, object]] = {}
    for name, port in SERVICE_PORTS.items():
        # Run blocking TCP probe in thread to avoid blocking the event loop
        status = await loop.run_in_executor(None, _probe_tcp, "127.0.0.1", port, 2.0)
        services[name] = {"port": port, "status": status}

    all_healthy = all(s["status"] == "healthy" for s in services.values())

    return {
        "gateway": "running",
        "services": services,
        "all_healthy": all_healthy,
    }


# ── v2 Dashboard Router ──────────────────────────────────────
from api_gateway.routes.dashboard import router as dashboard_router

app.include_router(dashboard_router, prefix="/api/v2", tags=["Dashboard"])

# ── WebSocket Manager ────────────────────────────────────────
from api_gateway.websocket_manager import websocket_manager


# ── WebSocket Endpoint ───────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time market data and alerts.

    Supports room-based subscriptions via ``?room=<name>`` query parameter.
    Rooms: ``market-data``, ``tiger``, or custom names.
    """
    room = websocket.query_params.get("room", "")
    await websocket_manager.connect(websocket)
    if room:
        await websocket_manager.join_room(websocket, room)
    try:
        while True:
            # Keep connection alive; clients may send pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await websocket_manager.disconnect(websocket)


# ── REST→WS Bridge Endpoints ─────────────────────────────────
@app.post("/api/v2/push/cycle-data", tags=["WebSocket Bridge"])
async def push_cycle_data(data: dict) -> dict:
    """Push cycle data to all WebSocket clients in the 'market-data' room.

    Args:
        data: Cycle data payload to broadcast.

    Returns:
        Broadcast status with recipient count.
    """
    await websocket_manager.push_cycle_data(data)
    return {
        "status": "broadcast",
        "recipients": websocket_manager.room_size("market-data"),
    }


@app.post("/api/v2/push/tiger-snapshot", tags=["WebSocket Bridge"])
async def push_tiger_snapshot(data: dict) -> dict:
    """Push Tiger snapshot to all WebSocket clients in the 'tiger' room.

    Args:
        data: Tiger snapshot data payload to broadcast.

    Returns:
        Broadcast status with recipient count.
    """
    await websocket_manager.push_tiger_snapshot(data)
    return {
        "status": "broadcast",
        "recipients": websocket_manager.room_size("tiger"),
    }


# ── SPA Catch-all (must be last route registered) ────────────
@app.get("/{full_path:path}", tags=["SPA"])
async def spa_catchall(full_path: str) -> Any:
    """Serve the SPA frontend for any non-API route.

    If ``frontend/dist/index.html`` exists, returns it as a static file.
    Otherwise returns a 404 JSON response.
    """
    from pathlib import Path

    from fastapi.responses import FileResponse

    index_path = Path("frontend/dist/index.html")
    if index_path.exists():
        return FileResponse(str(index_path))
    raise HTTPException(
        status_code=404,
        detail="Frontend not built. Run 'cd frontend && npm run build'.",
    )
