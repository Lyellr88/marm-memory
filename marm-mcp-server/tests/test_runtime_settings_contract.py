import asyncio
import importlib
import os
import threading
import time

import pytest
from fastapi import HTTPException


def _mod(name: str):
    """Resolve at call time: load_isolated_server reloads these, so a bound import goes stale."""
    return importlib.import_module(name)


def system_module():
    return _mod("marm_mcp_server.endpoints.system")


def settings_module():
    return system_module().settings


def memory_obj():
    return system_module().memory


def limiter():
    return system_module().rate_limiter


@pytest.fixture
def restore_encoder_state():
    m = memory_obj()
    saved = (m.encoder, m._encoder_loading, m._encoder_failed)
    yield
    m.encoder, m._encoder_loading, m._encoder_failed = saved


@pytest.fixture
def restore_rate_limits():
    rl = limiter()
    saved = {name: dict(config) for name, config in rl.limits.items()}
    yield
    rl.limits = saved


def settings_payload() -> dict:
    return asyncio.run(system_module().runtime_settings())


def test_console_contract_carries_rate_limit_search_and_embedding_dimension():
    payload = settings_payload()

    assert set(payload["rate_limit"]) == {
        "requests_per_minute",
        "window_seconds",
        "block_seconds",
        "enforced",
        "environment_default",
    }
    assert set(payload["search"]) == {
        "semantic_enabled",
        "semantic_available",
        "model_state",
    }
    assert isinstance(payload["embedding"]["dimension"], int)
    assert payload["embedding"]["dimension"] > 0
    assert payload["search"]["model_state"] in {
        "loaded",
        "loading",
        "failed",
        "not_loaded",
    }


def test_rate_limit_reports_the_live_limiter_not_the_environment_default(
    restore_rate_limits,
):
    baseline = settings_payload()["rate_limit"]
    assert baseline["requests_per_minute"] == baseline["environment_default"]

    limiter().configure(requests=600, window=60, block_duration=30)
    swarm_max = settings_payload()["rate_limit"]
    assert swarm_max["requests_per_minute"] == 600
    assert swarm_max["enforced"] is True
    assert swarm_max["environment_default"] == baseline["environment_default"]

    limiter().configure(requests=0, window=60, block_duration=30)
    trusted = settings_payload()["rate_limit"]
    assert trusted["requests_per_minute"] == 0
    assert trusted["enforced"] is False


@pytest.mark.parametrize(
    ("encoder", "loading", "failed", "expected"),
    [
        (None, False, False, "not_loaded"),
        (None, True, False, "loading"),
        (None, False, True, "failed"),
        (object(), False, False, "loaded"),
        (object(), False, True, "loaded"),
    ],
)
def test_model_state_reports_the_encoder_not_mere_importability(
    restore_encoder_state, encoder, loading, failed, expected
):
    m = memory_obj()
    m.encoder = encoder
    m._encoder_loading = loading
    m._encoder_failed = failed

    assert settings_payload()["search"]["model_state"] == expected


def test_installed_but_unloaded_model_is_not_reported_as_loaded(restore_encoder_state):
    """A fresh runtime imports fastembed long before any recall loads the encoder."""
    m = memory_obj()
    m.encoder = None
    m._encoder_loading = False
    m._encoder_failed = False

    search = settings_payload()["search"]

    assert search["semantic_available"] is True
    assert search["model_state"] == "not_loaded"


def test_failed_load_is_visible_while_semantic_search_still_reports_available(
    restore_encoder_state,
):
    m = memory_obj()
    m.encoder = None
    m._encoder_loading = False
    m._encoder_failed = True

    search = settings_payload()["search"]

    assert search["semantic_available"] is True
    assert search["model_state"] == "failed"


def profile(name: str, rpm: int | None = None) -> dict:
    return asyncio.run(
        system_module().update_runtime_profile(
            system_module().RuntimeProfileRequest(profile=name, rate_limit_rpm=rpm)
        )
    )


@pytest.fixture
def restore_profile(restore_rate_limits):
    cfg = settings_module()
    mem = _mod("marm_mcp_server.core.memory")
    flags = _mod("marm_mcp_server.core.runtime_flags")
    # apply_runtime_preset writes five module attributes; restoring fewer leaks into later tests.
    saved = {
        "env": os.environ.get("MARM_RUNTIME_PROFILE"),
        "rpm": cfg.MARM_RATE_LIMIT_RPM,
        "queue": cfg.WRITE_QUEUE_ENABLED,
        "trigger": cfg.COMPACTION_TRIGGER_COUNT,
        "mem_queue": mem.WRITE_QUEUE_ENABLED,
        "mem_trigger": mem.COMPACTION_TRIGGER_COUNT,
        "flag_profile": flags.get(flags.RUNTIME_PROFILE),
        "flag_rpm": flags.get(flags.RUNTIME_RATE_LIMIT_RPM),
    }
    yield
    cfg.MARM_RATE_LIMIT_RPM = saved["rpm"]
    cfg.WRITE_QUEUE_ENABLED = saved["queue"]
    cfg.COMPACTION_TRIGGER_COUNT = saved["trigger"]
    mem.WRITE_QUEUE_ENABLED = saved["mem_queue"]
    mem.COMPACTION_TRIGGER_COUNT = saved["mem_trigger"]
    for key, value in (
        (flags.RUNTIME_PROFILE, saved["flag_profile"]),
        (flags.RUNTIME_RATE_LIMIT_RPM, saved["flag_rpm"]),
    ):
        flags.clear(key) if value is None else flags.set_(key, value)
    if saved["env"] is None:
        os.environ.pop("MARM_RUNTIME_PROFILE", None)
    else:
        os.environ["MARM_RUNTIME_PROFILE"] = saved["env"]


