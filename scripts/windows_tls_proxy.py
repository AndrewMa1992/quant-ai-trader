#!/usr/bin/env python3
"""Public HTTPS front door for the Windows host.

The API gateway stays plain HTTP on 127.0.0.1:8001 so health checks and
service-to-service calls do not change. This process:

  127.0.0.1:8443  TLS  ->  TCP 127.0.0.1:8001   (netsh portproxy 443 -> 8443)
  127.0.0.1:8081  HTTP 301 -> https://<host><path>   (netsh portproxy 80 -> 8081)

The certificate is generated on the server under certs/tls/ (gitignored).
It is a self-signed certificate for the public IP. Do not point this at the
Tiger API private key.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import select
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

TLS_PORT = 8443
REDIRECT_PORT = 8081
BACKEND = ("127.0.0.1", 8001)
LISTEN = "127.0.0.1"
# Budget for the TLS handshake and the HTTP redirect request. This must stay
# well above a public round trip. A short timeout on the listening socket is
# copied onto accepted sockets on Windows and aborts the handshake before a
# ServerHello is written.
HANDSHAKE_TIMEOUT = 30.0


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def host_without_port(host: str) -> str:
    host = (host or "").strip()
    if any(ch in host for ch in ("\r", "\n", " ", "/")):
        return ""
    if host.startswith("["):
        end = host.find("]")
        return host[: end + 1] if end != -1 else ""
    if host.count(":") == 1:
        return host.split(":", 1)[0]
    return host


def request_target(request_line: str) -> str:
    parts = request_line.split(" ")
    if len(parts) < 2:
        return "/"
    target = parts[1]
    if not target.startswith("/") or target.startswith("//"):
        return "/"
    if any(ch in target for ch in ("\r", "\n", " ")):
        return "/"
    return target


def redirect_location(request_head: bytes, fallback_host: str) -> str:
    head = request_head.decode("latin1", errors="replace")
    lines = head.split("\r\n")
    target = request_target(lines[0] if lines else "")
    host = ""
    for line in lines[1:]:
        if line.lower().startswith("host:"):
            host = host_without_port(line.split(":", 1)[1])
            break
    if not host:
        host = host_without_port(fallback_host) or "127.0.0.1"
    return "https://%s%s" % (host, target)


def discover_public_host() -> str:
    env = os.environ.get("QAT_PUBLIC_HOST", "").strip()
    if env:
        return env
    for url in (
        "http://metadata.tencentyun.com/latest/meta-data/public-ipv4",
        "http://169.254.169.254/latest/meta-data/public-ipv4",
    ):
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                text = resp.read().decode().strip()
        except Exception:
            continue
        if text and len(text) < 80 and " " not in text and "\n" not in text:
            return text
    return ""


def cert_hosts(public_host: str) -> list[str]:
    hosts: list[str] = []
    for item in (public_host, "localhost", "127.0.0.1"):
        item = (item or "").strip()
        if item and item not in hosts:
            hosts.append(item)
    return hosts


def _assert_safe_key(path: Path) -> None:
    name = path.name.lower()
    if "tiger" in str(path).lower() or name == "tiger_private_key.pem":
        raise SystemExit("refusing to write a TLS key over the Tiger private key")


def find_openssl() -> str | None:
    found = shutil.which("openssl")
    if found:
        return found
    for cand in (
        r"C:\Program Files\Git\usr\bin\openssl.exe",
        r"C:\Program Files\Git\mingw64\bin\openssl.exe",
    ):
        if os.path.isfile(cand):
            return cand
    return None


def _openssl_config(hosts: list[str]) -> str:
    sans = []
    for host in hosts:
        sans.append("IP:%s" % host if _is_ip(host) else "DNS:%s" % host)
    lines = [
        "[req]",
        "distinguished_name = dn",
        "x509_extensions = v3",
        "prompt = no",
        "[dn]",
        "CN = %s" % hosts[0],
        "[v3]",
        "subjectAltName = %s" % ",".join(sans),
        "keyUsage = digitalSignature, keyEncipherment",
        "extendedKeyUsage = serverAuth",
        "basicConstraints = CA:FALSE",
        "",
    ]
    return "\n".join(lines)


def _write_cert_cryptography(cert_path: Path, key_path: Path, hosts: list[str]) -> None:
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    san: list[x509.GeneralName] = []
    for host in hosts:
        if _is_ip(host):
            san.append(x509.IPAddress(ipaddress.ip_address(host)))
        else:
            san.append(x509.DNSName(host))
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0])])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _write_cert_openssl(cert_path: Path, key_path: Path, hosts: list[str], openssl: str) -> None:
    config_path = cert_path.parent / "openssl.cnf"
    config_path.write_text(_openssl_config(hosts), encoding="ascii")
    cmd = [
        openssl,
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-sha256",
        "-days",
        "825",
        "-nodes",
        "-keyout",
        str(key_path),
        "-out",
        str(cert_path),
        "-config",
        str(config_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def ensure_cert(cert_dir: Path, public_host: str) -> tuple[Path, Path]:
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"
    sans_path = cert_dir / "sans.txt"
    _assert_safe_key(key_path)
    hosts = cert_hosts(public_host)
    wanted = "\n".join(hosts) + "\n"
    current = sans_path.read_text(encoding="ascii") if sans_path.exists() else ""
    if cert_path.exists() and key_path.exists() and current == wanted:
        return cert_path, key_path
    openssl = find_openssl()
    if openssl:
        _write_cert_openssl(cert_path, key_path, hosts, openssl)
    else:
        try:
            _write_cert_cryptography(cert_path, key_path, hosts)
        except Exception as exc:
            raise SystemExit(
                "cannot create a TLS certificate (openssl and cryptography unavailable): %s" % exc
            ) from exc
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    sans_path.write_text(wanted, encoding="ascii")
    print("[ok] TLS certificate for %s" % ", ".join(hosts))
    return cert_path, key_path


def prepare_accepted(client: socket.socket) -> None:
    """Replace any inherited listen timeout before the handshake starts."""
    client.settimeout(HANDSHAKE_TIMEOUT)


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except Exception:
            pass


def _bridge(client: ssl.SSLSocket, backend: tuple[str, int]) -> None:
    upstream = None
    try:
        upstream = socket.create_connection(backend, timeout=10)
        upstream.settimeout(None)
        client.settimeout(None)
        left = threading.Thread(target=_pipe, args=(client, upstream), daemon=True)
        right = threading.Thread(target=_pipe, args=(upstream, client), daemon=True)
        left.start()
        right.start()
        left.join()
        right.join()
    except Exception:
        pass
    finally:
        for sock in (upstream, client):
            if sock is None:
                continue
            try:
                sock.close()
            except Exception:
                pass


def _read_head(conn: socket.socket, limit: int = 8192) -> bytes:
    data = b""
    while b"\r\n\r\n" not in data and len(data) < limit:
        chunk = conn.recv(min(4096, limit - len(data)))
        if not chunk:
            break
        data += chunk
    return data


def _handle_redirect(conn: socket.socket, fallback_host: str) -> None:
    try:
        head = _read_head(conn)
        location = redirect_location(head, fallback_host)
        body = b""
        resp = (
            "HTTP/1.1 301 Moved Permanently\r\n"
            "Location: %s\r\n"
            "Content-Length: %d\r\n"
            "Connection: close\r\n"
            "\r\n" % (location, len(body))
        ).encode("ascii")
        conn.sendall(resp)
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


class TlsProxy:
    def __init__(
        self,
        certfile: Path,
        keyfile: Path,
        backend: tuple[str, int] = BACKEND,
        tls_port: int = TLS_PORT,
        redirect_port: int = REDIRECT_PORT,
        listen_host: str = LISTEN,
        public_host: str = "",
    ) -> None:
        self.certfile = Path(certfile)
        self.keyfile = Path(keyfile)
        self.backend = backend
        self.tls_port = tls_port
        self.redirect_port = redirect_port
        self.listen_host = listen_host
        self.public_host = public_host or "127.0.0.1"
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._socks: list[socket.socket] = []

    def start(self) -> None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(str(self.certfile), str(self.keyfile))
        tls_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tls_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tls_sock.bind((self.listen_host, self.tls_port))
        tls_sock.listen(64)
        redir_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        redir_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        redir_sock.bind((self.listen_host, self.redirect_port))
        redir_sock.listen(64)
        self._socks = [tls_sock, redir_sock]
        self._threads = [
            threading.Thread(target=self._accept_tls, args=(tls_sock, ctx), daemon=True),
            threading.Thread(target=self._accept_redirect, args=(redir_sock,), daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def wait(self) -> None:
        while not self._stop.is_set():
            if any(not thread.is_alive() for thread in self._threads):
                raise SystemExit("TLS proxy listener exited")
            self._stop.wait(1.0)

    def stop(self) -> None:
        self._stop.set()
        for sock in self._socks:
            try:
                sock.close()
            except Exception:
                pass
        for thread in self._threads:
            thread.join(timeout=2)

    def _take_client(self, sock: socket.socket) -> socket.socket | None:
        """Accept one client, or return None when this listener must stop.

        select() waits so the listening socket can stay blocking. A timeout on
        that socket would be inherited by every accepted client on Windows.
        """
        while not self._stop.is_set():
            try:
                readable, _, _ = select.select([sock], [], [], 0.5)
            except (OSError, ValueError):
                return None
            if not readable:
                continue
            try:
                client, _addr = sock.accept()
            except OSError:
                return None
            prepare_accepted(client)
            return client
        return None

    def _accept_tls(self, sock: socket.socket, ctx: ssl.SSLContext) -> None:
        while not self._stop.is_set():
            client = self._take_client(sock)
            if client is None:
                break
            try:
                secure = ctx.wrap_socket(client, server_side=True)
            except Exception as exc:
                print("[warn] TLS handshake failed: %s" % exc, file=sys.stderr)
                try:
                    client.close()
                except Exception:
                    pass
                continue
            threading.Thread(target=_bridge, args=(secure, self.backend), daemon=True).start()

    def _accept_redirect(self, sock: socket.socket) -> None:
        while not self._stop.is_set():
            client = self._take_client(sock)
            if client is None:
                break
            threading.Thread(
                target=_handle_redirect,
                args=(client, self.public_host),
                daemon=True,
            ).start()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _check_redirect(redirect_port: int) -> bool:
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        opener.open("http://127.0.0.1:%d/" % redirect_port, timeout=8)
        print("[ERR] redirect did not return 301")
        return False
    except urllib.error.HTTPError as exc:
        loc = exc.headers.get("Location", "")
        if exc.code == 301 and loc.startswith("https://"):
            print("[ok] redirect %s %s" % (exc.code, loc))
            return True
        print("[ERR] redirect %s %s" % (exc.code, loc))
        return False
    except Exception as exc:
        print("[ERR] redirect %s" % exc)
        return False


def check_handshake(tls_port: int = TLS_PORT, redirect_port: int = REDIRECT_PORT) -> int:
    """Prove the terminator presents a certificate. Do not require the gateway."""
    failed = False
    ctx = ssl._create_unverified_context()
    raw = None
    try:
        raw = socket.create_connection(("127.0.0.1", tls_port), timeout=8)
        secure = ctx.wrap_socket(raw, server_hostname="127.0.0.1")
        try:
            cert = secure.getpeercert(binary_form=True)
        finally:
            secure.close()
        if cert:
            print("[ok] tls handshake :%d" % tls_port)
        else:
            print("[ERR] tls handshake :%d returned no certificate" % tls_port)
            failed = True
    except Exception as exc:
        print("[ERR] tls handshake :%d %s" % (tls_port, exc))
        failed = True
    finally:
        if raw is not None:
            try:
                raw.close()
            except Exception:
                pass
    if not _check_redirect(redirect_port):
        failed = True
    return 1 if failed else 0


def check_local(tls_port: int = TLS_PORT, redirect_port: int = REDIRECT_PORT) -> int:
    failed = False
    ctx = ssl._create_unverified_context()
    url = "https://127.0.0.1:%d/health" % tls_port
    try:
        with urllib.request.urlopen(url, context=ctx, timeout=8) as resp:
            print("[ok] tls %s HTTP %s" % (url, resp.status))
            if not (200 <= resp.status < 500):
                failed = True
    except Exception as exc:
        print("[ERR] tls %s %s" % (url, exc))
        failed = True

    if not _check_redirect(redirect_port):
        failed = True
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HTTPS terminator and HTTP redirect")
    parser.add_argument("--public-host", default="")
    parser.add_argument("--cert-dir", default="")
    parser.add_argument("--tls-port", type=int, default=TLS_PORT)
    parser.add_argument("--redirect-port", type=int, default=REDIRECT_PORT)
    parser.add_argument("--backend-host", default=BACKEND[0])
    parser.add_argument("--backend-port", type=int, default=BACKEND[1])
    parser.add_argument("--ensure-cert", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--check-handshake",
        action="store_true",
        help="Verify the certificate and the HTTP redirect without calling the gateway",
    )
    args = parser.parse_args(argv)

    if args.check_handshake:
        return check_handshake(args.tls_port, args.redirect_port)
    if args.check:
        return check_local(args.tls_port, args.redirect_port)

    public_host = (args.public_host or discover_public_host() or "127.0.0.1").strip()
    root = Path(os.environ.get("QAT_PROJECT_ROOT", ".")).resolve()
    cert_dir = Path(args.cert_dir) if args.cert_dir else root / "certs" / "tls"
    if args.ensure_cert or not (cert_dir / "cert.pem").exists():
        cert_path, key_path = ensure_cert(cert_dir, public_host)
    else:
        cert_path, key_path = cert_dir / "cert.pem", cert_dir / "key.pem"

    proxy = TlsProxy(
        certfile=cert_path,
        keyfile=key_path,
        backend=(args.backend_host, args.backend_port),
        tls_port=args.tls_port,
        redirect_port=args.redirect_port,
        public_host=public_host,
    )
    proxy.start()
    print(
        "[ok] TLS :%d -> %s:%d ; HTTP :%d redirects to https://%s/"
        % (args.tls_port, args.backend_host, args.backend_port, args.redirect_port, public_host)
    )
    try:
        proxy.wait()
    except KeyboardInterrupt:
        proxy.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
