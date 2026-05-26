import sys
import pytest


@pytest.fixture
def notebook_svc(monkeypatch, tmp_path):
    for name in list(sys.modules):
        if name == "marm_mcp_server" or name.startswith("marm_mcp_server."):
            del sys.modules[name]

    monkeypatch.setenv("MARM_DB_PATH", str(tmp_path / "nb-test.db"))
    monkeypatch.setenv("MARM_ANALYTICS_DB_PATH", str(tmp_path / "nb-analytics.db"))

    from marm_mcp_server.services.notebook import notebook_dispatch
    from marm_mcp_server.core.memory import memory

    monkeypatch.setattr(memory, "_encoder_failed", True)
    monkeypatch.setattr(memory, "active_notebook_entries_by_session", {})

    return notebook_dispatch, memory


@pytest.mark.asyncio
async def test_dispatch_add_saves_entry_and_returns_success(notebook_svc):
    dispatch, _ = notebook_svc
    result = await dispatch(action="add", name="rule_a", data="always use snake_case")
    assert result["status"] == "success"
    assert result["name"] == "rule_a"


@pytest.mark.asyncio
async def test_dispatch_show_returns_added_entry(notebook_svc):
    dispatch, _ = notebook_svc
    await dispatch(action="add", name="rule_b", data="keep responses short")
    result = await dispatch(action="show")
    assert result["status"] == "success"
    assert result["total_count"] == 1
    assert result["entries"][0]["name"] == "rule_b"


@pytest.mark.asyncio
async def test_dispatch_use_activates_existing_entry(notebook_svc):
    dispatch, memory = notebook_svc
    await dispatch(action="add", name="rule_c", data="cite sources")
    result = await dispatch(action="use", names="rule_c")
    assert result["status"] == "success"
    assert "rule_c" in result["activated_entries"]
    assert memory.get_active_notebook_entries("main")[0]["name"] == "rule_c"


@pytest.mark.asyncio
async def test_dispatch_status_reflects_active_entries(notebook_svc):
    dispatch, _ = notebook_svc
    await dispatch(action="add", name="rule_d", data="be direct")
    await dispatch(action="use", names="rule_d")
    result = await dispatch(action="status")
    assert result["status"] == "success"
    assert result["active_count"] == 1
    assert "rule_d" in result["active_entries"]


@pytest.mark.asyncio
async def test_dispatch_clear_empties_active_entries(notebook_svc):
    dispatch, memory = notebook_svc
    await dispatch(action="add", name="rule_e", data="no padding")
    await dispatch(action="use", names="rule_e")
    result = await dispatch(action="clear")
    assert result["status"] == "success"
    assert result["active_count"] == 0
    assert memory.get_active_notebook_entries("main") == []


@pytest.mark.asyncio
async def test_dispatch_add_missing_name_returns_error(notebook_svc):
    dispatch, _ = notebook_svc
    result = await dispatch(action="add", name=None, data="some data")
    assert result["status"] == "error"
    assert "name" in result["message"]


@pytest.mark.asyncio
async def test_dispatch_add_missing_data_returns_error(notebook_svc):
    dispatch, _ = notebook_svc
    result = await dispatch(action="add", name="rule_f", data=None)
    assert result["status"] == "error"
    assert "data" in result["message"]


@pytest.mark.asyncio
async def test_dispatch_use_missing_names_returns_error(notebook_svc):
    dispatch, _ = notebook_svc
    result = await dispatch(action="use", names=None)
    assert result["status"] == "error"
    assert "names" in result["message"]


@pytest.mark.asyncio
async def test_dispatch_add_blank_name_returns_error(notebook_svc):
    dispatch, _ = notebook_svc
    result = await dispatch(action="add", name="   ", data="some data")
    assert result["status"] == "error"
    assert "name" in result["message"]


@pytest.mark.asyncio
async def test_dispatch_use_comma_only_names_returns_error(notebook_svc):
    dispatch, _ = notebook_svc
    result = await dispatch(action="use", names="  ,  ,  ")
    assert result["status"] == "error"
    assert "names" in result["message"]


@pytest.mark.asyncio
async def test_dispatch_unknown_action_returns_error(notebook_svc):
    dispatch, _ = notebook_svc
    result = await dispatch(action="explode")
    assert result["status"] == "error"
    assert "explode" in result["message"]


@pytest.mark.asyncio
async def test_dispatch_use_silently_skips_nonexistent_entries(notebook_svc):
    dispatch, memory = notebook_svc
    result = await dispatch(action="use", names="ghost_entry")
    assert result["status"] == "success"
    assert result["activated_entries"] == []
    assert memory.get_active_notebook_entries("main") == []


@pytest.mark.asyncio
async def test_dispatch_scopes_active_entries_by_session(notebook_svc):
    dispatch, memory = notebook_svc
    await dispatch(action="add", name="alpha_rule", data="alpha instructions")
    await dispatch(action="add", name="beta_rule", data="beta instructions")

    await dispatch(action="use", names="alpha_rule", session_name="alpha")
    await dispatch(action="use", names="beta_rule", session_name="beta")

    alpha = await dispatch(action="status", session_name="alpha")
    beta = await dispatch(action="status", session_name="beta")

    assert alpha["active_entries"] == ["alpha_rule"]
    assert beta["active_entries"] == ["beta_rule"]
    assert memory.get_active_notebook_entries("alpha")[0]["name"] == "alpha_rule"
    assert memory.get_active_notebook_entries("beta")[0]["name"] == "beta_rule"


@pytest.mark.asyncio
async def test_dispatch_clear_only_clears_requested_session(notebook_svc):
    dispatch, _ = notebook_svc
    await dispatch(action="add", name="alpha_rule", data="alpha instructions")
    await dispatch(action="add", name="beta_rule", data="beta instructions")
    await dispatch(action="use", names="alpha_rule", session_name="alpha")
    await dispatch(action="use", names="beta_rule", session_name="beta")

    cleared = await dispatch(action="clear", session_name="alpha")
    beta = await dispatch(action="status", session_name="beta")

    assert cleared["active_count"] == 0
    assert beta["active_entries"] == ["beta_rule"]


@pytest.mark.asyncio
async def test_dispatch_normalizes_session_name(notebook_svc):
    dispatch, memory = notebook_svc
    await dispatch(action="add", name="alpha_rule", data="alpha instructions")

    await dispatch(action="use", names="alpha_rule", session_name="  alpha  ")
    result = await dispatch(action="status", session_name="alpha")

    assert result["active_entries"] == ["alpha_rule"]
    assert memory.get_active_notebook_entries("alpha")[0]["name"] == "alpha_rule"
    assert "  alpha  " not in memory.active_notebook_entries_by_session


@pytest.mark.asyncio
async def test_dispatch_blank_session_name_returns_error(notebook_svc):
    dispatch, _ = notebook_svc

    result = await dispatch(action="status", session_name="")
    padded_result = await dispatch(action="status", session_name="   ")

    assert result["status"] == "error"
    assert "session_name" in result["message"]
    assert padded_result["status"] == "error"
    assert "session_name" in padded_result["message"]


@pytest.mark.asyncio
async def test_memory_remove_active_notebook_entry_cleans_all_sessions(notebook_svc):
    dispatch, memory = notebook_svc
    await dispatch(action="add", name="shared_rule", data="shared instructions")
    await dispatch(action="use", names="shared_rule", session_name="alpha")
    await dispatch(action="use", names="shared_rule", session_name="beta")

    memory.remove_active_notebook_entry("shared_rule")

    assert memory.get_active_notebook_entries("alpha") == []
    assert memory.get_active_notebook_entries("beta") == []
