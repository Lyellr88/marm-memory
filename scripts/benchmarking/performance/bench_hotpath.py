"""Hot-path benchmark.

Measures, against the REAL MARMMemory + configured fastembed-backed semantic encoder:
  1. encode() wall time (the per-call CPU cost)
  2. recall_similar latency vs session size N (FTS filter + bounded embedding rerank)
  3. event-loop blocking: concurrent recalls via asyncio.gather vs serial sum
  4. write latency with consolidation OFF vs ON (double-encode + scan-per-write)
  5. RECALL SCALING: production full semantic scan vs production hybrid recall

Every timed path calls the shipped MARMMemory code (recall_similar,
_fetch_and_score_embedding_rows). No scoring is reimplemented in this script,
so the numbers reflect what a caller actually gets.

Run from repo root:  python scripts/benchmarking/performance/bench_hotpath.py
Uses a throwaway temp DB; never touches ~/.marm.
"""

import asyncio
import importlib.util
import os
import sqlite3
import statistics
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone

_TMP = tempfile.mkdtemp(prefix="marm_bench_")
os.environ["MARM_DB_PATH"] = os.path.join(_TMP, "bench.db")
os.environ["MARM_ANALYTICS_DB_PATH"] = os.path.join(_TMP, "analytics.db")
os.environ["SERVER_HOST"] = "127.0.0.1"
os.environ["WRITE_QUEUE_ENABLED"] = "0"

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, os.path.join(_REPO_ROOT, "marm-mcp-server"))

from marm_mcp_server.core.memory import MARMMemory, _wide_fts_query  # noqa: E402
from marm_mcp_server.core import consolidation  # noqa: E402
from marm_mcp_server.core import memory_ops  # noqa: E402
from marm_mcp_server.config.settings import (  # noqa: E402
    DEFAULT_SEMANTIC_DIM,
    FTS_CANDIDATE_LIMIT,
)

NUMPY_AVAILABLE = importlib.util.find_spec("numpy") is not None


def _pct(values, p):
    s = sorted(values)
    k = max(0, min(len(s) - 1, round((p / 100) * (len(s) - 1))))
    return s[k]


def _stat_line(label, samples_ms):
    return (
        f"{label:<28} "
        f"min={min(samples_ms):7.1f}  "
        f"med={statistics.median(samples_ms):7.1f}  "
        f"p95={_pct(samples_ms, 95):7.1f}  "
        f"max={max(samples_ms):7.1f}  (ms)"
    )


VOCAB = (
    "deploy rollback latency embedding session compaction queue sqlite vector "
    "rate limit semantic merge consolidation worker token bloat refactor schema "
    "websocket transport docker registry pipeline migration encoder cosine recall "
    "summary cluster threshold nudge staging idempotent transaction lock writer"
).split()

EMBEDDING_DIM = DEFAULT_SEMANTIC_DIM
EMBEDDING_BYTES = EMBEDDING_DIM * 4


def _make_text(i):
    import random

    rnd = random.Random(i)
    n = rnd.randint(8, 30)
    return f"memory {i}: " + " ".join(rnd.choice(VOCAB) for _ in range(n))


def reset_benchmark_rows(mem: MARMMemory) -> None:
    """Clear benchmark rows explicitly so each phase starts from a clean DB."""
    with mem.get_connection() as conn:
        conn.execute("DELETE FROM memory_chunks")
        conn.execute("DELETE FROM memories")
        conn.execute("DELETE FROM sessions WHERE session_name = 'bench'")


def assert_embedding_dimensions(mem: MARMMemory) -> None:
    """Fail fast if benchmark setup produced vectors with the wrong dimension."""
    with mem.get_connection() as conn:
        bad_memories = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL AND length(embedding) != ?",
            (EMBEDDING_BYTES,),
        ).fetchone()[0]
        bad_chunks = conn.execute(
            "SELECT COUNT(*) FROM memory_chunks WHERE embedding IS NOT NULL AND length(embedding) != ?",
            (EMBEDDING_BYTES,),
        ).fetchone()[0]

    if bad_memories or bad_chunks:
        raise RuntimeError(
            "benchmark produced wrong-dimension embeddings "
            f"(memories={bad_memories}, chunks={bad_chunks}, expected_bytes={EMBEDDING_BYTES})"
        )


def seed(mem: MARMMemory, n: int):
    """Insert n rows with REAL embeddings, bypassing dedup for speed."""
    mem._load_encoder_lazily()
    texts = [_make_text(i) for i in range(n)]
    embs = mem.encoder.encode(texts)
    ts = datetime.now(timezone.utc).isoformat()
    reset_benchmark_rows(mem)
    with mem.get_connection() as conn:
        for _i, (t, e) in enumerate(zip(texts, embs)):
            conn.execute(
                "INSERT INTO memories (id, session_name, content, embedding, "
                "content_hash, timestamp, context_type, metadata) "
                "VALUES (?, 'bench', ?, ?, ?, ?, 'general', '{}')",
                (
                    str(uuid.uuid4()),
                    t,
                    e.astype("float32").tobytes(),
                    consolidation.compute_content_hash(t),
                    ts,
                ),
            )
    assert_embedding_dimensions(mem)


