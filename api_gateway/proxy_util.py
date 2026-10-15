"""Helpers for the gateway reverse proxy."""

from __future__ import annotations

from collections.abc import Mapping

# Hop-by-hop headers plus encoding/length. httpx already decompresses the body,
# so forwarding content-encoding makes browsers try to decode it a second time.
_DROP_RESPONSE_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-encoding",
        "content-length",
    }
)


def filtered_response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Copy upstream headers that are safe to return to the browser."""
    return {key: value for key, value in headers.items() if key.lower() not in _DROP_RESPONSE_HEADERS}
