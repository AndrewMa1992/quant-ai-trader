#!/usr/bin/env python3
"""Windows-friendly frontend static server with API proxy.

Serves frontend/dist on 0.0.0.0:5180 and proxies /api, /health, /ws
to the local API gateway (127.0.0.1:8001).

Critical: never return index.html for /assets/* (browsers reject JS modules
served as text/html).
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

# Ensure correct types even on Windows registries that map .js oddly
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("image/svg+xml", ".svg")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=os.environ.get("QAT_PROJECT_ROOT", "."))
    parser.add_argument("--port", type=int, default=int(os.environ.get("QAT_FRONTEND_PORT", "5180")))
    parser.add_argument("--gateway", default=os.environ.get("QAT_GATEWAY_URL", "http://127.0.0.1:8001"))
    args = parser.parse_args()

    root = Path(args.root).resolve()
    dist = (root / "frontend" / "dist").resolve()
    index = dist / "index.html"
    if not index.exists():
        print(f"[ERR] Missing {index}. Run: cd frontend && npm run build", file=sys.stderr)
        return 1

    gateway = args.gateway.rstrip("/")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *fmt_args) -> None:
            sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % fmt_args))

        def _proxy(self) -> None:
            target = f"{gateway}{self.path}"
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length) if length > 0 else None
            headers = {
                k: v
                for k, v in self.headers.items()
                if k.lower() not in ("host", "content-length", "connection", "transfer-encoding")
            }
            req = Request(target, data=body, headers=headers, method=self.command)
            try:
                with urlopen(req, timeout=60) as resp:
                    payload = resp.read()
                    self.send_response(resp.status)
                    for k, v in resp.headers.items():
                        if k.lower() in ("transfer-encoding", "connection", "content-encoding"):
                            continue
                        self.send_header(k, v)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    if self.command != "HEAD":
                        self.wfile.write(payload)
            except HTTPError as exc:
                payload = exc.read()
                self.send_response(exc.code)
                self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(payload)
            except URLError as exc:
                msg = f'{{"detail":"gateway proxy failed: {exc}"}}'.encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(msg)

        def _is_proxy_path(self, path: str) -> bool:
            return path == "/health" or path.startswith("/api") or path.startswith("/ws")

        def _send_bytes(self, status: int, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-cache" if content_type.startswith("text/html") else "public, max-age=3600")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        def _serve_file(self, file_path: Path) -> None:
            ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            if file_path.suffix.lower() in (".js", ".mjs"):
                ctype = "application/javascript"
            elif file_path.suffix.lower() == ".css":
                ctype = "text/css"
            payload = file_path.read_bytes()
            self._send_bytes(200, payload, ctype)

        def _handle(self) -> None:
            parsed = urlparse(self.path)
            path = unquote(parsed.path or "/")
            if self._is_proxy_path(path):
                self._proxy()
                return

            # Normalize and block path escape
            rel = path.lstrip("/")
            candidate = (dist / rel).resolve() if rel else index
            try:
                candidate.relative_to(dist)
            except ValueError:
                self._send_bytes(403, b"forbidden", "text/plain; charset=utf-8")
                return

            if path.startswith("/assets/") or path == "/favicon.ico":
                if candidate.is_file():
                    self._serve_file(candidate)
                    return
                # NEVER return HTML for asset URLs (causes MIME module errors)
                msg = f"asset not found: {path}".encode("utf-8")
                self._send_bytes(404, msg, "text/plain; charset=utf-8")
                return

            if candidate.is_file():
                self._serve_file(candidate)
                return

            # SPA fallback only for non-asset routes
            self._serve_file(index)

        def do_GET(self) -> None:  # noqa: N802
            self._handle()

        def do_HEAD(self) -> None:  # noqa: N802
            self._handle()

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path or "/"
            if self._is_proxy_path(path):
                self._proxy()
                return
            self.send_error(405)

        def do_PUT(self) -> None:  # noqa: N802
            path = urlparse(self.path).path or "/"
            if self._is_proxy_path(path):
                self._proxy()
                return
            self.send_error(405)

        def do_PATCH(self) -> None:  # noqa: N802
            path = urlparse(self.path).path or "/"
            if self._is_proxy_path(path):
                self._proxy()
                return
            self.send_error(405)

        def do_DELETE(self) -> None:  # noqa: N802
            path = urlparse(self.path).path or "/"
            if self._is_proxy_path(path):
                self._proxy()
                return
            self.send_error(405)

        def do_OPTIONS(self) -> None:  # noqa: N802
            path = urlparse(self.path).path or "/"
            if self._is_proxy_path(path):
                self._proxy()
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,DELETE,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.end_headers()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"[ok] frontend static+proxy on 0.0.0.0:{args.port} -> {gateway}")
    print(f"[ok] dist={dist}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
