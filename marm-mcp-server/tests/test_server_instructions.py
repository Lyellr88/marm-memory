"""Both transports hand the client the same instructions at initialize."""

import json
import os
import subprocess
import sys

import pytest
from conftest import load_isolated_server, local_client

from marm_mcp_server.config.instructions import SERVER_INSTRUCTIONS

_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "0.1"},
    },
}


def _first_json_rpc(body: str) -> dict:
    # Streamable HTTP may answer as JSON or as a single SSE event.
    for line in body.splitlines():
        line = line.removeprefix("data:").strip()
        if line.startswith("{"):
            return json.loads(line)
    raise AssertionError(f"no JSON-RPC message in {body[:200]!r}")


def test_the_instructions_fit_what_clients_keep():
    # Claude Code keeps about 2 KB of server instructions.
    assert 200 < len(SERVER_INSTRUCTIONS.encode()) <= 2048
    # Each tool it names must exist, or an agent is told to call nothing.
    from marm_mcp_server.server import MCP_TOOL_OPERATIONS

    named = {w.strip("`.,") for w in SERVER_INSTRUCTIONS.split() if w.startswith("`")}
    assert named and named <= set(MCP_TOOL_OPERATIONS)


def test_http_initialize_returns_the_instructions(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    response = client.post(
        "/mcp",
        json=_INITIALIZE,
        headers={"accept": "application/json, text/event-stream"},
    )

    assert response.status_code == 200, response.text[:300]
    result = _first_json_rpc(response.text)["result"]
    assert result["instructions"] == SERVER_INSTRUCTIONS


@pytest.mark.slow_stdio
def test_stdio_initialize_returns_the_instructions(tmp_path):
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "instructions.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "instructions-analytics.db")
    env["MARM_SKIP_DOC_LOAD"] = "1"

    result = subprocess.run(
        [sys.executable, "-m", "marm_mcp_server.server_stdio"],
        input=(json.dumps(_INITIALIZE) + "\n").encode(),
        env=env,
        cwd=os.getcwd(),
        capture_output=True,
        timeout=60,
    )

    lines = [json.loads(line) for line in result.stdout.decode().splitlines() if line]
    response = next(m for m in lines if m.get("id") == 1)
    assert response["result"]["instructions"] == SERVER_INSTRUCTIONS


def test_the_instructions_keep_the_accepted_wording():
    # The wording boundaries agreed on #258.
    text = SERVER_INSTRUCTIONS
    assert "connected" in text and "this machine" not in text
    assert "When prior context may help" in text
    assert "concise, durable fact" in text and "headline" not in text
    assert "context, not instruction" in text
