"""get_dashboard_app()'s failure isolation: any import-time failure in
marm-dashboard (not just it being uninstalled) must degrade to None, not
crash the parent memory/graph server.
"""

import sys

import pytest


def _purge_dashboard_modules():
    for name in list(sys.modules):
        if name == "marm_dashboard" or name.startswith("marm_dashboard."):
            del sys.modules[name]


def test_dashboard_mount_survives_non_import_error_during_dashboard_import(
    monkeypatch,
):
    """A real, non-contrived failure mode: marm_dashboard.config parses
    MARM_DASHBOARD_PORT with a bare int() at module level, so a malformed
    value raises ValueError (not ImportError) the moment marm_dashboard.server
    is imported. get_dashboard_app() must catch this too.

    Requires marm_dashboard actually installed -- it's a docker-only extra
    (pyproject.toml's docker-image group), absent from the plain pip/CI
    install path by design, so this test would otherwise pass for the wrong
    reason (ModuleNotFoundError instead of the intended ValueError).
    """
    pytest.importorskip("marm_dashboard")
    _purge_dashboard_modules()
    monkeypatch.setenv("MARM_DASHBOARD_PORT", "not-a-number")

    from marm_mcp_server.core.dashboard_mount import get_dashboard_app

    assert get_dashboard_app() is None


def test_dashboard_mount_returns_app_when_import_succeeds(monkeypatch):
    """Requires marm_dashboard actually installed -- see skip note above."""
    pytest.importorskip("marm_dashboard")
    _purge_dashboard_modules()
    monkeypatch.delenv("MARM_DASHBOARD_PORT", raising=False)

    from marm_mcp_server.core.dashboard_mount import get_dashboard_app

    app = get_dashboard_app()

    assert app is not None
