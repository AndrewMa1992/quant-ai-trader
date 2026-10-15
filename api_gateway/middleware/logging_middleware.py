"""api_gateway/middleware/logging_middleware.py – Request logging middleware.

Logs every HTTP request with:
- Method, path, status code
- Response time in milliseconds
- Client IP address
- Request ID for tracing
"""

from __future__ import annotations

import time
import uuid

from fastapi import Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs incoming requests and their response times.

    Adds an X-Request-ID header to each response for traceability.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # Generate a unique request ID
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        path = request.url.path
        # Health and static assets are polled constantly. Skip their access
        # lines unless the response is an error, so log files stay useful.
        quiet = path in {"/health", "/health/live", "/favicon.ico"} or path.startswith("/assets/")

        # Get client IP (accounting for reverse proxies)
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.client.host if request.client else "unknown"

        if not quiet:
            logger.info(
                f"[{request_id}] {request.method} {path} "
                f"from {client_ip} - {request.headers.get('User-Agent', 'unknown')[:80]}"
            )

        start_time = time.perf_counter()

        # Process the request
        response = await call_next(request)

        # Calculate elapsed time
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        status_code = response.status_code
        if not quiet or status_code >= 400:
            log_level = "ERROR" if status_code >= 500 else "WARNING" if status_code >= 400 else "INFO"
            logger.bind(name="request").log(
                log_level,
                f"[{request_id}] {request.method} {path} "
                f"→ {status_code} ({elapsed_ms:.1f}ms)",
            )

        return response
