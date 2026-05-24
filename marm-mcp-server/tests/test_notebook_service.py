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

    memory._encoder_failed = True
    memory.active_notebook_entries = []

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
    assert memory.active_notebook_entries[0]["name"] == "rule_c"


@pytest.mark.asyncio
async def test_dispatch_status_reflects_active_entries(notebook_svc):
    dispatch, memory = notebook_svc
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
    assert memory.active_notebook_entries == []


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
    assert memory.active_notebook_entries == []
