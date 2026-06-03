"""Hot-path benchmark for the opus-review findings.

Measures, against the REAL MARMMemory + real all-MiniLM-L6-v2 encoder:
  1. encode() wall time (the per-call CPU cost)
  2. recall_similar latency vs session size N (O(N) brute force + 1000 cliff)
  3. event-loop blocking: concurrent recalls via asyncio.gather vs serial sum
  4. write latency with consolidation OFF vs ON (double-encode + scan-per-write)

Run from marm-mcp-server/:  python scripts/bench_hotpath.py
Uses a throwaway temp DB; never touches ~/.marm.
"""

import asyncio
import os
import statistics
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone

# Point global state at a temp DB BEFORE importing the package.
_TMP = tempfile.mkdtemp(prefix="marm_bench_")
os.environ["MARM_DB_PATH"] = os.path.join(_TMP, "bench.db")
os.environ["MARM_ANALYTICS_DB_PATH"] = os.path.join(_TMP, "analytics.db")
os.environ["SERVER_HOST"] = "127.0.0.1"
os.environ["WRITE_QUEUE_ENABLED"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from marm_mcp_server.core.memory import MARMMemory  # noqa: E402
from marm_mcp_server.core import consolidation  # noqa: E402


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


def _make_text(i):
    import random

    rnd = random.Random(i)
    n = rnd.randint(8, 30)
    return f"memory {i}: " + " ".join(rnd.choice(VOCAB) for _ in range(n))


def seed(mem: MARMMemory, n: int):
    """Insert n rows with REAL embeddings, bypassing dedup for speed."""
    mem._load_encoder_lazily()
    texts = [_make_text(i) for i in range(n)]
    embs = mem.encoder.encode(texts)  # batch encode = fast setup
    ts = datetime.now(timezone.utc).isoformat()
    with mem.get_connection() as conn:
        conn.execute("DELETE FROM memories")
        for i, (t, e) in enumerate(zip(texts, embs)):
            conn.execute(
                "INSERT INTO memories (id, session_name, content, embedding, "
                "content_hash, timestamp, context_type, metadata) "
                "VALUES (?, 'bench', ?, ?, ?, ?, 'general', '{}')",
                (str(uuid.uuid4()), t, e.astype("float32").tobytes(),
                 consolidation.compute_content_hash(t), ts),
            )


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
            await mem.recall_similar(f"latency embedding {k}", session="bench", limit=5)
            samples.append((time.perf_counter() - t0) * 1000)
        results[n] = samples
    return results


async def bench_concurrency(mem, n=1000, concurrency=10):
    """If encode/recall block the loop, gather time ~= serial sum (no parallelism)."""
    seed(mem, n)
    queries = [f"semantic merge worker {i}" for i in range(concurrency)]

    # Serial baseline
    t0 = time.perf_counter()
    for q in queries:
        await mem.recall_similar(q, session="bench", limit=5)
    serial_ms = (time.perf_counter() - t0) * 1000

    # Concurrent via gather
    t0 = time.perf_counter()
    await asyncio.gather(
        *(mem.recall_similar(q, session="bench", limit=5) for q in queries)
    )
    gather_ms = (time.perf_counter() - t0) * 1000
    return serial_ms, gather_ms


async def bench_write(mem, n=800, iters=15):
    """Compare store_memory cost with consolidation OFF vs ON at session size n."""
    import marm_mcp_server.core.memory as mm

    out = {}
    for flag in (False, True):
        mm.CONSOLIDATION_ENABLED = flag
        seed(mem, n)
        samples = []
        for k in range(iters):
            # unique content each time so Layer 1 exact-dedup never short-circuits
            txt = f"unique write probe {uuid.uuid4()} latency embedding worker {k}"
            t0 = time.perf_counter()
            await mem.store_memory(txt, "bench")
            samples.append((time.perf_counter() - t0) * 1000)
        out["ON" if flag else "OFF"] = samples
    mm.CONSOLIDATION_ENABLED = False
    return out


async def main():
    mem = MARMMemory()
    print("loading encoder (cold)...")
    t0 = time.perf_counter()
    mem._load_encoder_lazily()
    print(f"  cold model load: {(time.perf_counter()-t0)*1000:.0f} ms\n")

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
    print(f"  consolidation penalty: {on_med/off_med:.1f}x median\n")


if __name__ == "__main__":
    asyncio.run(main())
