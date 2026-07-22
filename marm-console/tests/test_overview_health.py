"""Overview health-probe tests.

The health probe used to build its own bare urllib request, which
skipped the MARM_API_KEY header the shared mcp_client adapter already
adds to every other console->MCP call. An authenticated MCP instance
would look unreachable from the console for no reason other than a
missing header.
"""

import json

from marm_mcp_server.console import mcp_client
from marm_mcp_server.console.endpoints import overview as overview_endpoint


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = 200

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


def test_mcp_status_sends_api_key_through_shared_client(monkeypatch):
    monkeypatch.setenv("MARM_API_KEY", "console-secret")
    captured: dict = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        return _FakeResponse(
            {
                "status": "healthy",
                "version": "2.23.0",
                "timestamp": "2026-07-18T00:00:00Z",
                "concept_extraction": "available",
            }
        )

    monkeypatch.setattr(mcp_client, "urlopen", fake_urlopen)

    result = overview_endpoint._mcp_status()

    assert captured["url"].endswith("/health")
    assert captured["authorization"] == "Bearer console-secret"
    assert result["reachable"] is True
    assert result["version"] == "2.23.0"
    assert result["concept_extraction"] == "available"


def test_mcp_status_reports_unreachable_without_raising(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise mcp_client.URLError("connection refused")

    monkeypatch.setattr(mcp_client, "urlopen", fake_urlopen)

    result = overview_endpoint._mcp_status()

    assert result == {"reachable": False}