@pytest.mark.parametrize(
    ("name", "rpm", "enforced"),
    [
        ("standard", 80, True),
        ("swarm", 200, True),
        ("swarm-max", 600, True),
        ("trusted", 0, False),
    ],
)
def test_each_profile_applies_its_documented_rate_limit(
    restore_profile, name, rpm, enforced
):
    result = profile(name)

    assert result["profile"] == name
    assert result["rate_limit"]["requests_per_minute"] == rpm
    assert result["rate_limit"]["enforced"] is enforced
    assert settings_payload()["rate_limit"]["requests_per_minute"] == rpm


def test_returning_to_standard_restores_the_limit_after_trusted(restore_profile):
    """Trusted sets the limit to 0. Standard has to restore it, not inherit it."""
    profile("trusted")
    assert settings_payload()["rate_limit"]["enforced"] is False

    profile("standard")
    restored = settings_payload()["rate_limit"]

    assert restored["requests_per_minute"] == restored["environment_default"]
    assert restored["enforced"] is True


def test_environment_default_never_moves_as_profiles_change(restore_profile):
    baseline = settings_payload()["rate_limit"]["environment_default"]

    for name in ("swarm", "trusted", "swarm-max", "standard"):
        profile(name)
        assert settings_payload()["rate_limit"]["environment_default"] == baseline


def test_reported_profile_follows_the_applied_profile(restore_profile):
    profile("swarm-max")
    assert settings_payload()["profile"] == "swarm-max"
    profile("standard")
    assert settings_payload()["profile"] == "standard"


def test_custom_rpm_override_is_reported_as_custom_mode(restore_profile):
    result = profile("standard", 45)

    assert result["mode"] == "custom"
    assert settings_payload()["rate_limit"]["requests_per_minute"] == 45


def test_negative_rpm_is_rejected(restore_profile):
    with pytest.raises(HTTPException) as excinfo:
        profile("standard", -1)

    assert excinfo.value.status_code == 422
    assert settings_payload()["rate_limit"]["requests_per_minute"] >= 0


def test_a_profile_change_survives_into_the_next_boot(restore_profile):
    """The Console writes a durable flag; a bare CLI start has to pick it up."""
    flags = _mod("marm_mcp_server.core.runtime_flags")
    resolve = _mod("marm_mcp_server.cli").resolve_runtime_preset

    result = profile("swarm")

    assert result["persistence"] == "saved"
    assert flags.saved_runtime_preset() == ("swarm", None)
    assert resolve(None, None) == ("swarm", None)


def test_an_explicit_cli_profile_beats_the_saved_one(restore_profile):
    resolve = _mod("marm_mcp_server.cli").resolve_runtime_preset
    profile("trusted")

    assert resolve("swarm-max", None) == ("swarm-max", None)


def test_a_saved_custom_rpm_is_restored_on_the_next_boot(restore_profile):
    resolve = _mod("marm_mcp_server.cli").resolve_runtime_preset
    profile("standard", 45)

    assert resolve(None, None) == ("standard", 45)
    assert resolve(None, 99) == ("standard", 99)


def test_applying_a_profile_leaves_no_stale_compaction_trigger(restore_profile):
    cfg = settings_module()
    mem = _mod("marm_mcp_server.core.memory")
    profile("swarm")

    assert cfg.COMPACTION_TRIGGER_COUNT == mem.COMPACTION_TRIGGER_COUNT
    assert cfg.WRITE_QUEUE_ENABLED == mem.WRITE_QUEUE_ENABLED


def dry_run_job(
    session_name: str, timeout: float = 30.0, started_job: dict | None = None
) -> dict:
    system = system_module()
    started = started_job or asyncio.run(
        system.runtime_compaction_dry_run(
            system.CompactionDryRunRequest(session_name=session_name)
        )
    )
    deadline = time.monotonic() + timeout
    job = started
    while job["status"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.05)
        job = asyncio.run(system.runtime_compaction_dry_run_status(started["job_id"]))
    return job