async def bench_encode(mem, iters=30):
    mem._load_encoder_lazily()
    q = "deploy rollback latency embedding session compaction queue sqlite"
    samples = []
    for _ in range(iters):
        t0 = time.perf_counter()
        mem.encoder.encode(q)
        samples.append((time.perf_counter() - t0) * 1000)
    return samples


async def bench_recall_vs_n(mem, sizes, iters=15):
    results = {}
    for n in sizes:
        seed(mem, n)
        samples = []
        for k in range(iters):
            t0 = time.perf_counter()
            q = f"{VOCAB[k % len(VOCAB)]} {VOCAB[(k + 1) % len(VOCAB)]}"
            await mem.recall_similar(q, session="bench", limit=5)
            samples.append((time.perf_counter() - t0) * 1000)
        results[n] = samples
    return results


async def bench_concurrency(mem, n=1000, concurrency=10):
    """If encode/recall block the loop, gather time ~= serial sum (no parallelism)."""
    seed(mem, n)
    queries = [f"semantic merge worker {i}" for i in range(concurrency)]

    t0 = time.perf_counter()
    for q in queries:
        await mem.recall_similar(q, session="bench", limit=5)
    serial_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    await asyncio.gather(
        *(mem.recall_similar(q, session="bench", limit=5) for q in queries)
    )
    gather_ms = (time.perf_counter() - t0) * 1000
    return serial_ms, gather_ms


async def bench_write(mem, n=800, iters=15):
    """Compare store_memory cost with consolidation OFF vs ON at session size n."""
    out = {}
    for flag in (False, True):
        memory_ops.CONSOLIDATION_ENABLED = flag
        seed(mem, n)
        samples = []
        for k in range(iters):
            txt = f"unique write probe {uuid.uuid4()} latency embedding worker {k}"
            t0 = time.perf_counter()
            await mem.store_memory(txt, "bench")
            samples.append((time.perf_counter() - t0) * 1000)
        out["ON" if flag else "OFF"] = samples
    memory_ops.CONSOLIDATION_ENABLED = False
    return out


async def bench_connection_overhead(db_path, iters=30):
    """Measure SQLite connection creation overhead."""
    samples = []
    for _ in range(iters):
        t0 = time.perf_counter()
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.close()
        samples.append((time.perf_counter() - t0) * 1000)
    return samples


async def bench_hybrid_strategies(mem, sizes=None, iters=15):
    """Compare two REAL production recall paths as session size N grows:

    1. Full semantic scan  -- _fetch_and_score_embedding_rows scores every
       embedding row (the cost with no keyword pre-filter).
    2. Production hybrid    -- recall_similar: FTS pre-filter to a bounded
       candidate set, then semantic + BM25 + temporal re-rank.

    Both are timed with the query vector precomputed, so encode cost (constant
    in N, reported in section 1) is excluded and the numbers isolate the
    scan-vs-prefilter scaling difference. No scoring is reimplemented here.
    """
    if sizes is None:
        sizes = [100, 500, 1000, 2000, 4000, 10000]

    if not NUMPY_AVAILABLE:
        print("  [SKIPPED: numpy not available]")
        return None

    from marm_mcp_server.core.memory_scoring import _fetch_and_score_embedding_rows

    mem._load_encoder_lazily()
    results = {
        "full_scan": {},
        "production_hybrid": {},
        "fts_hit_rate": {},
    }

    # Test queries with good keyword coverage
    test_queries = [
        "deploy latency embedding session",
        "consolidation worker semantic merge",
        "docker registry pipeline migration",
    ]

    for n in sizes:
        seed(mem, n)

        scan_samples = []
        prod_samples = []
        fts_hits = []

        for iter_num in range(iters):
            query = test_queries[iter_num % len(test_queries)]
            query_vec = mem._encode_sync(query)
            # Must match what recall_similar actually runs. These queries are all
            # non-exact, so the timed path uses the wide builder; counting strict-AND
            # matches described a query the measured path never issues.
            fts_query = _wide_fts_query(query)

            # Alternate order so one path does not always benefit from a warmed cache.
            if iter_num % 2 == 0:
                t0 = time.perf_counter()
                await asyncio.to_thread(
                    _fetch_and_score_embedding_rows,
                    mem.db_path,
                    "bench",
                    n,
                    query_vec,
                    5,
                )
                scan_samples.append((time.perf_counter() - t0) * 1000)

                t0 = time.perf_counter()
                await mem.recall_similar(
                    query, session="bench", limit=5, query_vec=query_vec
                )
                prod_samples.append((time.perf_counter() - t0) * 1000)
            else:
                t0 = time.perf_counter()
                await mem.recall_similar(
                    query, session="bench", limit=5, query_vec=query_vec
                )
                prod_samples.append((time.perf_counter() - t0) * 1000)

                t0 = time.perf_counter()
                await asyncio.to_thread(
                    _fetch_and_score_embedding_rows,
                    mem.db_path,
                    "bench",
                    n,
                    query_vec,
                    5,
                )
                scan_samples.append((time.perf_counter() - t0) * 1000)

            # Informational only: how many candidates the FTS pre-filter matched.
            if fts_query:
                with mem.get_connection() as conn:
                    matched = conn.execute(
                        """SELECT COUNT(*) FROM memories_fts
                           JOIN memories m ON memories_fts.rowid = m.rowid
                           WHERE memories_fts MATCH ? AND m.session_name = 'bench'""",
                        (fts_query,),
                    ).fetchone()[0]
                fts_hits.append(min(matched, FTS_CANDIDATE_LIMIT))

        results["full_scan"][n] = scan_samples
        results["production_hybrid"][n] = prod_samples
        results["fts_hit_rate"][n] = (sum(fts_hits) / len(fts_hits)) if fts_hits else 0

    return results


