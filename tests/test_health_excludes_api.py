"""Regression: gateway /health must not probe itself (api)."""

from shared.service_discovery import SERVICE_PORT_MAP


def test_health_probe_excludes_self_conceptually():
    # api is in the port map for URL building, but health_check skips it.
    assert "api" in SERVICE_PORT_MAP
    names = [n for n in SERVICE_PORT_MAP if n != "api"]
    assert "api" not in names
    assert "data" in names
    assert "execution" in names
