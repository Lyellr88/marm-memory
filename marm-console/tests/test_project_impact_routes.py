"""The change-impact proxy, against the shape the engine really returns.

This route reported "No impact detected" for a repository with 864 impacted
symbols, for as long as it has existed. It read `affected_symbols` / `affected`
and the engine returns **`impacted_symbols`**; the per-row names were wrong too
(`qn` and `file`, not `qualified_name` and `file_path`). Nothing caught it
because nothing asserted the proxy against a real engine payload -- so that is
what this file does.
"""

import pytest
from fastapi.testclient import TestClient
from marm_mcp_server.console import app as console_app

#: Copied from a live `marm_graph_impact` response, trimmed. The field names
#: here are the point of the file; do not "tidy" them to match the browser.
ENGINE = {
    "base": "HEAD~30",
    "merge_base": "b0c6b83",
    "direction": "inbound",
    "changed_files": ["Cargo.lock", "crates/nes-ppu/src/ppu.rs"],
    "seed_symbols": 905,
    "impacted_total": 864,
    "impacted_shown": 2,
    "impacted_modules": [{"module": "crates/nes-netplay", "count": 96}],
    "truncated": False,
    "impacted_symbols": [
        {
            "qn": "proj.crates.nes-netplay.src.transport.rs.__file__",
            "label": "File",
            "file": "crates/nes-netplay/src/transport.rs",
            "hop": 1,
        },
        {
            "qn": "proj.crates.nes-frontend.src.app.rs.__file__",
            "label": "File",
            "file": "crates/nes-frontend/src/app.rs",
            "hop": 2,
        },
    ],
}


def _client(monkeypatch, payload):
    monkeypatch.setattr(console_app.mcp_client, "post", lambda *a, **k: payload)
    return TestClient(console_app.app)


def test_the_engine_key_is_impacted_symbols(monkeypatch):
    client = _client(monkeypatch, ENGINE)
    body = client.post("/api/projects/p/impact", json={"since": "HEAD~30"}).json()

    assert len(body["affected_symbols"]) == 2, "the engine's list was dropped"


def test_rows_are_renamed_to_the_browser_contract(monkeypatch):
    client = _client(monkeypatch, ENGINE)
    row = client.post("/api/projects/p/impact", json={}).json()["affected_symbols"][0]

    assert row["qualified_name"].endswith("transport.rs.__file__")
    assert row["file_path"] == "crates/nes-netplay/src/transport.rs"
    assert row["hop"] == 1
    assert row["label"] == "File"


def test_no_risk_is_invented(monkeypatch):
    """The old mapping defaulted `risk` to 'low' for a field the engine does
    not send, so every row claimed an assessment nothing had made."""
    client = _client(monkeypatch, ENGINE)
    row = client.post("/api/projects/p/impact", json={}).json()["affected_symbols"][0]

    assert "risk" not in row


def test_the_engine_cap_is_reported(monkeypatch):
    """200 rows shown out of 864 reads as "all of them" without this."""
    client = _client(monkeypatch, ENGINE)
    body = client.post("/api/projects/p/impact", json={}).json()

    assert body["impacted_total"] == 864
    assert body["impacted_shown"] == 2
    assert body["impacted_modules"][0]["module"] == "crates/nes-netplay"


def test_an_absent_hop_stays_absent(monkeypatch):
    """None, not 0: an unknown distance and "is itself a changed file" are
    different claims."""
    payload = dict(ENGINE, impacted_symbols=[{"qn": "a", "file": "a.rs"}])
    client = _client(monkeypatch, payload)
    row = client.post("/api/projects/p/impact", json={}).json()["affected_symbols"][0]

    assert row["hop"] is None


@pytest.mark.parametrize("key", ["affected_symbols", "affected"])
def test_older_engine_key_names_still_work(monkeypatch, key):
    """The fallbacks are kept so a different engine build does not regress
    this back to an empty list."""
    payload = {"changed_files": [], key: [{"qualified_name": "x", "file_path": "x.rs"}]}
    client = _client(monkeypatch, payload)
    body = client.post("/api/projects/p/impact", json={}).json()

    assert body["affected_symbols"][0]["qualified_name"] == "x"


def test_an_empty_result_is_still_empty(monkeypatch):
    client = _client(monkeypatch, {"changed_files": [], "impacted_symbols": []})
    body = client.post("/api/projects/p/impact", json={}).json()

    assert body["affected_symbols"] == []
    assert body["impacted_total"] == 0
