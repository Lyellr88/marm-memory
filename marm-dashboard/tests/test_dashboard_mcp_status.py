import json
import urllib.error
import urllib.request

from conftest import load_dashboard, local_client


def test_mcp_status_unreachable_when_probe_fails(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(urllib.error.URLError("connection refused")),
    )

    client = local_client(server.app)
    res = client.get("/api/mcp-status")
    assert res.status_code == 200
    assert res.json()["reachable"] is False


def test_mcp_status_reachable_when_mcp_responds(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)

    health_body = {"status": "healthy", "service": "MARM MCP Server", "version": "2.2.7"}

    class _FakeResp:
        def read(self):
            return json.dumps(health_body).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: _FakeResp())

    client = local_client(server.app)
    res = client.get("/api/mcp-status")

    assert res.status_code == 200
    data = res.json()
    assert data["reachable"] is True
    assert data["body"]["version"] == "2.2.7"
    assert data["body"]["service"] == "MARM MCP Server"


def test_mcp_status_handles_non_200_response_gracefully(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(urllib.error.URLError("connection refused")),
    )

    client = local_client(server.app)
    res = client.get("/api/mcp-status")

    assert res.status_code == 200
    assert res.json()["reachable"] is False
