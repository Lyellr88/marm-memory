import importlib
import os
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _reimport(monkeypatch, tmp_path, analytics_path=None):
    for name in list(sys.modules):
        if name == "marm_mcp_server" or name.startswith("marm_mcp_server."):
            monkeypatch.delitem(sys.modules, name)

    monkeypatch.setenv("MARM_DB_PATH", str(tmp_path / "memory.db"))
    if analytics_path is None:
        monkeypatch.delenv("MARM_ANALYTICS_DB_PATH", raising=False)
    else:
        monkeypatch.setenv("MARM_ANALYTICS_DB_PATH", str(analytics_path))

    settings = importlib.import_module("marm_mcp_server.config.settings")
    server = importlib.import_module("marm_mcp_server.server")
    analytics = importlib.import_module("marm_mcp_server.services.analytics")
    return settings, server, analytics


def _events(db_path):
    with sqlite3.connect(str(db_path)) as conn:
        return conn.execute(
            "SELECT event_type, endpoint, user_agent, ip_address FROM usage_events"
        ).fetchall()


def _recall_through_http(app) -> None:
    client = TestClient(app, client=("127.0.0.1", 50000))
    try:
        response = client.post(
            "/marm_smart_recall",
            headers={"user-agent": "regression-probe/1.0"},
            json={"query": "analytics route regression", "limit": 1},
        )
    finally:
        client.close()
    assert response.status_code == 200


def test_endpoint_tracking_writes_to_the_configured_analytics_db(monkeypatch, tmp_path):
    """The configured path is honored, and nothing lands in the launch directory.

    Nested on purpose: the setting's own resolver creates the parent directory,
    so a configured path pointing somewhere that does not exist yet still has to
    work rather than falling back to a relative name.
    """
    configured = tmp_path / "nested" / "analytics.db"
    launch_dir = tmp_path / "launch"
    launch_dir.mkdir()

    _, server, _ = _reimport(monkeypatch, tmp_path, configured)
    monkeypatch.chdir(launch_dir)

    _recall_through_http(server.app)

    assert configured.exists(), "the configured analytics database was not written"
    assert _events(configured) == [
        ("endpoint_usage", "marm_smart_recall", "regression-probe/1.0", "127.0.0.1")
    ]
    assert list(launch_dir.iterdir()) == [], (
        f"a database was created in the launch directory: "
        f"{[p.name for p in launch_dir.iterdir()]}"
    )


def test_endpoint_and_lifecycle_tracking_share_one_database(monkeypatch, tmp_path):
    """One table, one file. These were two independent writers.

    Without this, a future cleanup could reintroduce a second writer with its own
    path and nothing would notice: the endpoint rows would simply stop appearing
    alongside the startup and shutdown rows.
    """
    configured = tmp_path / "shared" / "analytics.db"
    launch_dir = tmp_path / "launch"
    launch_dir.mkdir()

    _, server, analytics = _reimport(monkeypatch, tmp_path, configured)
    monkeypatch.chdir(launch_dir)

    analytics.track_usage("server_startup", user_data={"version": "test"})
    _recall_through_http(server.app)

    assert [row[0] for row in _events(configured)] == [
        "server_startup",
        "endpoint_usage",
    ]
    assert list(launch_dir.iterdir()) == []


@pytest.mark.skipif(
    os.path.exists("/app/data"),
    reason="the Docker branch owns the default path when /app/data exists",
)
def test_default_analytics_path_is_under_the_marm_home(monkeypatch, tmp_path):
    """With nothing configured, the default must not be relative to the CWD.

    This is the common case, and the one the earlier fix missed: delegating to
    track_usage corrected the configured and Docker paths while the fallback was
    still a bare filename, so a default install kept dropping the file wherever
    it was started from. The memory database has always defaulted under ~/.marm.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))

    launch_dir = tmp_path / "launch"
    launch_dir.mkdir()
    monkeypatch.chdir(launch_dir)

    settings, server, _ = _reimport(monkeypatch, tmp_path, analytics_path=None)

    resolved = Path(settings.ANALYTICS_DB_PATH)
    assert resolved.is_absolute(), f"default is not absolute: {resolved}"
    assert fake_home in resolved.parents, f"default is outside the home: {resolved}"

    _recall_through_http(server.app)

    assert _events(resolved)
    assert list(launch_dir.iterdir()) == []
