#!/usr/bin/env python3
"""Windows-friendly frontend static server with API proxy.

Serves frontend/dist on 0.0.0.0:5180 and proxies /api, /health, /ws
to the local API gateway (127.0.0.1:8001).

Why: vite preview/dev under Start-Process is unreliable on Windows Server.
"""

from __future__ import annotations

import argparse
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=os.environ.get("QAT_PROJECT_ROOT", "."))
    parser.add_argument("--port", type=int, default=int(os.environ.get("QAT_FRONTEND_PORT", "5180")))
    parser.add_argument("--gateway", default=os.environ.get("QAT_GATEWAY_URL", "http://127.0.0.1:8001"))
    args = parser.parse_args()

    root = Path(args.root).resolve()
    dist = root / "frontend" / "dist"
    index = dist / "index.html"
    if not index.exists():
        print(f"[ERR] Missing {index}. Run: cd frontend && npm run build", file=sys.stderr)
        return 1

    gateway = args.gateway.rstrip("/")
    os.chdir(dist)

    class Handler(SimpleHTTPRequestHandler):
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
                self.wfile.write(payload)
            except URLError as exc:
                msg = f'{{"detail":"gateway proxy failed: {exc}"}}'.encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)

        def _is_proxy_path(self) -> bool:
            p = self.path.split("?", 1)[0]
            return p == "/health" or p.startswith("/api") or p.startswith("/ws")

        def do_GET(self) -> None:  # noqa: N802
            if self._is_proxy_path():
                self._proxy()
                return
            path = self.path.split("?", 1)[0]
            file_path = dist / path.lstrip("/")
            if path != "/" and not file_path.exists() and not path.startswith("/assets"):
                self.path = "/index.html"
            return SimpleHTTPRequestHandler.do_GET(self)

        def do_HEAD(self) -> None:  # noqa: N802
            if self._is_proxy_path():
                self._proxy()
                return
            return SimpleHTTPRequestHandler.do_HEAD(self)

        def do_POST(self) -> None:  # noqa: N802
            if self._is_proxy_path():
                self._proxy()
                return
            self.send_error(405)

        def do_PUT(self) -> None:  # noqa: N802
            if self._is_proxy_path():
                self._proxy()
                return
            self.send_error(405)

        def do_PATCH(self) -> None:  # noqa: N802
            if self._is_proxy_path():
                self._proxy()
                return
            self.send_error(405)

        def do_DELETE(self) -> None:  # noqa: N802
            if self._is_proxy_path():
                self._proxy()
                return
            self.send_error(405)

        def do_OPTIONS(self) -> None:  # noqa: N802
            if self._is_proxy_path():
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
