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

import httpx
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from loguru import logger
from sqlalchemy import text

from api_gateway.health_cache import read_health_cache, write_health_cache
from api_gateway.middleware.auth import AuthMiddleware
from api_gateway.middleware.logging_middleware import LoggingMiddleware
from api_gateway.proxy_util import filtered_response_headers
from configs.settings import settings
from shared.core.exceptions import QATException
from shared.core.logger import setup_logger
from shared.database.engine import close_engine, get_engine
from shared.redis_client import close_redis, get_redis
from shared.schema import HealthResponse
from shared.service_discovery import SERVICE_PORT_MAP, service_base_url, service_health_url

# Application startup time for uptime tracking
_START_TIME: float = time.time()
_FRONTEND_DIST = Path("frontend/dist")


def _spa_index_response() -> FileResponse | None:
    """Return built Vue index.html when present (public UI on :8001/)."""
    index_path = _FRONTEND_DIST / "index.html"
    if index_path.is_file():
        return FileResponse(str(index_path), media_type="text/html")
    return None


def _api_info_payload() -> dict:
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "env": settings.ENV,
        "docs": "/docs",
        "health": "/health",
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan handler for startup/shutdown events."""
    # ── Startup ──────────────────────────────────────────────
    setup_logger()
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION} (env={settings.ENV})")

    # Initialize database engine + create missing tables (SQLite paper friendly)
    try:
        engine = get_engine()
        import shared.models  # noqa: F401 - register ORM metadata
        from shared.models.base import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database engine initialized (schema ensure)")
    except Exception as e:
        logger.error(f"Database engine initialization failed: {e}")

    # Initialize Redis
    try:
        redis = await get_redis()
        logger.info("Redis client initialized")
    except Exception as e:
        logger.info(f"Redis not configured — running without cache: {e}")

    logger.info(f"API Gateway ready on {settings.API_HOST}:{settings.API_PORT}")

    # Initialize httpx client for reverse proxy to microservices
    app.state.http_client = httpx.AsyncClient(timeout=30.0)
    logger.info("HTTPX reverse proxy client initialized")

    yield

    # ── Shutdown ─────────────────────────────────────────────
    logger.info("Shutting down API Gateway...")
    await app.state.http_client.aclose()
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
@app.get("/health/live", tags=["System"])
async def health_live() -> dict:
    """Liveness only — always fast. Use for CD / load balancers / UI probes."""
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "uptime_seconds": round(time.time() - _START_TIME, 2),
    }


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check(request: Request) -> HealthResponse:
    """Health check endpoint for load balancers and monitoring.

    Aggregates status from:
    - Database (async connection check)
    - Redis (ping check)
    - All 6 downstream microservices (HTTP /health probe)

    Each check has a 2-second timeout so the endpoint always
    responds in <3 seconds. A fresh result is reused for a few seconds
    so repeated polls do not probe every service again.
    """
    cached = read_health_cache()
    if isinstance(cached, HealthResponse):
        return cached

    db_status = "unknown"
    redis_status = "unknown"
    services_status: dict[str, str] = {}

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
        if redis.is_degraded:
            return redis.mode
        await redis.ping()
        return redis.mode

    try:
        redis_status = await asyncio.wait_for(_check_redis(), timeout=2.0)
    except asyncio.TimeoutError:
        redis_status = "degraded (timeout)"
        logger.warning("Health check: redis timed out after 2s")
    except Exception as exc:
        redis_status = "degraded (unreachable)"
        logger.warning(f"Health check: redis error: {exc}")

    # ── Downstream service health probes ─────────────────────
    # Probe each microservice (exclude "api" — that is THIS gateway; probing
    # ourselves recursively deadlocks /health and makes the UI look "down").

    async def _probe_service(name: str, port: int) -> tuple[str, str]:
        """Probe a single downstream service via HTTP GET /health."""
        client: httpx.AsyncClient = request.app.state.http_client
        try:
            resp = await client.get(service_health_url(name), timeout=1.5)
            if resp.status_code == 200:
                return (name, "healthy")
            return (name, f"degraded (HTTP {resp.status_code})")
        except httpx.ConnectError:
            return (name, "unreachable")
        except httpx.TimeoutException:
            return (name, "timeout")
        except Exception as exc:
            return (name, f"error: {exc}")

    probe_tasks = [
        _probe_service(name, port)
        for name, port in SERVICE_PORT_MAP.items()
        if name != "api"
    ]
    probe_results = await asyncio.gather(*probe_tasks, return_exceptions=True)
    services_status = {}
    for item in probe_results:
        if isinstance(item, Exception):
            continue
        name, status = item
        services_status[name] = status
    services_status["api"] = "healthy"  # this process responded


    # ── Determine overall status ──────────────────────────────
    infra_healthy = db_status == "healthy"
    redis_healthy = redis_status.startswith("healthy")
    services_healthy = all(
        s == "healthy" for s in services_status.values()
    )
    any_unreachable = any(
        s == "unreachable" for s in services_status.values()
    )

    if infra_healthy and redis_healthy and services_healthy:
        overall = "healthy"
    elif any_unreachable or db_status == "unhealthy":
        overall = "unhealthy"
    else:
        overall = "degraded"

    uptime = time.time() - _START_TIME
    payload = HealthResponse(
        status=overall,
        version=settings.APP_VERSION,
        uptime_seconds=round(uptime, 2),
        database=db_status,
        redis=redis_status,
        services=services_status,
    )
    return write_health_cache(payload)


# ── Root ─────────────────────────────────────────────────────
@app.get("/", tags=["System"])
async def root(request: Request):
    """Public UI: serve the Vue SPA at / when frontend/dist exists.

    Browsers hitting http://<host>:8001/ must get HTML, not JSON.
    JSON API info remains at GET /api.
    """
    accept = (request.headers.get("accept") or "").lower()
    spa = _spa_index_response()
    # Prefer SPA for browsers; keep JSON only when explicitly asked and SPA missing
    if spa is not None and "text/html" in accept:
        return spa
    if spa is not None and "application/json" not in accept:
        return spa
    return _api_info_payload()


@app.get("/api", tags=["System"])
async def api_info() -> dict:
    """Machine-readable gateway info (JSON)."""
    return _api_info_payload()


# ── API v2 Status ───────────────────────────────────────────
@app.get("/api/v2/status", tags=["System"])
async def api_status() -> dict:
    """API v2 status with live service health probes.

    Probes each microservice via TCP connect on the configured host/port
    with a 2-second timeout per service.
    """

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

    from shared.service_discovery import service_host

    loop = asyncio.get_running_loop()
    services: dict[str, dict[str, object]] = {}
    for name, port in SERVICE_PORT_MAP.items():
        host = service_host(name)
        status = await loop.run_in_executor(None, _probe_tcp, host, port, 2.0)
        services[name] = {"host": host, "port": port, "status": status}

    all_healthy = all(s["status"] == "healthy" for s in services.values())

    return {
        "gateway": "running",
        "services": services,
        "all_healthy": all_healthy,
    }


# ── v2 Dashboard Router ──────────────────────────────────────
from api_gateway.routes.dashboard import router as dashboard_router

app.include_router(dashboard_router, prefix="/api/v2", tags=["Dashboard"])

# ── v2 Rollback Router ───────────────────────────────────────
from api_gateway.routes.rollback import router as rollback_router

app.include_router(rollback_router, prefix="/api/v2", tags=["Execution"])

# ── v2 Server Logs Router (web log viewer / remote agents) ───
from api_gateway.routes.logs import router as logs_router

app.include_router(logs_router, prefix="/api/v2", tags=["Logs"])

# ── WebSocket Manager ────────────────────────────────────────
from api_gateway.websocket_manager import websocket_manager


# ── WebSocket Endpoint ───────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time market data and alerts.

    Supports room-based subscriptions via ``?room=<name>`` query parameter.
    Comma-separated rooms allowed (e.g. ``tiger,market-data``).
    Empty room → join both ``tiger`` and ``market-data`` (dashboard default).
    Clients may also send JSON ``{"action":"join","room":"..."}``.
    """
    import json as _json

    room_param = websocket.query_params.get("room", "")
    await websocket_manager.connect(websocket)
    if room_param.strip():
        for room in [r.strip() for r in room_param.split(",") if r.strip()]:
            await websocket_manager.join_room(websocket, room)
    else:
        await websocket_manager.join_room(websocket, "tiger")
        await websocket_manager.join_room(websocket, "market-data")
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
                continue
            try:
                msg = _json.loads(data)
                if isinstance(msg, dict) and msg.get("action") == "join":
                    room = str(msg.get("room") or "").strip()
                    if room:
                        await websocket_manager.join_room(websocket, room)
                elif isinstance(msg, dict) and msg.get("action") == "leave":
                    room = str(msg.get("room") or "").strip()
                    if room:
                        await websocket_manager.leave_room(websocket, room)
            except Exception:
                pass
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


