"""HTTP-surface tests: MCP tool whitelist, auth, and UI-only guards.

Uses httpx ASGITransport (no bound port). Async calls are driven via asyncio.run
so no pytest-asyncio dependency is needed.
"""

import asyncio

import httpx
import pytest

from marm_graph import server
from conftest import requires_binary

AUTH = {"Authorization": "Bearer testkey"}


def _req(method: str, path: str, **kw) -> httpx.Response:
    async def go():
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            return await ac.request(method, path, **kw)

    return asyncio.run(go())


# ── structural: MCP surface is exactly the 5 AI tools ───────────────


def test_mcp_exposes_exactly_five_ai_tools():
    names = set(server.mcp.tools.keys()) if isinstance(server.mcp.tools, dict) else {
        t.name for t in server.mcp.tools
    }
    assert names == set(server.AI_OPERATIONS)
    assert len(names) == 5


def test_no_ui_operation_in_mcp_surface():
    names = set(server.mcp.tools.keys()) if isinstance(server.mcp.tools, dict) else {
        t.name for t in server.mcp.tools
    }
    assert not any("ui_" in n for n in names)


# ── schema contract: startup must fail on a missing upstream tool ───


def test_check_schema_raises_on_missing_expected_tool():
    names = set(server._EXPECTED_UPSTREAM_TOOLS)
    names.discard("search_graph")
    with pytest.raises(RuntimeError):
        server._check_schema(names)


def test_check_schema_allows_all_expected_plus_extra():
    names = set(server._EXPECTED_UPSTREAM_TOOLS) | {"a_new_upstream_tool"}
    server._check_schema(names)  # extra tools are forward-compatible, no raise


# ── auth (no binary needed) ─────────────────────────────────────────


def test_health_is_public():
    r = _req("GET", "/health")
    assert r.status_code == 200
    assert r.json()["server_version"] == server.settings.SERVER_VERSION


def test_unauthenticated_tool_call_rejected():
    r = _req("POST", "/tools/code_lookup", json={"query": "x"})
    assert r.status_code == 401


def test_unauthenticated_ui_call_rejected():
    r = _req("POST", "/ui/projects", json={})
    assert r.status_code == 401


# ── UI guards (return before touching the backend) ──────────────────


def test_delete_project_requires_confirmation():
    r = _req(
        "POST", "/ui/delete_project",
        json={"project": "anything", "confirm": False}, headers=AUTH,
    )
    assert r.json()["status"] == "confirmation_required"


def test_query_graph_rejects_write_clauses():
    r = _req(
        "POST", "/ui/query_graph",
        json={"project": "p", "query": "MATCH (n) DELETE n"}, headers=AUTH,
    )
    assert r.json()["status"] == "rejected"


# ── integration (real backend) ──────────────────────────────────────


@requires_binary
def test_authed_code_lookup_returns_results(client, project):
    r = _req(
        "POST", "/tools/code_lookup",
        json={"query": "CbmClient", "project": project}, headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json()["results"]


@requires_binary
def test_query_graph_read_executes(client, project):
    r = _req(
        "POST", "/ui/query_graph",
        json={"project": project, "query": "MATCH (n) RETURN count(n) AS c"},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json().get("status") != "error"
