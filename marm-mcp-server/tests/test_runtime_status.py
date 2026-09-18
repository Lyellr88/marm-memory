import psutil

from marm_mcp_server.services import runtime_status


def test_knowledge_status_does_not_create_absent_concept_database(
    monkeypatch, tmp_path
):
    concept_path = tmp_path / "missing" / "marm_index.db"
    monkeypatch.setattr(
        runtime_status, "get_default_concept_db_path", lambda: str(concept_path)
    )

    result = runtime_status.knowledge_status()

    assert result["schema"] == "missing"
    assert result["database"]["exists"] is False
    assert not concept_path.exists()
    assert not concept_path.parent.exists()


def test_passive_status_does_not_start_graph(monkeypatch, tmp_path):
    memory_path = tmp_path / "missing-memory.db"
    monkeypatch.setattr(runtime_status, "DEFAULT_DB_PATH", str(memory_path))
    monkeypatch.setattr(
        runtime_status,
        "inspect_runtime",
        lambda: {"state": "stopped", "managed": False},
    )
    monkeypatch.setattr(
        runtime_status,
        "knowledge_status",
        lambda: {
            "state": "ready_no_build",
            "database": {"path": str(tmp_path / "concept.db"), "exists": False},
        },
    )

    result = runtime_status.full_status()

    assert result["projects"] == {"state": "runtime_stopped"}
    assert result["memory"]["exists"] is False
    assert not memory_path.exists()


# --- the runtime must never probe itself over HTTP -------------------------


def test_inspect_runtime_does_not_probe_itself(monkeypatch):
    """Answering the probe is itself the proof, so never send one.

    `request_runtime` blocks, and an async endpoint calling it blocks the very
    event loop that would have to serve the probe. Measured before the fix:
    `/internal/runtime/settings` took 1.04s -- the full timeout -- on a page
    that polls every 5s, and a concurrent request to any other route stalled
    922ms behind it. The probe then returned nothing, so a healthy server
    reported itself as not ready.
    """
    import os

    from marm_mcp_server.core import runtime_manager

    monkeypatch.setattr(
        runtime_manager,
        "read_state",
        lambda: {
            "pid": os.getpid(),
            "process_created_at": psutil.Process(os.getpid()).create_time(),
            "runtime_id": "rid",
            "host": "127.0.0.1",
            "port": 8001,
        },
    )

    def fail(*_args, **_kwargs):
        raise AssertionError("inspect_runtime probed its own process over HTTP")

    monkeypatch.setattr(runtime_manager, "request_runtime", fail)

    result = runtime_manager.inspect_runtime()
    assert result["state"] == "ready"
    assert result["identity_matches"] is True
    # Callers read this as though it came over the wire.
    assert result["runtime"]["write_queue"] is not None
    assert "graph" in result["runtime"], (
        "full_status() reads `graph` from here and otherwise invents "
        "`runtime_stopped` for a running server"
    )


def test_inspect_runtime_still_probes_another_process(monkeypatch):
    """The CLI runs in a separate process, where the probe is the only way to
    know. That path must be left alone."""
    import os

    from marm_mcp_server.core import runtime_manager

    monkeypatch.setattr(
        runtime_manager,
        "read_state",
        lambda: {
            "pid": os.getpid() + 1,
            "runtime_id": "rid",
            "host": "127.0.0.1",
            "port": 8001,
        },
    )
    monkeypatch.setattr(runtime_manager, "process_matches", lambda _state: False)

    probed = []

    def record(path, **kwargs):
        probed.append(path)
        return None

    monkeypatch.setattr(runtime_manager, "request_runtime", record)

    result = runtime_manager.inspect_runtime()
    assert probed == ["/internal/runtime/status"]
    assert result["state"] == "stale"


def test_inspect_runtime_does_not_trust_a_reused_pid(monkeypatch):
    """A stale runtime.json whose pid the OS reused must not look like us.

    The self-snapshot branch keys on `pid == os.getpid()`. If a stale state file
    holds a pid that is later reused -- by the very CLI process doing the
    inspecting -- that test alone is satisfied by coincidence. `stop_runtime()`
    reads the result as `identity_matches` and POSTs shutdown to the host and
    port in the stale file, which a different runtime may now be serving.

    Creation time is what a reused pid cannot forge, so it must be present and
    must match before the branch is taken.
    """
    import os

    from marm_mcp_server.core import runtime_manager

    probed: list[str] = []

    monkeypatch.setattr(
        runtime_manager,
        "read_state",
        lambda: {
            "pid": os.getpid(),
            # the stale file was written by a process that started long ago
            "process_created_at": psutil.Process(os.getpid()).create_time() - 10_000,
            "runtime_id": "stale",
            "host": "127.0.0.1",
            "port": 8001,
        },
    )
    monkeypatch.setattr(
        runtime_manager,
        "request_runtime",
        lambda *a, **k: probed.append("probed") or None,
    )

    result = runtime_manager.inspect_runtime()

    assert result.get("identity_matches") is not True
    assert probed, "a pid that only coincidentally matches must still be probed"
