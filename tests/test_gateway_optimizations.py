"""Gateway proxy header filtering and short /health cache."""

from api_gateway.health_cache import (
    TTL_SECONDS,
    clear_health_cache,
    read_health_cache,
    write_health_cache,
)
from api_gateway.proxy_util import filtered_response_headers


def setup_function() -> None:
    clear_health_cache()


def test_proxy_drops_encoding_and_hop_headers() -> None:
    headers = filtered_response_headers(
        {
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "Content-Length": "999",
            "Transfer-Encoding": "chunked",
            "Connection": "keep-alive",
            "X-Request-Id": "abc",
        }
    )
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Request-Id"] == "abc"
    assert "Content-Encoding" not in headers
    assert "Content-Length" not in headers
    assert "Transfer-Encoding" not in headers
    assert "Connection" not in headers


def test_health_cache_reuses_payload_inside_ttl() -> None:
    payload = {"status": "ok"}
    write_health_cache(payload, now=100.0)
    assert read_health_cache(now=100.0 + TTL_SECONDS - 0.1) is payload
    assert read_health_cache(now=100.0 + TTL_SECONDS) is None


def test_health_cache_clear() -> None:
    write_health_cache({"status": "ok"}, now=1.0)
    clear_health_cache()
    assert read_health_cache(now=1.0) is None
