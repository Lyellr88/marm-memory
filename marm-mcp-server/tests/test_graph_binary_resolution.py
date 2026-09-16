import asyncio
import os
import shutil
import sys

import pytest


@pytest.fixture
def engine_config(monkeypatch, tmp_path):
    from codebase_memory_mcp import _cli

    from marm_graph.config import settings

    cached = tmp_path / "cached-engine"
    monkeypatch.setattr(_cli, "_bin_path", lambda version: cached)
    monkeypatch.setattr(settings, "CBM_BINARY_PATH", "")
    monkeypatch.setattr(settings, "_CBM_COMMAND_RAW", "")
    monkeypatch.setattr(settings, "CBM_CWD", str(tmp_path))
    return settings, cached


def executable(path):
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_worker_primes_configured_binary_without_cached_engine(
    engine_config, monkeypatch
):
    from marm_mcp_server.core import graph_index_worker as module

    settings, cached = engine_config
    binary = executable(cached.with_name("docker-engine"))
    monkeypatch.setattr(settings, "CBM_BINARY_PATH", str(binary))
    started = []
    monkeypatch.setattr(
        module.graph_supervisor, "is_available", lambda: started.append(True)
    )

    worker = module.GraphIndexWorker()
    try:
        asyncio.run(worker._prime_engine())
        assert started == [True]
        assert worker.binary_present()
        assert settings.cbm_spawn_command() == [str(binary)]
    finally:
        worker._watcher.stop()


def test_configured_missing_path_is_distinct_and_does_not_fall_back(
    engine_config, monkeypatch
):
    from marm_mcp_server.core import graph_index_worker as module

    settings, cached = engine_config
    executable(cached)
    monkeypatch.setattr(settings, "CBM_BINARY_PATH", str(cached.with_name("missing")))
    logs = []
    monkeypatch.setattr(
        module.logger, "info", lambda event, **fields: logs.append((event, fields))
    )
    monkeypatch.setattr(
        module.graph_supervisor,
        "is_available",
        lambda: pytest.fail("missing override must stay dormant"),
    )

    worker = module.GraphIndexWorker()
    try:
        asyncio.run(worker._prime_engine())
        assert not worker.binary_present()
        assert (
            "graph_auto_index.dormant",
            {"reason": "configured_binary_missing"},
        ) in logs
    finally:
        worker._watcher.stop()


def test_pip_cache_is_checked_without_changing_the_lazy_launcher(engine_config):
    from marm_mcp_server.core.graph_index_worker import GraphIndexWorker

    settings, cached = engine_config
    assert not GraphIndexWorker.binary_present()
    assert settings.cbm_spawn_command() == [sys.executable, "-m", "codebase_memory_mcp"]
    executable(cached)
    assert GraphIndexWorker.binary_present()
    assert settings.cbm_spawn_command() == [sys.executable, "-m", "codebase_memory_mcp"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable permissions")
def test_non_executable_override_is_dormant(engine_config, monkeypatch):
    from marm_mcp_server.core.graph_index_worker import GraphIndexWorker

    settings, cached = engine_config
    binary = cached.with_name("not-executable")
    binary.write_text("data", encoding="utf-8")
    binary.chmod(0o644)
    monkeypatch.setattr(settings, "CBM_BINARY_PATH", str(binary))
    assert not GraphIndexWorker.binary_present()
    assert settings.cbm_binary_status() == "configured_binary_not_executable"


def test_configured_command_uses_its_executable_not_pip_cache(
    engine_config, monkeypatch
):
    from marm_mcp_server.core.graph_index_worker import GraphIndexWorker

    settings, _ = engine_config
    monkeypatch.setattr(settings, "_CBM_COMMAND_RAW", f'"{sys.executable}" -m example')
    assert settings.cbm_spawn_command() == [sys.executable, "-m", "example"]
    assert GraphIndexWorker.binary_present()


def test_invalid_command_stays_dormant(engine_config, monkeypatch):
    from marm_mcp_server.core.graph_index_worker import GraphIndexWorker

    settings, _ = engine_config
    monkeypatch.setattr(settings, "_CBM_COMMAND_RAW", '"unclosed')
    assert not GraphIndexWorker.binary_present()
    assert settings.cbm_binary_status() == "configured_command_invalid"


def test_binary_override_takes_precedence_over_command(engine_config, monkeypatch):
    from marm_mcp_server.core.graph_index_worker import GraphIndexWorker

    settings, cached = engine_config
    monkeypatch.setattr(settings, "CBM_BINARY_PATH", str(cached))
    monkeypatch.setattr(settings, "_CBM_COMMAND_RAW", f'"{sys.executable}"')
    assert not GraphIndexWorker.binary_present()
    assert settings.cbm_spawn_command() == [str(cached)]


def test_relative_binary_resolves_from_child_working_directory(
    engine_config, monkeypatch
):
    from marm_mcp_server.core.graph_index_worker import GraphIndexWorker

    settings, cached = engine_config
    executable(cached)
    monkeypatch.setattr(settings, "CBM_BINARY_PATH", "./cached-engine")
    assert GraphIndexWorker.binary_present()
    assert settings.cbm_spawn_command() == ["./cached-engine"]


def test_command_resolves_on_path(engine_config, monkeypatch):
    from marm_mcp_server.core.graph_index_worker import GraphIndexWorker

    settings, _ = engine_config
    from pathlib import Path

    monkeypatch.setenv("PATH", str(Path(sys.executable).parent))
    monkeypatch.setattr(settings, "_CBM_COMMAND_RAW", Path(sys.executable).name)
    assert GraphIndexWorker.binary_present()


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO permissions")
@pytest.mark.parametrize("setting", ["CBM_BINARY_PATH", "_CBM_COMMAND_RAW"])
def test_bare_launcher_must_be_a_regular_file(engine_config, monkeypatch, setting):
    from marm_mcp_server.core import graph_index_worker as module

    settings, cached = engine_config
    fifo = cached.with_name("engine-fifo")
    os.mkfifo(fifo, 0o755)
    monkeypatch.setenv("PATH", str(fifo.parent))
    monkeypatch.setattr(settings, setting, fifo.name)
    assert shutil.which(fifo.name) == str(fifo)
    monkeypatch.setattr(
        module.graph_supervisor,
        "is_available",
        lambda: pytest.fail("a FIFO must not be used as an engine launcher"),
    )
    worker = module.GraphIndexWorker()
    try:
        asyncio.run(worker._prime_engine())
        assert not worker.binary_present()
        prefix = (
            "configured_binary"
            if setting == "CBM_BINARY_PATH"
            else "configured_command"
        )
        assert settings.cbm_binary_status() == f"{prefix}_missing"
    finally:
        worker._watcher.stop()


def test_configured_engine_does_not_log_a_pip_download(engine_config, monkeypatch):
    import importlib

    module = importlib.import_module("marm_mcp_server.core.graph_supervisor")
    settings, cached = engine_config
    monkeypatch.setattr(
        settings, "CBM_BINARY_PATH", str(executable(cached.with_name("engine")))
    )
    logs = []
    monkeypatch.setattr(
        module.logger, "info", lambda event, **fields: logs.append(event)
    )
    module.GraphSupervisor._log_first_run_download()
    assert logs == []
    monkeypatch.setattr(settings, "CBM_BINARY_PATH", "")
    module.GraphSupervisor._log_first_run_download()
    assert logs == ["MARM: downloading graph engine (~269MB, one-time)..."]
