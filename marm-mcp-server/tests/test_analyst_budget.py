import time

from marm_mcp_server.services.analyst.budget import Budget


def test_env_defaults(monkeypatch):
    for k in ("MARM_ANALYST_TIME_BUDGET", "MARM_ANALYST_FOLLOW_UPS"):
        monkeypatch.delenv(k, raising=False)
    b = Budget.from_env()
    assert (b.time_s, b.follow_ups) == (90.0, 0)


def test_env_is_clamped(monkeypatch):
    monkeypatch.setenv("MARM_ANALYST_TIME_BUDGET", "100000")
    monkeypatch.setenv("MARM_ANALYST_FOLLOW_UPS", "9")
    b = Budget.from_env()
    assert b.time_s == 600.0 and b.follow_ups == 2


def test_caller_can_lower_but_not_raise_follow_ups(monkeypatch):
    monkeypatch.setenv("MARM_ANALYST_FOLLOW_UPS", "1")
    assert Budget.from_env(follow_ups=0).follow_ups == 0
    assert Budget.from_env(follow_ups=2).follow_ups == 1


def test_context_budget_comes_from_the_caller():
    assert Budget.from_env(context_chars=4000).context_chars == 4000


def test_run_reports_cancel_and_deadline():
    run = Budget(time_s=5).start()
    assert run.stop_reason() is None
    run.cancel.set()
    assert run.stop_reason() == "cancelled"
    run2 = Budget(time_s=0.01).start()
    time.sleep(0.02)
    assert run2.expired() and run2.stop_reason() == "deadline"
