"""Concept indexing worker contention benchmark.

The one thing the test suite cannot answer. conftest forces the encoder off for
isolation, so nothing in `pytest` exercises what this feature's own spec calls
its main performance risk: `_try_embed` reaches into `memory._encoder_lock`,
which is serialized process-wide and shared with every recall and every write.
Before v2.36.0 nothing held that lock on a loop. Now a background worker does.

Measures, against the REAL MARMMemory and the configured fastembed encoder,
store and recall latency twice:

  1. baseline    -- worker stopped, nothing competing for the encoder
  2. contended   -- worker actively draining a backlog the whole time

The gap between them is the number to judge. A worker that doubles recall
latency is not shippable on defaults; a few percent is noise.

Run from repo root:
    python scripts/benchmarking/performance/bench_concept_worker.py
    python scripts/benchmarking/performance/bench_concept_worker.py --from-live

Uses a throwaway temp DB. `--from-live` COPIES ~/.marm/marm_memory.db into it
and never writes to the original, so the numbers come from a real corpus
without touching it.
"""

import argparse
import asyncio
import os
import shutil
import statistics
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="marm_bench_worker_")
os.environ["MARM_DB_PATH"] = os.path.join(_TMP, "bench.db")
os.environ["MARM_ANALYTICS_DB_PATH"] = os.path.join(_TMP, "analytics.db")
os.environ["MARM_CONCEPT_DB_PATH"] = os.path.join(_TMP, "bench_index.db")
os.environ["SERVER_HOST"] = "127.0.0.1"
os.environ["WRITE_QUEUE_ENABLED"] = "0"
# Off unless asked for. Every extracted entity otherwise costs a ~300ms
# round trip to the code-graph subprocess, which swamps the encoder-lock
# contention this benchmark exists to isolate and says more about that
# child process than about the worker. --with-code-graph re-enables it.
if "--with-code-graph" not in sys.argv:
    os.environ["GRAPH_ENABLED"] = "false"

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, os.path.join(_REPO_ROOT, "marm-mcp-server"))


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-live",
        action="store_true",
        help="copy ~/.marm/marm_memory.db and measure against the real corpus",
    )
    parser.add_argument("--seed", type=int, default=600, help="synthetic corpus size")
    parser.add_argument("--iters", type=int, default=40, help="timed samples per phase")
    parser.add_argument(
        "--with-code-graph",
        action="store_true",
        help="leave the code-graph engine on (adds subprocess cost per entity)",
    )
    parser.add_argument(
        "--sweep",
        type=str,
        default="",
        help=(
            "compare inter-batch pauses instead of the two-phase run, "
            "e.g. --sweep 0,250,500 (milliseconds)"
        ),
    )
    return parser.parse_args()


ARGS = _parse_args()

if ARGS.from_live:
    _live = Path.home() / ".marm" / "marm_memory.db"
    if not _live.exists():
        print(f"No live database at {_live}", file=sys.stderr)
        raise SystemExit(1)
    # Copy before importing anything that opens the path, and take the WAL
    # sidecars too: without them a recently written corpus loses its newest
    # rows and the benchmark silently runs on less data than the user has.
    shutil.copy2(_live, os.environ["MARM_DB_PATH"])
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(_live) + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, os.environ["MARM_DB_PATH"] + suffix)
    print(f"Copied live corpus from {_live}\n")

from marm_mcp_server.config.settings import (  # noqa: E402
    CONCEPT_INDEX_BATCH_SIZE,
    CONCEPTS_AVAILABLE,
)
from marm_mcp_server.core import concept_queue, consolidation  # noqa: E402
from marm_mcp_server.core.concept_worker import ConceptIndexWorker  # noqa: E402
from marm_mcp_server.core.memory import MARMMemory  # noqa: E402

RECALL_LIMIT = 5

QUERIES = [
    "how does the write queue work",
    "what did we decide about compaction",
    "sqlite connection pool",
    "embedding model dimensions",
    "concept graph rebuild",
]

VOCAB = (
    "deploy rollback latency embedding session compaction queue sqlite vector "
    "rate limit semantic merge consolidation worker token bloat refactor schema "
    "websocket transport docker registry pipeline migration encoder cosine recall"
).split()


def _pct(values, p):
    s = sorted(values)
    k = max(0, min(len(s) - 1, round((p / 100) * (len(s) - 1))))
    return s[k]


def _stat(label, samples_ms):
    return (
        f"{label:<26} "
        f"med={statistics.median(samples_ms):7.1f}  "
        f"p95={_pct(samples_ms, 95):7.1f}  "
        f"max={max(samples_ms):7.1f}  (ms)"
    )


