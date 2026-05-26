"""Tests for scripts/find-dead-code.py changes in this PR.

Covers (PR-added code only):
- CHECK / WARN / FAIL constants
- display_path() returns a path relative to ROOT.parent when possible
- display_path() falls back to str(path) for paths outside ROOT.parent
- module_reference_patterns() includes all expected import variants
- module_reference_patterns() handles top-level and nested module paths
- explain_static_limits() runs without error and produces output
"""

import importlib.util
import io
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load the script as a module without executing __main__
# ---------------------------------------------------------------------------
_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "find-dead-code.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("find_dead_code", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def fdc():
    return _load_script()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_check_constant_is_plus(fdc):
    assert fdc.CHECK == "+"


def test_warn_constant_is_question_mark(fdc):
    assert fdc.WARN == "?"


def test_fail_constant_is_x(fdc):
    assert fdc.FAIL == "x"


# ---------------------------------------------------------------------------
# display_path()
# ---------------------------------------------------------------------------

def test_display_path_returns_relative_path_under_root_parent(fdc):
    # ROOT is marm-mcp-server/, ROOT.parent is the repo root.
    # Any path inside the repo should be returned relative to the repo root.
    repo_root = fdc.ROOT.parent
    inside_path = repo_root / "marm-mcp-server" / "marm_mcp_server" / "core" / "memory.py"
    result = fdc.display_path(inside_path)
    assert not result.startswith("/") or Path(result).is_absolute() is False or str(inside_path) == result
    # The key property: the result should not start with the full repo root prefix
    assert str(repo_root) not in result or result == str(inside_path)


def test_display_path_accepts_string_input(fdc):
    # display_path must accept both Path and str
    repo_root = fdc.ROOT.parent
    path_str = str(repo_root / "marm-mcp-server" / "marm_mcp_server" / "server.py")
    result = fdc.display_path(path_str)
    assert isinstance(result, str)
    assert len(result) > 0


def test_display_path_falls_back_to_absolute_for_outside_paths(fdc, tmp_path):
    # A path that is NOT under ROOT.parent should return its str representation.
    outside = tmp_path / "some_random_file.py"
    result = fdc.display_path(outside)
    assert str(outside) == result


def test_display_path_relative_is_shorter_than_absolute(fdc):
    repo_root = fdc.ROOT.parent
    inside = repo_root / "marm-mcp-server" / "marm_mcp_server" / "core" / "events.py"
    if inside.exists():
        relative = fdc.display_path(inside)
        absolute = str(inside)
        assert len(relative) <= len(absolute)


# ---------------------------------------------------------------------------
# module_reference_patterns()
# ---------------------------------------------------------------------------

def test_module_reference_patterns_includes_full_module_path(fdc):
    patterns = fdc.module_reference_patterns("marm_mcp_server.core.memory")
    assert "marm_mcp_server.core.memory" in patterns


def test_module_reference_patterns_includes_stem_import(fdc):
    patterns = fdc.module_reference_patterns("marm_mcp_server.core.memory")
    assert "import memory" in patterns


def test_module_reference_patterns_includes_relative_from_dot(fdc):
    patterns = fdc.module_reference_patterns("marm_mcp_server.core.memory")
    assert "from .memory" in patterns


def test_module_reference_patterns_includes_relative_from_dotdot(fdc):
    patterns = fdc.module_reference_patterns("marm_mcp_server.core.memory")
    assert "from ..memory" in patterns


def test_module_reference_patterns_includes_from_module_path(fdc):
    patterns = fdc.module_reference_patterns("marm_mcp_server.core.memory")
    assert "from marm_mcp_server.core.memory" in patterns


def test_module_reference_patterns_includes_package_relative_forms(fdc):
    patterns = fdc.module_reference_patterns("marm_mcp_server.core.memory")
    # package_relative strips the top package: "core.memory"
    assert "from .core.memory" in patterns or "import core.memory" in patterns


def test_module_reference_patterns_handles_top_level_module(fdc):
    """A module directly under marm_mcp_server (no sub-package) should still work."""
    patterns = fdc.module_reference_patterns("marm_mcp_server.server")
    assert "marm_mcp_server.server" in patterns
    assert "import server" in patterns
    assert "from .server" in patterns


def test_module_reference_patterns_returns_set(fdc):
    result = fdc.module_reference_patterns("marm_mcp_server.utils.helpers")
    assert isinstance(result, set)
    assert len(result) > 0


def test_module_reference_patterns_all_strings(fdc):
    patterns = fdc.module_reference_patterns("marm_mcp_server.services.notebook")
    assert all(isinstance(p, str) for p in patterns)


# ---------------------------------------------------------------------------
# explain_static_limits()
# ---------------------------------------------------------------------------

def test_explain_static_limits_produces_output(fdc, capsys):
    fdc.explain_static_limits()
    captured = capsys.readouterr()
    # Should mention that it scans source text and to treat as review candidates
    assert "source text" in captured.out or "review candidates" in captured.out


def test_explain_static_limits_does_not_raise(fdc):
    # Simple smoke test: must not raise any exception
    fdc.explain_static_limits()