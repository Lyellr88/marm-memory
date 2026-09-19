"""The indexed-project cache, and the reasons it is a cache and not a memo."""

from __future__ import annotations

import pytest

from marm_mcp_server.services.code_context import backend as B


@pytest.fixture(autouse=True)
def _clear():
    B.invalidate_projects_cache()
    yield
    B.invalidate_projects_cache()


class _Counter:
    """A LocalBackend whose graph round trip is counted, not performed."""

    def __init__(self, payload, fail_first=False):
        self.calls = 0
        self.payload = payload
        self.fail_first = fail_first

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            return {"status": "error", "message": "graph backend unavailable"}
        return self.payload


def _patched(monkeypatch, counter):
    """Stand in for `R.do_index` without a graph subprocess."""
    import marm_graph.core.tool_router as R

    monkeypatch.setattr(R, "do_index", counter)
    monkeypatch.setattr(B.LocalBackend, "_client", lambda self: object())
    return B.LocalBackend()


def test_the_list_is_fetched_once_within_the_ttl(monkeypatch):
    """Profiled at 117 ms of a 595 ms composition -- 20% -- to re-fetch a list
    that changes only when a repository is indexed or deleted."""
    counter = _Counter({"projects": [{"name": "a"}]})
    backend = _patched(monkeypatch, counter)

    assert backend.projects() == [{"name": "a"}]
    assert backend.projects() == [{"name": "a"}]
    assert backend.projects() == [{"name": "a"}]
    assert counter.calls == 1


def test_invalidation_makes_an_index_visible_immediately(monkeypatch):
    counter = _Counter({"projects": [{"name": "a"}]})
    backend = _patched(monkeypatch, counter)

    backend.projects()
    B.invalidate_projects_cache()
    backend.projects()
    assert counter.calls == 2


def test_the_ttl_bounds_staleness_without_invalidation(monkeypatch):
    """The list also changes from paths that never call invalidate -- the
    auto-index poller, a second client, the CLI -- so the TTL is the floor."""
    counter = _Counter({"projects": [{"name": "a"}]})
    backend = _patched(monkeypatch, counter)
    monkeypatch.setattr(B, "_PROJECTS_TTL", 0.0)

    backend.projects()
    backend.projects()
    assert counter.calls == 2


def test_a_failure_is_never_cached(monkeypatch):
    """An empty or failed answer from a graph that is merely slow to start
    would otherwise be served as fact for the whole TTL, and "no indexed
    project" sends a caller off to index a repository they already indexed."""
    counter = _Counter({"projects": [{"name": "a"}]}, fail_first=True)
    backend = _patched(monkeypatch, counter)

    with pytest.raises(B.GraphUnavailable):
        backend.projects()
    assert backend.projects() == [{"name": "a"}]
    assert counter.calls == 2


def test_a_caller_cannot_mutate_the_cached_list(monkeypatch):
    counter = _Counter({"projects": [{"name": "a"}]})
    backend = _patched(monkeypatch, counter)

    got = backend.projects()
    got.append({"name": "injected"})
    assert backend.projects() == [{"name": "a"}]