def _make_text(i):
    import random

    rnd = random.Random(i)
    return f"benchmark memory {i}: " + " ".join(
        rnd.choice(VOCAB) for _ in range(rnd.randint(10, 30))
    )


def seed_synthetic(mem, n):
    """Insert n rows with real embeddings, bypassing the write path for speed."""
    mem._load_encoder_lazily()
    texts = [_make_text(i) for i in range(n)]
    embeddings = mem.encoder.encode(texts)
    timestamp = datetime.now(timezone.utc).isoformat()
    with mem.get_connection() as conn:
        for text, vector in zip(texts, embeddings):
            conn.execute(
                "INSERT INTO memories (id, session_name, content, embedding, "
                "content_hash, timestamp, context_type, metadata) "
                "VALUES (?, 'bench', ?, ?, ?, ?, 'general', '{}')",
                (
                    str(uuid.uuid4()),
                    text,
                    vector.astype("float32").tobytes(),
                    consolidation.compute_content_hash(text),
                    timestamp,
                ),
            )


def queue_everything(mem) -> int:
    """Recreate the post-upgrade state: every memory waiting to be indexed.

    This is the worst realistic case and the one every user hits once, so it
    is what the worker should be measured under rather than a trickle.
    """
    with mem.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, COALESCE(content_hash, id) FROM memories "
            "WHERE content IS NOT NULL AND content != ''"
        ).fetchall()
        for memory_id, content_hash in rows:
            concept_queue.enqueue(conn, memory_id, content_hash)
    return len(rows)


async def measure_writes(mem, iters):
    samples = []
    for i in range(iters):
        text = f"latency probe {uuid.uuid4()}: " + _make_text(10_000 + i)
        start = time.perf_counter()
        await mem.store_memory(text, "bench-probe")
        samples.append((time.perf_counter() - start) * 1000)
    return samples


async def measure_recalls(mem, iters):
    samples = []
    for i in range(iters):
        query = QUERIES[i % len(QUERIES)]
        start = time.perf_counter()
        await mem.recall_similar(query, limit=RECALL_LIMIT)
        samples.append((time.perf_counter() - start) * 1000)
    return samples


def _delta(baseline, contended):
    base = statistics.median(baseline)
    cont = statistics.median(contended)
    if base <= 0:
        return "n/a"
    return f"{((cont - base) / base) * 100:+.1f}%"


def reset_graph(concepts_module):
    """Drop the concept database between sweep points.

    Without this, entity dedup makes every run after the first cheaper than
    the one before it, and the pause would take credit for work the previous
    run already did.
    """
    if concepts_module._concept_db is not None:
        concepts_module._concept_db.close()
        concepts_module._concept_db = None
    base = Path(os.environ["MARM_CONCEPT_DB_PATH"])
    for path in (base, Path(str(base) + "-wal"), Path(str(base) + "-shm")):
        if path.exists():
            path.unlink()


async def drain_with_pause(mem, pause_ms, worker_module, concepts_module):
    """Time a full backlog drain while sampling recall throughout."""
    reset_graph(concepts_module)
    with mem.get_connection() as conn:
        conn.execute("DELETE FROM concept_index_queue")
    queued = queue_everything(mem)

    worker_module.CONCEPT_INDEX_BATCH_PAUSE_MS = pause_ms
    worker_module.CONCEPT_INDEX_DEBOUNCE_SECONDS = 0.01
    worker = worker_module.ConceptIndexWorker()

    samples = []
    started = time.perf_counter()
    worker.start()
    while True:
        query = QUERIES[len(samples) % len(QUERIES)]
        probe = time.perf_counter()
        await mem.recall_similar(query, limit=RECALL_LIMIT)
        samples.append((time.perf_counter() - probe) * 1000)
        if concept_queue.counts()["pending"] == 0:
            break
        if time.perf_counter() - started > 900:
            print("  timed out after 15 minutes", file=sys.stderr)
            break
    elapsed = time.perf_counter() - started
    await worker.stop()
    return queued, elapsed, samples