async def main():
    mem = MARMMemory()
    print("loading encoder (cold)...")
    t0 = time.perf_counter()
    mem._load_encoder_lazily()
    print(f"  cold model load: {(time.perf_counter() - t0) * 1000:.0f} ms\n")

    print("=== 1. encode() wall time (single short string) ===")
    enc = await bench_encode(mem)
    print(_stat_line("encode() warm", enc), "\n")

    print("=== 2. recall_similar latency vs session size N ===")
    rec = await bench_recall_vs_n(mem, [100, 250, 500, 1000, 2000, 4000])
    for n, s in rec.items():
        print(_stat_line(f"recall  N={n}", s))
    print()

    print("=== 3. event-loop blocking (10 concurrent recalls, N=1000) ===")
    serial, gather = await bench_concurrency(mem, n=1000, concurrency=10)
    print(f"  serial (10x sequential): {serial:8.1f} ms")
    print(f"  gather (10x concurrent): {gather:8.1f} ms")
    ratio = gather / serial if serial else 0
    verdict = "BLOCKED (no parallelism)" if ratio > 0.85 else "parallel"
    print(f"  gather/serial = {ratio:.2f}  -> {verdict}\n")

    print("=== 4. write latency: consolidation OFF vs ON (N=800) ===")
    w = await bench_write(mem, n=800)
    print(_stat_line("store_memory OFF", w["OFF"]))
    print(_stat_line("store_memory ON ", w["ON"]))
    off_med = statistics.median(w["OFF"])
    on_med = statistics.median(w["ON"])
    print(f"  consolidation penalty: {on_med / off_med:.1f}x median\n")

    print("=== 5. SQLite connection overhead (baseline) ===")
    conn_overhead = await bench_connection_overhead(mem.db_path)
    print(_stat_line("connect + close", conn_overhead), "\n")

    print("=== 6. RECALL SCALING: full semantic scan vs production hybrid ===")
    print(
        "Both paths call shipped code, timed with the query vector precomputed\n"
        "(encode is constant in N, see section 1).\n"
    )

    hybrid = await bench_hybrid_strategies(
        mem, sizes=[100, 500, 1000, 2000, 4000, 10000]
    )

    if hybrid:
        print(
            f"{'Size':<8} {'Full Scan':<14} {'Prod Hybrid':<14} {'Speedup':<10} {'FTS Hits'}"
        )
        print("-" * 60)

        for n in [100, 500, 1000, 2000, 4000, 10000]:
            scan_med = statistics.median(hybrid["full_scan"][n])
            prod_med = statistics.median(hybrid["production_hybrid"][n])
            speedup = scan_med / prod_med if prod_med > 0 else 0
            fts_hit_rate = hybrid["fts_hit_rate"][n]

            print(
                f"{n:<8} {scan_med:>7.1f}ms     {prod_med:>7.1f}ms      "
                f"{speedup:>5.1f}x     {fts_hit_rate:>4.1f}/{FTS_CANDIDATE_LIMIT}"
            )

        print("\nKey points:")
        print(
            "  • Full Scan: _fetch_and_score_embedding_rows over all N rows (no prefilter)"
        )
        print(
            "  • Prod Hybrid: recall_similar -- FTS prefilter + semantic/BM25/temporal rerank"
        )
        print("  • Speedup = full scan / production hybrid (both real code paths)")
        print(
            "  • FTS Hits: avg candidates the keyword prefilter matched "
            f"(capped at FTS_CANDIDATE_LIMIT={FTS_CANDIDATE_LIMIT})\n"
        )


if __name__ == "__main__":
    asyncio.run(main())
