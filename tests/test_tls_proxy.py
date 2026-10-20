"""HTTPS terminator: TLS tunnel to the gateway and HTTP-to-HTTPS redirect."""

import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import windows_tls_proxy as tls  # noqa: E402


class _Backend(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = ("ok " + self.path).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # noqa: A003
        return


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_redirect_location_uses_host_header():
    head = b"GET /dashboard?x=1 HTTP/1.1\r\nHost: 43.160.194.146\r\n\r\n"
    assert tls.redirect_location(head, "127.0.0.1") == "https://43.160.194.146/dashboard?x=1"


def test_redirect_strips_port_and_rejects_open_redirect():
    head = b"GET http://evil.example/ HTTP/1.1\r\nHost: 43.160.194.146:80\r\n\r\n"
    assert tls.redirect_location(head, "127.0.0.1") == "https://43.160.194.146/"
    assert tls.host_without_port("bad host\r\nX") == ""


def test_https_tunnel_and_redirect(tmp_path):
    backend_port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", backend_port), _Backend)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    cert_dir = tmp_path / "tls"
    cert_path, key_path = tls.ensure_cert(cert_dir, "127.0.0.1")
    assert cert_path.exists() and key_path.exists()
    assert "127.0.0.1" in (cert_dir / "sans.txt").read_text(encoding="ascii")
    again, _ = tls.ensure_cert(cert_dir, "127.0.0.1")
    assert again.read_bytes() == cert_path.read_bytes()

    tls_port = _free_port()
    redirect_port = _free_port()
    proxy = tls.TlsProxy(
        certfile=cert_path,
        keyfile=key_path,
        backend=("127.0.0.1", backend_port),
        tls_port=tls_port,
        redirect_port=redirect_port,
        public_host="203.0.113.10",
    )
    proxy.start()
    try:
        ctx = ssl.create_default_context(cafile=str(cert_path))
        with urllib.request.urlopen(
            "https://127.0.0.1:%d/health" % tls_port, context=ctx, timeout=5
        ) as resp:
            assert resp.status == 200
            assert resp.read() == b"ok /health"

        req = urllib.request.Request(
            "https://127.0.0.1:%d/api/v2/status" % tls_port,
            data=b"ping",
            method="POST",
        )
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            assert resp.read() == b"ping"

        opener = urllib.request.build_opener(tls._NoRedirect)
        try:
            opener.open("http://127.0.0.1:%d/portfolio" % redirect_port, timeout=5)
            raise AssertionError("expected 301")
        except urllib.error.HTTPError as exc:
            assert exc.code == 301
            assert exc.headers.get("Location") == "https://127.0.0.1/portfolio"

        public = urllib.request.Request(
            "http://127.0.0.1:%d/orders" % redirect_port,
            headers={"Host": "203.0.113.10"},
        )
        try:
            opener.open(public, timeout=5)
            raise AssertionError("expected 301")
        except urllib.error.HTTPError as exc:
            assert exc.headers.get("Location") == "https://203.0.113.10/orders"
    finally:
        proxy.stop()
        server.shutdown()


def test_prepare_accepted_replaces_short_timeout():
    sock = socket.socket()
    try:
        sock.settimeout(0.5)
        tls.prepare_accepted(sock)
        assert sock.gettimeout() == tls.HANDSHAKE_TIMEOUT
    finally:
        sock.close()


def test_slow_client_hello_survives_inherited_timeout(tmp_path, monkeypatch):
    """Windows copies the listen timeout onto accepted sockets.

    A 0.5s inherited timeout used to close the connection before the
    ClientHello arrived, so the public peer saw EOF and no certificate.
    """
    real_accept = socket.socket.accept

    def accept_inherits_short_timeout(self):
        client, addr = real_accept(self)
        client.settimeout(0.5)
        return client, addr

    monkeypatch.setattr(socket.socket, "accept", accept_inherits_short_timeout)

    backend_port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", backend_port), _Backend)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    cert_dir = tmp_path / "tls"
    cert_path, key_path = tls.ensure_cert(cert_dir, "127.0.0.1")
    tls_port = _free_port()
    redirect_port = _free_port()
    proxy = tls.TlsProxy(
        certfile=cert_path,
        keyfile=key_path,
        backend=("127.0.0.1", backend_port),
        tls_port=tls_port,
        redirect_port=redirect_port,
        public_host="203.0.113.10",
    )
    proxy.start()
    try:
        raw = socket.create_connection(("127.0.0.1", tls_port), timeout=5)
        time.sleep(1.2)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        secure = ctx.wrap_socket(raw, server_hostname="127.0.0.1")
        try:
            assert secure.getpeercert(binary_form=True)
            secure.sendall(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
            data = b""
            while True:
                chunk = secure.recv(4096)
                if not chunk:
                    break
                data += chunk
            assert b"ok /health" in data
        finally:
            secure.close()
    finally:
        proxy.stop()
        server.shutdown()
