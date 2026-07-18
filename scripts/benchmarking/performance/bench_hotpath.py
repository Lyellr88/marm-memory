"""Hot-path benchmark.

Measures, against the REAL MARMMemory + configured fastembed-backed semantic encoder:
  1. encode() wall time (the per-call CPU cost)
  2. recall_similar latency vs session size N (FTS filter + bounded embedding rerank)
  3. event-loop blocking: concurrent recalls via asyncio.gather vs serial sum
  4. write latency with consolidation OFF vs ON (double-encode + scan-per-write)
  5. HYBRID SEARCH: FTS5 filter→re-rank vs weighted fusion vs pure semantic

Run from repo root:  python scripts/benchmarking/performance/bench_hotpath.py
Uses a throwaway temp DB; never touches ~/.marm.
"""

import asyncio
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

from marm_mcp_server.core.memory import MARMMemory, _safe_fts_query  # noqa: E402
from marm_mcp_server.core import consolidation  # noqa: E402
from marm_mcp_server.core import memory_ops  # noqa: E402
from marm_mcp_server.config.settings import DEFAULT_SEMANTIC_DIM  # noqa: E402

try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


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
    """Benchmark three hybrid search strategies:
    1. Pure Semantic (baseline brute-force)
    2. Current Production (weighted fusion: vector scan + FTS merge)
    3. Filter→Re-rank (FTS top 50 → semantic re-rank only those 50)
    """
    if sizes is None:
        sizes = [100, 500, 1000, 2000, 4000, 10000]

    if not NUMPY_AVAILABLE:
        print("  [SKIPPED: numpy not available]")
        return None

    mem._load_encoder_lazily()
    results = {
        "pure_semantic": {},
        "production_hybrid": {},
        "filter_rerank": {},
        "fts_only": {},
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

        pure_samples = []
        prod_samples = []
        filter_samples = []
        fts_samples = []
        fts_hits = []

        for iter_num in range(iters):
            query = test_queries[iter_num % len(test_queries)]
            query_emb = mem.encoder.encode(query)
            fts_query = _safe_fts_query(query)

            # 1. Pure Semantic (disable FTS in production code temporarily)
            t0 = time.perf_counter()
            conn = sqlite3.connect(mem.db_path, timeout=30.0)
            try:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT id, content, embedding FROM memories
                       WHERE session_name = 'bench' AND embedding IS NOT NULL
                       ORDER BY timestamp DESC LIMIT 10000"""
                ).fetchall()

                if rows:
                    similarities = []
                    for row in rows:
                        emb_bytes = row["embedding"]
                        if emb_bytes:
                            emb = np.frombuffer(emb_bytes, dtype=np.float32)
                            if len(emb) == len(query_emb):
                                sim = float(np.dot(query_emb, emb))
                                similarities.append((row["id"], row["content"], sim))
                    similarities.sort(key=lambda x: x[2], reverse=True)
                    # Top results available in similarities[:5]
            finally:
                conn.close()
            pure_samples.append((time.perf_counter() - t0) * 1000)

            # 2. Production Hybrid (current recall_similar implementation)
            t0 = time.perf_counter()
            await mem.recall_similar(query, session="bench", limit=5)
            prod_samples.append((time.perf_counter() - t0) * 1000)

            # 3. Filter→Re-rank Strategy (dump.md approach)
            t0 = time.perf_counter()
            conn = sqlite3.connect(mem.db_path, timeout=30.0)
            try:
                conn.row_factory = sqlite3.Row

                # Step 1: FTS filter to top 50 candidates
                candidates = (
                    conn.execute(
                        """SELECT m.id, m.content, m.embedding
                       FROM memories_fts
                       JOIN memories m ON memories_fts.rowid = m.rowid
                       WHERE memories_fts MATCH ? AND m.session_name = 'bench'
                       ORDER BY bm25(memories_fts) LIMIT 50""",
                        (fts_query,),
                    ).fetchall()
                    if fts_query
                    else []
                )

                fts_hits.append(len(candidates))

                # Fallback: if FTS finds nothing, take top 50 by timestamp
                if not candidates:
                    candidates = conn.execute(
                        """SELECT id, content, embedding FROM memories
                           WHERE session_name = 'bench' AND embedding IS NOT NULL
                           ORDER BY timestamp DESC LIMIT 50"""
                    ).fetchall()

                # Step 2: Re-rank only those 50 by semantic similarity
                if candidates:
                    scores = []
                    for row in candidates:
                        emb_bytes = row["embedding"]
                        if emb_bytes:
                            emb = np.frombuffer(emb_bytes, dtype=np.float32)
                            if len(emb) == len(query_emb):
                                score = float(np.dot(query_emb, emb))
                                scores.append((row["id"], row["content"], score))

                    scores.sort(key=lambda x: x[2], reverse=True)
                    # Top results available in scores[:5]
            finally:
                conn.close()
            filter_samples.append((time.perf_counter() - t0) * 1000)

            # 4. FTS-only (baseline keyword search)
            if fts_query:
                t0 = time.perf_counter()
                conn = sqlite3.connect(mem.db_path, timeout=30.0)
                try:
                    conn.row_factory = sqlite3.Row
                    conn.execute(
                        """SELECT m.id, m.content FROM memories_fts
                           JOIN memories m ON memories_fts.rowid = m.rowid
                           WHERE memories_fts MATCH ? AND m.session_name = 'bench'
                           ORDER BY bm25(memories_fts) LIMIT 5""",
                        (fts_query,),
                    ).fetchall()
                finally:
                    conn.close()
                fts_samples.append((time.perf_counter() - t0) * 1000)

        results["pure_semantic"][n] = pure_samples
        results["production_hybrid"][n] = prod_samples
        results["filter_rerank"][n] = filter_samples
        results["fts_only"][n] = fts_samples if fts_samples else [0.0] * iters
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

    print("=== 6. HYBRID SEARCH STRATEGIES COMPARISON ===")
    print(
        "Testing: Pure Semantic | Production Hybrid (weighted fusion) | Filter→Re-rank\n"
    )

    hybrid = await bench_hybrid_strategies(
        mem, sizes=[100, 500, 1000, 2000, 4000, 10000]
    )

    if hybrid:
        print(
            f"{'Size':<8} {'Pure Sem':<12} {'Prod Hybrid':<14} {'Filter→Rerank':<16} {'FTS-Only':<12} {'Speedup':<12} {'FTS Hits'}"
        )
        print("-" * 100)

        for n in [100, 500, 1000, 2000, 4000, 10000]:
            pure_med = statistics.median(hybrid["pure_semantic"][n])
            prod_med = statistics.median(hybrid["production_hybrid"][n])
            filt_med = statistics.median(hybrid["filter_rerank"][n])
            fts_med = (
                statistics.median(hybrid["fts_only"][n])
                if hybrid["fts_only"][n][0] > 0
                else 0
            )

            # Speedup: filter→re-rank vs pure semantic
            speedup = pure_med / filt_med if filt_med > 0 else 0
            fts_hit_rate = hybrid["fts_hit_rate"][n]

            print(
                f"{n:<8} {pure_med:>7.1f}ms     {prod_med:>7.1f}ms       "
                f"{filt_med:>7.1f}ms         {fts_med:>7.1f}ms      "
                f"{speedup:>5.1f}x        {fts_hit_rate:>4.1f}/50"
            )

        print("\n📊 Key Insights:")
        print("  • Pure Semantic: O(N) brute-force vector scan (baseline)")
        print("  • Prod Hybrid: Weighted fusion (65% vector + 35% FTS scores)")
        print(
            "  • Filter→Re-rank: FTS narrows to 50 → semantic re-rank (dump.md strategy)"
        )
        print("  • Speedup shows Filter→Re-rank advantage over Pure Semantic")
        print("  • FTS Hits shows avg candidates found by keyword filter\n")


if __name__ == "__main__":
    asyncio.run(main())
