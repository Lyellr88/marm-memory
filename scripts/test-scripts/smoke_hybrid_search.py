#!/usr/bin/env python
"""
Hybrid search smoke harness — seeds deterministic memories and prints
vector / FTS / combined scores per query for weight tuning.

Usage:
    python scripts/test-scripts/smoke_hybrid_search.py
    python scripts/test-scripts/smoke_hybrid_search.py --fts-weight 0.4
"""

import argparse
import atexit
import asyncio
import os
import sys
import tempfile
from pathlib import Path

# UTF-8 output on Windows (cp1252 cannot encode box-drawing characters)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

SERVER_ROOT = Path(__file__).resolve().parents[2] / "marm-mcp-server"
sys.path.insert(0, str(SERVER_ROOT))

_BOOT_FD, _BOOT_DB_PATH = tempfile.mkstemp(suffix=".db", prefix="smoke_hybrid_boot_")
os.close(_BOOT_FD)
os.environ.setdefault("MARM_DB_PATH", _BOOT_DB_PATH)

from marm_mcp_server.config.settings import RECALL_SCAN_LIMIT, SEMANTIC_SEARCH_AVAILABLE  # noqa: E402
from marm_mcp_server.core import memory as memory_module  # noqa: E402
from marm_mcp_server.core.memory import (  # noqa: E402
    MARMMemory,
    _fetch_and_score_embedding_rows,
    _fetch_and_score_fts_rows,
    _safe_fts_query,
)


def _cleanup_boot_db() -> None:
    try:
        memory_module.memory.connection_pool.close_all()
    except Exception:
        pass
    try:
        os.unlink(_BOOT_DB_PATH)
    except Exception:
        pass


atexit.register(_cleanup_boot_db)

SEED_MEMORIES = [
    "COMPACTION_TRIGGER_COUNT = 20 controls write-threshold before scan",
    "docker run -p 8001:8001 lyellr88/marm-mcp-server:latest --swarm",
    "Set up persistent memory so agents remember previous sessions",
    "Deployed MARM HTTP server on Ubuntu VPS using Docker Compose with port 8001",
    "The weather was nice today",
]

TEST_QUERIES = [
    ("COMPACTION_TRIGGER_COUNT", "exact config key — FTS should dominate"),
    ("docker deployment command", "mixed — both lanes contribute"),
    ("persistent agent memory", "semantic only — vector should dominate"),
    ("marm server setup", "mixed retrieval"),
]

SESSION = "smoke-hybrid-test"
COL_WIDTH = 70


def _close_pool(memory: MARMMemory) -> None:
    """Drain and close all pooled SQLite connections so the DB file can be deleted."""
    pool = memory.connection_pool
    while True:
        try:
            conn = pool.pool.get_nowait()
            conn.close()
        except Exception:
            break


async def run(fts_weight: float) -> bool:
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="smoke_hybrid_")
    os.close(fd)
    memory: MARMMemory | None = None
    try:
        memory = MARMMemory(db_path)

        encoder_ok = SEMANTIC_SEARCH_AVAILABLE and memory._load_encoder_lazily()
        if not encoder_ok:
            memory._encoder_failed = True
            print(
                "NOTE: sentence-transformers not available — vector scores will be 0.00\n"
            )

        for content in SEED_MEMORIES:
            await memory.store_memory(content, session=SESSION)

        with memory.get_connection() as conn:
            content_map: dict[str, str] = {
                row[0]: row[1]
                for row in conn.execute(
                    "SELECT id, content FROM memories WHERE session_name = ?",
                    (SESSION,),
                ).fetchall()
            }

        print(f"Weight: FTS={fts_weight:.2f}  Vector={1 - fts_weight:.2f}\n")

        checks: list[tuple[str, bool]] = []

        for query, label in TEST_QUERIES:
            print(f'QUERY: "{query}"  [{label}]')
            print("─" * COL_WIDTH)
            print(f"{'Rank':>4}  {'Vec':>5}  {'FTS':>5}  {'Combined':>8}  Content")
            print("─" * COL_WIDTH)

            # Vector lane
            vec_scores: dict[str, float] = {}
            if encoder_ok:
                try:
                    query_embedding = await asyncio.to_thread(
                        memory._encode_sync, query
                    )
                    sims, _, _ = await asyncio.to_thread(
                        _fetch_and_score_embedding_rows,
                        db_path,
                        SESSION,
                        RECALL_SCAN_LIMIT,
                        query_embedding,
                        len(SEED_MEMORIES),
                    )
                    for row, score in sims:
                        vec_scores[row["id"]] = score
                except Exception as e:
                    print(f"  Vector lane error: {e}")

            # FTS lane
            fts_scores: dict[str, float] = {}
            fts_query = _safe_fts_query(query)
            if fts_query:
                try:
                    for row, score in await asyncio.to_thread(
                        _fetch_and_score_fts_rows,
                        db_path,
                        SESSION,
                        fts_query,
                        len(SEED_MEMORIES),
                    ):
                        fts_scores[row["id"]] = score
                except Exception as e:
                    print(f"  FTS lane error: {e}")

            # Merge all memories — zeros for non-matching rows (noise check)
            rows: list[tuple[float, float, float, str]] = []
            for mem_id, content in content_map.items():
                v = vec_scores.get(mem_id, 0.0)
                f = fts_scores.get(mem_id, 0.0)
                c = (1 - fts_weight) * v + fts_weight * f
                rows.append((v, f, c, content))

            rows.sort(key=lambda x: x[2], reverse=True)

            for rank, (v, f, c, content) in enumerate(rows, 1):
                snippet = (content[:57] + "...") if len(content) > 60 else content
                print(f"{rank:>4}  {v:>5.2f}  {f:>5.2f}  {c:>8.4f}  {snippet}")

            # Smoke check: exact config key must rank first
            if query == "COMPACTION_TRIGGER_COUNT":
                top_content = rows[0][3] if rows else ""
                passed = "COMPACTION_TRIGGER_COUNT" in top_content
                checks.append((query, passed))
                status = "PASS" if passed else "FAIL"
                print(f"  [{status}] config key ranks rank-1: {passed}")

            print()

        print("─" * COL_WIDTH)
        failures = [q for q, ok in checks if not ok]
        if failures:
            print(f"SMOKE FAILED — {len(failures)} check(s) failed: {failures}")
        else:
            print(f"SMOKE PASSED — {len(checks)} check(s) OK")
        print()
        return len(failures) == 0

    finally:
        if memory is not None:
            _close_pool(memory)
        try:
            os.unlink(db_path)
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid search smoke harness")
    parser.add_argument(
        "--fts-weight",
        type=float,
        default=0.35,
        help="FTS5 weight in combined score (default: 0.35)",
    )
    args = parser.parse_args()

    if not (0.0 <= args.fts_weight <= 1.0):
        print("Error: --fts-weight must be between 0.0 and 1.0")
        sys.exit(1)

    passed = asyncio.run(run(args.fts_weight))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
