"""Regression test for _maybe_embedding's encoder lock (marm_dashboard/db.py).

Dashboard routes are sync `def` handlers (marm_dashboard/server.py), which
FastAPI runs on its thread pool -- concurrent requests can genuinely execute
_maybe_embedding on separate threads at the same time, not just interleaved
via asyncio. Before _ENCODER_LOCK existed, two concurrent calls could both
see _ENCODER is None and race to construct it independently. Found by
CodeRabbit review on the fastembed-backend PR; core/memory.py already had
the equivalent _encoder_lock for its own encoder, this brings db.py in line.
"""

import importlib
import sys
import threading


def _fresh_db_module():
    for name in list(sys.modules):
        if name == "marm_dashboard" or name.startswith("marm_dashboard."):
            del sys.modules[name]
    return importlib.import_module("marm_dashboard.db")


class _SlowFakeTextEmbedding:
    """Stands in for fastembed.TextEmbedding: construction blocks until
    released, so a second concurrent caller is forced to either wait on the
    lock (correct) or race past it and construct a second instance (bug)."""

    instances_created = 0
    entered = threading.Event()
    release = threading.Event()
    timed_out_waiting_for_release = False

    def __init__(self, model_name):
        type(self).instances_created += 1
        self.model_name = model_name
        type(self).entered.set()
        if not type(self).release.wait(timeout=5):
            # Don't assert here: this runs inside _maybe_embedding's try block,
            # so an AssertionError would be swallowed by its blanket
            # `except Exception`, surfacing only as a confusing `None` result
            # instead of the real "deadlocked" diagnostic. Record it and let
            # the test body assert after joining both threads instead.
            type(self).timed_out_waiting_for_release = True

    def embed(self, texts):
        for _ in texts:
            yield __import__("numpy").zeros(3, dtype="float32")


def test_concurrent_embedding_calls_do_not_race_on_encoder_init(monkeypatch):
    db = _fresh_db_module()
    _SlowFakeTextEmbedding.instances_created = 0
    _SlowFakeTextEmbedding.entered = threading.Event()
    _SlowFakeTextEmbedding.release = threading.Event()
    _SlowFakeTextEmbedding.timed_out_waiting_for_release = False

    import fastembed

    monkeypatch.setattr(fastembed, "TextEmbedding", _SlowFakeTextEmbedding)
    db._ENCODER = None
    db._ENCODER_FAILED = False

    results = []

    def _caller():
        results.append(db._maybe_embedding("some dashboard text"))

    first = threading.Thread(target=_caller)
    first.start()
    assert _SlowFakeTextEmbedding.entered.wait(timeout=5), (
        "first caller never reached encoder construction"
    )

    second = threading.Thread(target=_caller)
    second.start()

    # The second caller must block on _ENCODER_LOCK, not race past it and
    # start constructing its own TextEmbedding instance concurrently.
    second.join(timeout=0.2)
    assert second.is_alive(), "second caller proceeded before the lock released"

    _SlowFakeTextEmbedding.release.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not _SlowFakeTextEmbedding.timed_out_waiting_for_release, (
        "test deadlocked waiting for release"
    )
    assert _SlowFakeTextEmbedding.instances_created == 1
    assert len(results) == 2
    assert all(r is not None for r in results)
