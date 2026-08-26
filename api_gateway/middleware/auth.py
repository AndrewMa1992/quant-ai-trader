"""api_gateway/middleware/auth.py – API Key authentication middleware.

Validates X-API-Key header against the configured API key.
Skips auth for health check and docs endpoints.
"""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from configs.settings import settings

# Paths that do NOT require authentication
PUBLIC_PATHS: set[str] = {
    "/health",
    "/health/live",
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v2/status",
    "/api",
    "/favicon.ico",
    "/ws",
}

# Path prefixes that are public
PUBLIC_PREFIXES: tuple[str, ...] = (
    "/docs",
    "/redoc",
    "/openapi",
    "/assets",
    "/api/v2/push/",  # pipeline → WS bridge (localhost)
)


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that validates X-API-Key for protected endpoints.

    Skips validation for public paths (health, docs, root, SPA).
    Returns 401 if the API key is missing or invalid.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # Allow public paths without authentication
        # NOTE: "/".rstrip("/") == "" — normalize empty back to "/"
        path = request.url.path.rstrip("/") or "/"
        if path in PUBLIC_PATHS:
            return await call_next(request)
        if any(path.startswith(prefix.rstrip("/")) for prefix in PUBLIC_PREFIXES):
            return await call_next(request)

        # SPA routes (Dashboard, etc.) must not require API key
        if not path.startswith("/api"):
            return await call_next(request)

        # Allow OPTIONS preflight requests for CORS
        if request.method == "OPTIONS":
            return await call_next(request)

        # Validate API Key
        api_key = request.headers.get("X-API-Key")
        expected_key = settings.API_KEY

        if not api_key:
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "message": "Missing X-API-Key header",
                    "code": "UNAUTHORIZED",
                    "status_code": 401,
                },
            )

        if api_key != expected_key:
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "message": "Invalid API key",
                    "code": "UNAUTHORIZED",
                    "status_code": 401,
                },
            )

        return await call_next(request)