def test_a_dry_run_returns_before_the_scan_is_allowed_to_finish(monkeypatch):
    """Gate the scan so a synchronous implementation cannot pass this by finishing fast."""
    system = system_module()
    compaction = _mod("marm_mcp_server.core.compaction")
    release = threading.Event()
    entered = threading.Event()

    def blocked_scan(*args, **kwargs):
        entered.set()
        if not release.wait(timeout=10):
            raise AssertionError("scan was never released")
        return {"candidates": [], "report_path": None}

    monkeypatch.setattr(compaction, "run_compaction_dry_run", blocked_scan)

    started = asyncio.run(
        system.runtime_compaction_dry_run(
            system.CompactionDryRunRequest(session_name="gated")
        )
    )
    try:
        assert entered.wait(timeout=5), "the scan never started on its own thread"
        # The scan is still blocked here, so a synchronous handler could not have returned.
        assert started["status"] in {"queued", "running"}
        assert started["finished_at"] is None
        mid_flight = asyncio.run(
            system.runtime_compaction_dry_run_status(started["job_id"])
        )
        assert mid_flight["status"] in {"queued", "running"}
    finally:
        release.set()

    assert dry_run_job("gated", started_job=started)["status"] == "success"


def test_a_dry_run_reports_the_session_it_was_given():
    system = system_module()
    started = asyncio.run(
        system.runtime_compaction_dry_run(
            system.CompactionDryRunRequest(session_name="does-not-exist")
        )
    )

    assert started["job_id"]
    assert started["session_name"] == "does-not-exist"


def test_a_dry_run_job_reaches_a_terminal_state():
    job = dry_run_job("does-not-exist")

    assert job["status"] == "success"
    assert job["candidates"] == []
    assert job["finished_at"] is not None


def test_a_dry_run_job_never_exposes_internal_bookkeeping():
    job = dry_run_job("does-not-exist")

    assert [key for key in job if key.startswith("_")] == []


def test_polling_an_unknown_job_is_a_404():
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(system_module().runtime_compaction_dry_run_status("no-such-job"))

    assert excinfo.value.status_code == 404


def test_two_dry_runs_get_independent_jobs():
    system = system_module()
    first = asyncio.run(
        system.runtime_compaction_dry_run(
            system.CompactionDryRunRequest(session_name="alpha")
        )
    )
    second = asyncio.run(
        system.runtime_compaction_dry_run(
            system.CompactionDryRunRequest(session_name="beta")
        )
    )

    assert first["job_id"] != second["job_id"]
    assert second["session_name"] == "beta"


def test_a_saved_trusted_profile_does_not_swallow_an_explicit_rate_limit(
    restore_profile,
):
    """apply_runtime_preset lets trusted overwrite an explicit rpm, so resolve must not pair them."""
    cli = _mod("marm_mcp_server.cli")
    profile("trusted")

    resolved = cli.resolve_runtime_preset(None, 99)
    applied = cli.apply_runtime_preset(
        **cli._profile_flags(resolved[0]), rate_limit_rpm=resolved[1]
    )

    assert applied["rate_limit_rpm"] == 99
    assert applied["mode"] == "custom"


def test_a_saved_trusted_profile_still_applies_when_no_rate_limit_is_given(
    restore_profile,
):
    cli = _mod("marm_mcp_server.cli")
    profile("trusted")

    resolved = cli.resolve_runtime_preset(None, None)
    applied = cli.apply_runtime_preset(
        **cli._profile_flags(resolved[0]), rate_limit_rpm=resolved[1]
    )

    assert resolved == ("trusted", None)
    assert applied["rate_limit_rpm"] == 0


@pytest.mark.parametrize("saved", ["swarm", "swarm-max", "standard"])
def test_an_explicit_rate_limit_survives_every_other_saved_profile(
    restore_profile, saved
):
    cli = _mod("marm_mcp_server.cli")
    profile(saved)

    resolved = cli.resolve_runtime_preset(None, 99)
    applied = cli.apply_runtime_preset(
        **cli._profile_flags(resolved[0]), rate_limit_rpm=resolved[1]
    )

    assert resolved[0] == saved
    assert applied["rate_limit_rpm"] == 99


def test_an_explicit_trusted_flag_keeps_its_existing_cli_meaning(restore_profile):
    """Typing both --profile trusted and --rate-limit-rpm is contradictory; trusted still wins."""
    cli = _mod("marm_mcp_server.cli")

    assert cli.resolve_runtime_preset("trusted", 99) == ("trusted", 99)


def test_console_custom_rpm_is_not_swallowed_by_a_trusted_profile(restore_profile):
    """The Console posts the active profile alongside the typed rpm; trusted would zero it."""
    profile("trusted")

    result = profile("trusted", 99)

    assert result["requested_profile"] == "trusted"
    assert result["profile"] == "standard"
    assert result["rate_limit"]["requests_per_minute"] == 99
    assert result["rate_limit"]["enforced"] is True


def test_the_reconciled_profile_is_what_gets_persisted(restore_profile):
    """Persisting ('trusted', 99) would reapply the discard on the next start."""
    flags = _mod("marm_mcp_server.core.runtime_flags")

    profile("trusted", 99)

    assert flags.saved_runtime_preset() == ("standard", 99)


def test_polling_an_unknown_reload_job_is_a_404():
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(system_module().runtime_reload_docs_status("no-such-job"))

    assert excinfo.value.status_code == 404