# ── Microservice Reverse Proxy ──────────────────────────────
# /api/v2/status (above) is registered first so it takes
# precedence over the catch-all proxy route below.

# User-facing URL segment → canonical service name (port lookup)
SERVICE_ALIASES: dict[str, str] = {
    "trade": "execution",
    "model": "model_infer",
    "analysis": "risk",
    # Frontend-friendly path segments (match service mount prefixes)
    "factors": "factor",
    "train": "model_train",
    "infer": "model_infer",
}

# Canonical service → URL path prefix on the microservice
# (mounts are /api/v2/factors, /api/v2/train, /api/v2/infer — not the service key)
SERVICE_PATH_PREFIX: dict[str, str] = {
    "data": "data",
    "factor": "factors",
    "model_train": "train",
    "model_infer": "infer",
    "risk": "risk",
    "execution": "execution",
}

# Combined lookup: canonical names + aliases (for 404 validation)
_ALL_SERVICE_NAMES: set[str] = set(SERVICE_PORT_MAP.keys()) | set(SERVICE_ALIASES.keys())


@app.api_route(
    "/api/v2/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def proxy_to_service(service: str, path: str, request: Request) -> Response:
    """Reverse-proxy /api/v2/{service}/* to the matching microservice port.

    Supports canonical names, frontend aliases (factors/train/infer/trade/…),
    and remaps path prefixes to each service's real mount
    (e.g. factor → /api/v2/factors/…).
    """
    if service not in _ALL_SERVICE_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")

    canonical = SERVICE_ALIASES.get(service, service)
    port = SERVICE_PORT_MAP[canonical]
    path_prefix = SERVICE_PATH_PREFIX.get(canonical, canonical)
    # Docker-aware host via service_discovery + correct mount path prefix
    target_url = f"{service_base_url(canonical)}/api/v2/{path_prefix}/{path}"

    if request.query_params:
        target_url += f"?{request.query_params}"

    try:
        body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in ("host", "content-length", "transfer-encoding")
        }

        client: httpx.AsyncClient = request.app.state.http_client
        resp = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
            timeout=30.0,
        )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=filtered_response_headers(resp.headers),
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=f"Service {service} (port {port}) is not available",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail=f"Service {service} timed out",
        )

# ── Frontend static assets + SPA (must be after API routes) ─
from fastapi.staticfiles import StaticFiles

_FRONTEND_ASSETS = _FRONTEND_DIST / "assets"
if _FRONTEND_ASSETS.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_ASSETS)), name="frontend-assets")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    icon = _FRONTEND_DIST / "favicon.ico"
    if icon.exists():
        return FileResponse(str(icon))
    raise HTTPException(status_code=404, detail="favicon not found")


@app.get("/{full_path:path}", tags=["SPA"])
async def spa_catchall(full_path: str):
    """SPA fallback: return index.html for client routes only.

    Never return HTML for missing /assets/* (that breaks ES modules).
    """
    if full_path.startswith("assets/") or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail=f"Not found: {full_path}")

    spa = _spa_index_response()
    if spa is not None:
        return spa
    raise HTTPException(
        status_code=404,
        detail="Frontend not built. Run 'cd frontend && npm run build'.",
    )
