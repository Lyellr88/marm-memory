#!/usr/bin/env python3

import json
import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_TMP = tempfile.mkdtemp(prefix="marm_schema_")
os.environ["MARM_DB_PATH"] = os.path.join(_TMP, "s.db")
os.environ["MARM_ANALYTICS_DB_PATH"] = os.path.join(_TMP, "a.db")
os.environ["SERVER_HOST"] = "127.0.0.1"
os.environ["WRITE_QUEUE_ENABLED"] = "0"
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "marm-mcp-server"))

from fastapi.testclient import TestClient  # noqa: E402
from marm_mcp_server.server import app  # noqa: E402

headers = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}

with TestClient(app, client=("127.0.0.1", 50000)) as client:
    init = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "schema-dump", "version": "0"},
            },
        },
    )
    sid = init.headers.get("mcp-session-id")
    if sid:
        headers["mcp-session-id"] = sid

    client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    )

    resp = client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )

raw = resp.text
if os.environ.get("DEBUG_RAW"):
    print("INIT STATUS:", init.status_code, "SID:", sid)
    print("LIST STATUS:", resp.status_code)
    print("RAW LIST:\n", raw[:3000], "\n---")
payload = None
for line in raw.splitlines():
    line = line.strip()
    if line.startswith("data:"):
        line = line[5:].strip()
    if line.startswith("{"):
        try:
            payload = json.loads(line)
            break
        except json.JSONDecodeError:
            continue

if payload is None:
    print("RAW RESPONSE:\n", raw[:2000])
    sys.exit(1)

tools = payload.get("result", {}).get("tools", [])
print(f"PUBLIC TOOL COUNT: {len(tools)}\n")
print("NAMES:", ", ".join(t["name"] for t in tools), "\n")

for name in ("marm_compaction", "marm_notebook"):
    tool = next((t for t in tools if t["name"] == name), None)
    if not tool:
        print(f"!! {name} not found in tools/list\n")
        continue
    print("=" * 70)
    print(f"TOOL: {name}")
    print("DESCRIPTION:")
    print(tool.get("description", "(none)"))
    print("INPUT SCHEMA:")
    print(json.dumps(tool.get("inputSchema", {}), indent=2))
    print()