async def run_sweep(mem, pauses):
    import marm_mcp_server.core.concept_worker as worker_module
    from marm_mcp_server.endpoints import concepts as concepts_module

    # spaCy loads its model on the first extraction, which costs seconds. Left
    # to the sweep, that lands entirely on whichever pause runs first and can
    # make a throttled run look faster than an unthrottled one.
    print("warming up the extractor...")
    concepts_module.extract_entities("warmup sentence about the write queue")

    print("Idle recall baseline (no worker running)")
    idle = await measure_recalls(mem, ARGS.iters)
    print("  " + _stat("recall_similar", idle) + "\n")

    rows = []
    for pause_ms in pauses:
        print(f"draining with a {pause_ms}ms pause between batches...")
        queued, elapsed, samples = await drain_with_pause(
            mem, pause_ms, worker_module, concepts_module
        )
        rows.append((pause_ms, queued, elapsed, samples))
        print(
            f"  {queued} memories in {elapsed:6.1f}s   "
            + _stat("recall during drain", samples)
        )

    print("\n--- pause sweep --------------------------------------------------")
    print(
        f"{'pause':>7}  {'drain':>8}  {'rate':>10}  "
        f"{'recall med':>11}  {'recall p95':>11}  {'p95 vs idle':>12}"
    )
    idle_p95 = _pct(idle, 95)
    for pause_ms, queued, elapsed, samples in rows:
        print(
            f"{pause_ms:>5}ms  {elapsed:>7.1f}s  "
            f"{queued / elapsed:>7.1f}/s  "
            f"{statistics.median(samples):>9.1f}ms  "
            f"{_pct(samples, 95):>9.1f}ms  "
            f"{((_pct(samples, 95) - idle_p95) / idle_p95) * 100:>+11.1f}%"
        )
    print(
        f"\nidle recall p95 was {idle_p95:.1f}ms. The pause buys interactive\n"
        "latency and costs drain duration; pick the point where p95 stops\n"
        "improving faster than the drain slows down."
    )


async def main():
    if not CONCEPTS_AVAILABLE:
        print(
            "Concept extraction is unavailable in this environment, so there is\n"
            "no worker to contend with and this benchmark would measure nothing.\n"
            "Run: python -m pip install -U --force-reinstall marm-mcp-server",
            file=sys.stderr,
        )
        raise SystemExit(1)

    mem = MARMMemory()
    if not mem._load_encoder_lazily():
        print(
            "The semantic encoder could not load. The encoder lock is exactly\n"
            "what this benchmark measures contention on, so there is nothing\n"
            "to report without it.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not ARGS.from_live:
        seed_synthetic(mem, ARGS.seed)

    with mem.get_connection() as conn:
        corpus = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    print(f"corpus: {corpus} memories   temp dir: {_TMP}")
    print(f"batch size: {CONCEPT_INDEX_BATCH_SIZE}   iters per phase: {ARGS.iters}\n")

    if ARGS.sweep:
        pauses = [int(value) for value in ARGS.sweep.split(",") if value.strip()]
        await run_sweep(mem, pauses)
        return

    print("--- baseline: worker stopped -------------------------------------")
    base_writes = await measure_writes(mem, ARGS.iters)
    base_recalls = await measure_recalls(mem, ARGS.iters)
    print(_stat("store_memory", base_writes))
    print(_stat("recall_similar", base_recalls))

    queued = queue_everything(mem)
    worker = ConceptIndexWorker()
    import marm_mcp_server.core.concept_worker as worker_module

    # Start draining immediately: the debounce is a real-usage nicety and only
    # delays the contention this run exists to observe.
    worker_module.CONCEPT_INDEX_DEBOUNCE_SECONDS = 0.01
    worker.start()

    # Do not start timing until the worker is genuinely busy, or the first
    # samples measure an idle process and flatter the result.
    for _ in range(300):
        await asyncio.sleep(0.1)
        if concept_queue.counts()["pending"] < queued:
            break

    print(f"\n--- contended: worker draining {queued} queued memories ----------")
    cont_writes = await measure_writes(mem, ARGS.iters)
    cont_recalls = await measure_recalls(mem, ARGS.iters)
    remaining = concept_queue.counts()

    await worker.stop()

    print(_stat("store_memory", cont_writes))
    print(_stat("recall_similar", cont_recalls))

    still_working = remaining["pending"] > 0
    print(
        f"\nqueue still had {remaining['pending']} pending at the end"
        f" ({'worker was busy throughout' if still_working else 'WORKER FINISHED EARLY'})"
    )
    if not still_working:
        print(
            "  Re-run with a larger --seed: the worker drained the backlog before\n"
            "  the timed phase ended, so part of it measured an idle process."
        )

    print("\n--- median deltas under load -------------------------------------")
    print(f"{'store_memory':<26} {_delta(base_writes, cont_writes)}")
    print(f"{'recall_similar':<26} {_delta(base_recalls, cont_recalls)}")
    print(
        "\nRestored settings are not written anywhere; this process used a\n"
        f"throwaway database at {_TMP} and never touched ~/.marm."
    )


if __name__ == "__main__":
    asyncio.run(main())
