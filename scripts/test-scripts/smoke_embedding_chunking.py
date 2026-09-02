#!/usr/bin/env python
"""
Embedding chunking smoke harness.

Checks 1-8 run with injected embeddings — no encoder required.
Checks 9-10 need a live encoder. Without one they count as failures
unless --no-encoder-checks is passed to explicitly opt out.

Usage:
    python scripts/test-scripts/smoke_embedding_chunking.py
    python scripts/test-scripts/smoke_embedding_chunking.py --no-encoder-checks
"""

import argparse
import asyncio
import atexit
import os
import sqlite3
import sys
import tempfile
import time
import uuid
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

SERVER_ROOT = Path(__file__).resolve().parents[2] / "marm-mcp-server"
sys.path.insert(0, str(SERVER_ROOT))

# Override DB path before any import triggers the module-level MARMMemory()
_BOOT_FD, _BOOT_DB_PATH = tempfile.mkstemp(suffix=".db", prefix="smoke_chunking_boot_")
os.close(_BOOT_FD)
_ORIG_DB_PATH = os.environ.get("MARM_DB_PATH")
os.environ["MARM_DB_PATH"] = _BOOT_DB_PATH

import numpy as np  # noqa: E402
from marm_mcp_server.config.settings import (  # noqa: E402
    DEFAULT_SEMANTIC_DIM,
    RECALL_SCAN_LIMIT,
    SEMANTIC_SEARCH_AVAILABLE,
)
from marm_mcp_server.core import memory as memory_module  # noqa: E402
from marm_mcp_server.core.memory import (  # noqa: E402
    MEMORY_CHUNK_OVERLAP_WORDS,
    MEMORY_CHUNK_TARGET_WORDS,
    MEMORY_CHUNK_THRESHOLD_WORDS,
    MARMMemory,
    _chunk_text,
)
from marm_mcp_server.core.memory_scoring import (  # noqa: E402
    _fetch_and_score_embedding_rows,
    _score_chunk_aware,
)

SEP = "-" * 70
SESSION = "smoke-chunking"

# Long memory: the first ~620 words are generic filler, distinctive phrase
# "crystallization threshold boundary" only appears near the end.
# Chunking preserves recall of the distinctive late-body phrase.
# The filler repeats six times so the body clears MEMORY_CHUNK_THRESHOLD_WORDS
# (500 since v2.14.0, 180 before it). At the old multiplier the body was 343
# words, under the current threshold, so _chunk_text returned nothing at all
# and every chunking assertion below was vacuous rather than wrong.
_FILLER = (
    "This document covers general system architecture notes for the server. "
    "Connection pools are initialized at startup to reduce open/close overhead. "
    "Configuration values are read from environment variables at import time. "
    "Logging is directed to stderr to keep STDIO JSON-RPC transport clean. "
    "Session state is persisted in SQLite with WAL mode and NORMAL sync. "
    "The write queue serializes concurrent agent writes to prevent contention. "
    "Rate limiting presets are applied per deployment mode at the HTTP layer. "
    "FTS5 uses the porter ascii tokenizer for stemming on all recall queries. "
    f"Embeddings are generated at {DEFAULT_SEMANTIC_DIM} dimensions. "
    "Compaction candidates are surfaced to agents after the configured write threshold. "
)
_LONG_BODY = (_FILLER * 6) + (
    "The key operational parameter is the crystallization threshold boundary "
    "which governs phase transition detection in the downstream process pipeline. "
    "This value must be configured before calibration or results will be invalid."
)

SHORT_CONTENT = "MARM stores memories in SQLite with WAL mode."


def _memory_chunks(text: str) -> list[str]:
    """Chunk with the MEMORY profile, the one store_memory() actually uses.

    _store_doc_mirror is the only writer that takes the DOC profile, so a
    harness for the memory write path must pass the MEMORY_* values here.
    """
    return _chunk_text(
        text,
        threshold=MEMORY_CHUNK_THRESHOLD_WORDS,
        target_size=MEMORY_CHUNK_TARGET_WORDS,
        overlap=MEMORY_CHUNK_OVERLAP_WORDS,
    )


def _unit_vec(dim: int = DEFAULT_SEMANTIC_DIM) -> np.ndarray:
    v = np.ones(dim, dtype=np.float32)
    return v / np.linalg.norm(v)


def _close_pool(memory: MARMMemory) -> None:
    pool = memory.connection_pool
    while True:
        try:
            conn = pool.pool.get_nowait()
            conn.close()
        except Exception:
            break


def _cleanup_boot_db() -> None:
    try:
        memory_module.memory.connection_pool.close_all()
    except Exception:
        pass
    try:
        os.unlink(_BOOT_DB_PATH)
    except Exception:
        pass
    if _ORIG_DB_PATH is not None:
        os.environ["MARM_DB_PATH"] = _ORIG_DB_PATH
    else:
        os.environ.pop("MARM_DB_PATH", None)


atexit.register(_cleanup_boot_db)


def _insert_memory(
    db_path: str, mem_id: str, content: str, embedding: bytes | None = None
) -> None:
    ts = (
        __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .isoformat()
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, embedding, timestamp, context_type, metadata)"
            " VALUES (?, ?, ?, ?, ?, 'general', '{}')",
            (mem_id, SESSION, content, embedding, ts),
        )
        conn.execute(
            "INSERT INTO memories_fts(rowid, content) SELECT rowid, content FROM memories WHERE id = ?",
            (mem_id,),
        )
        conn.commit()


def _insert_chunks(db_path: str, mem_id: str, n: int, embedding: bytes) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO memory_chunks (memory_id, chunk_index, chunk_text, embedding) VALUES (?, ?, ?, ?)",
            [(mem_id, i, f"chunk {i} text", embedding) for i in range(n)],
        )
        conn.commit()


async def _wait_for_chunks(db_path: str, memory_id: str, timeout: float = 20.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(0.25)
        with sqlite3.connect(db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM memory_chunks WHERE memory_id = ?", (memory_id,)
            ).fetchone()[0]
        if count > 0:
            return count
    return 0


class _Results:
    def __init__(self) -> None:
        self._checks: list[bool] = []

    def check(self, label: str, passed: bool, detail: str = "") -> bool:
        self._checks.append(passed)
        status = "PASS" if passed else "FAIL"
        line = f"  [{status}] {label}"
        if detail:
            line += f" — {detail}"
        print(line)
        return passed

    def skip(self, label: str, reason: str = "") -> None:
        print(f"  [SKIP] {label}" + (f" — {reason}" if reason else ""))

    def require(self, label: str, reason: str = "") -> None:
        """Register a skipped check as a failure."""
        self._checks.append(False)
        print(f"  [FAIL] {label} — SKIPPED: {reason}")

    @property
    def failures(self) -> list[int]:
        return [i + 1 for i, ok in enumerate(self._checks) if not ok]

    @property
    def total(self) -> int:
        return len(self._checks)


async def run(require_encoder: bool) -> bool:
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="smoke_chunking_")
    os.close(fd)
    memory: MARMMemory | None = None
    r = _Results()
    unit = _unit_vec()

    try:
        memory = MARMMemory(db_path)
        memory._encoder_failed = True  # disable encoder for checks 1-8

        # ── CHECK 1: schema ────────────────────────────────────────────────
        print(SEP)
        print("CHECK 1: Schema — memory_chunks table and index exist")
        print(SEP)
        with memory.get_connection() as conn:
            objects = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','index')"
                ).fetchall()
            }
        r.check("memory_chunks table created", "memory_chunks" in objects)
        r.check(
            "idx_memory_chunks_memory_id index created",
            "idx_memory_chunks_memory_id" in objects,
        )
        print()

        # ── CHECK 2: short content — no chunks ────────────────────────────
        print(SEP)
        print("CHECK 2: Short content writes no chunk rows")
        print(SEP)
        short_id = await memory.store_memory(SHORT_CONTENT, session=SESSION)
        await asyncio.sleep(0.3)
        with memory.get_connection() as conn:
            short_chunk_count = conn.execute(
                "SELECT COUNT(*) FROM memory_chunks WHERE memory_id = ?", (short_id,)
            ).fetchone()[0]
        r.check(
            "short content: zero chunk rows",
            short_chunk_count == 0,
            f"got {short_chunk_count}",
        )
        r.check(
            "_chunk_text returns empty for short content",
            _memory_chunks(SHORT_CONTENT) == [],
        )
        print()

        # ── CHECK 3: _chunk_text coverage and overlap ──────────────────────
        print(SEP)
        print("CHECK 3: _chunk_text — threshold, size, overlap, full coverage")
        print(SEP)
        all_words = _LONG_BODY.split()
        long_word_count = len(all_words)
        print(
            f"  Long body word count: {long_word_count}  "
            f"threshold: {MEMORY_CHUNK_THRESHOLD_WORDS}  "
            f"target: {MEMORY_CHUNK_TARGET_WORDS}  "
            f"overlap: {MEMORY_CHUNK_OVERLAP_WORDS}"
        )
        r.check(
            "long body clears the chunking threshold",
            long_word_count > MEMORY_CHUNK_THRESHOLD_WORDS,
            f"{long_word_count} words vs threshold {MEMORY_CHUNK_THRESHOLD_WORDS}",
        )
        chunks = _memory_chunks(_LONG_BODY)
        expected_count = -(-long_word_count // MEMORY_CHUNK_TARGET_WORDS)
        r.check(
            "_chunk_text splits into ceil(words / target) chunks",
            len(chunks) == expected_count,
            f"got {len(chunks)}, expected {expected_count}",
        )
        # Each span is padded by overlap // 2 on both sides, so target alone is
        # not the ceiling: target + overlap is.
        sizes = [len(c.split()) for c in chunks]
        size_cap = MEMORY_CHUNK_TARGET_WORDS + MEMORY_CHUNK_OVERLAP_WORDS
        r.check(
            "no chunk exceeds target + overlap",
            max(sizes, default=0) <= size_cap,
            f"sizes {sizes}, cap {size_cap}",
        )
        # The even split exists to stop a full-size chunk plus a tiny trailing
        # fragment, which is what the old fixed sliding window produced.
        r.check(
            "no tiny trailing fragment — chunks are near-equal",
            len(chunks) < 2 or min(sizes) >= max(sizes) // 2,
            f"sizes {sizes}",
        )
        if len(chunks) >= 2:
            # Span starts come from an even division of the word list, with the
            # remainder spread over the leading spans, then padded backwards by
            # overlap // 2.
            base, remainder = divmod(long_word_count, len(chunks))
            span_start = base + min(1, remainder)
            expected_index = max(0, span_start - MEMORY_CHUNK_OVERLAP_WORDS // 2)
            second_first_word = chunks[1].split()[0]
            expected_first = all_words[expected_index]
            r.check(
                "second chunk starts overlap // 2 words before its span",
                second_first_word == expected_first,
                f"got '{second_first_word}', want '{expected_first}'",
            )
        all_chunk_words = {w for c in chunks for w in c.split()}
        all_body_words = set(all_words)
        r.check(
            "chunks collectively cover all words in the long body",
            all_body_words <= all_chunk_words,
        )
        print()

        # ── CHECK 4: _score_chunk_aware MAX and dedup ──────────────────────
        print(SEP)
        print("CHECK 4: _score_chunk_aware — MAX scoring and deduplication")
        print(SEP)
        ortho = np.zeros(DEFAULT_SEMANTIC_DIM, dtype=np.float32)
        ortho[0] = 1.0

        mem_id = str(uuid.uuid4())
        row = {
            "id": mem_id,
            "session_name": SESSION,
            "content": "x",
            "embedding": None,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "context_type": "general",
            "metadata": "{}",
        }

        # 5 chunks: 4 orthogonal (score ~0.05), 1 aligned (score ~1.0)
        chunks_by_id = {mem_id: [ortho.tobytes()] * 4 + [unit.tobytes()]}
        results, _ = _score_chunk_aware([row], chunks_by_id, unit)
        r.check("score_chunk_aware: one result for one memory", len(results) == 1)
        if results:
            r.check(
                "score_chunk_aware: score is MAX (close to 1.0) not average",
                results[0][1] > 0.9,
                f"score={results[0][1]:.4f}",
            )
        print()

        # ── CHECK 5: mixed chunked + unchunked scoring ─────────────────────
        print(SEP)
        print("CHECK 5: Mixed candidate set — chunked and unchunked score together")
        print(SEP)
        id_chunked = str(uuid.uuid4())
        id_plain = str(uuid.uuid4())
        rows = [
            {
                "id": id_chunked,
                "session_name": SESSION,
                "content": "a",
                "embedding": None,
                "timestamp": "2026-01-01T00:00:00+00:00",
                "context_type": "general",
                "metadata": "{}",
            },
            {
                "id": id_plain,
                "session_name": SESSION,
                "content": "b",
                "embedding": unit.tobytes(),
                "timestamp": "2026-01-01T00:00:00+00:00",
                "context_type": "general",
                "metadata": "{}",
            },
        ]
        mixed_chunks = {id_chunked: [unit.tobytes()]}
        mixed_results, _ = _score_chunk_aware(rows, mixed_chunks, unit)
        result_ids = {res[0]["id"] for res in mixed_results}
        r.check("chunked memory scored", id_chunked in result_ids)
        r.check("unchunked memory scored", id_plain in result_ids)
        r.check("exactly two results returned", len(mixed_results) == 2)
        print()

        # ── CHECK 6: fallback path with injected chunks ────────────────────
        print(SEP)
        print(
            "CHECK 6: Semantic fallback path surfaces chunked memory via injected embeddings"
        )
        print(SEP)
        injected_id = str(uuid.uuid4())
        _insert_memory(
            db_path,
            injected_id,
            "injected chunked memory for fallback test",
            unit.tobytes(),
        )
        _insert_chunks(db_path, injected_id, n=3, embedding=unit.tobytes())

        fallback_results, _, _ = await asyncio.to_thread(
            _fetch_and_score_embedding_rows,
            db_path,
            SESSION,
            RECALL_SCAN_LIMIT,
            unit,
            20,
        )
        fallback_ids = [res[0]["id"] for res in fallback_results]
        r.check(
            "chunked memory found in fallback scan",
            injected_id in fallback_ids,
            f"top ids: {fallback_ids[:3]}",
        )
        r.check(
            "chunked memory appears exactly once in fallback (dedup)",
            fallback_ids.count(injected_id) == 1,
            f"count: {fallback_ids.count(injected_id)}",
        )
        print()

        # ── CHECK 7: cascade delete ────────────────────────────────────────
        print(SEP)
        print("CHECK 7: Cascade delete — deleting parent removes chunk rows")
        print(SEP)
        cascade_id = str(uuid.uuid4())
        _insert_memory(
            db_path, cascade_id, "memory for cascade delete test", unit.tobytes()
        )
        _insert_chunks(db_path, cascade_id, n=4, embedding=unit.tobytes())

        with memory.get_connection() as conn:
            before = conn.execute(
                "SELECT COUNT(*) FROM memory_chunks WHERE memory_id = ?", (cascade_id,)
            ).fetchone()[0]

        with memory.get_connection() as conn:
            conn.execute("DELETE FROM memories WHERE id = ?", (cascade_id,))

        with memory.get_connection() as conn:
            after = conn.execute(
                "SELECT COUNT(*) FROM memory_chunks WHERE memory_id = ?", (cascade_id,)
            ).fetchone()[0]

        r.check("chunk rows existed before delete", before == 4, f"before: {before}")
        r.check(
            "cascade delete removed all chunk rows", after == 0, f"remaining: {after}"
        )
        print()

        # ── CHECKS 8-9: encoder-dependent ─────────────────────────────────
        print(SEP)
        print(
            "CHECKS 8-9: Encoder-dependent — live chunk creation and late-body recall"
        )
        print(SEP)

        memory._encoder_failed = False
        encoder_ok = SEMANTIC_SEARCH_AVAILABLE and memory._load_encoder_lazily()

        if not encoder_ok:
            memory._encoder_failed = True
            msg = "encoder unavailable"
            if require_encoder:
                r.require("long content triggers background chunk task", msg)
                r.require("late-body phrase returned by recall_similar", msg)
                print(
                    "  Install fastembed to pass these, or re-run with --no-encoder-checks to skip them."
                )
            else:
                r.skip("long content triggers background chunk task", msg)
                r.skip("late-body phrase returned by recall_similar", msg)
                print("  Skipped by --no-encoder-checks.")
        else:
            live_id = await memory.store_memory(_LONG_BODY, session=SESSION)
            chunk_count = await _wait_for_chunks(db_path, live_id, timeout=25.0)
            expected = len(_memory_chunks(_LONG_BODY))
            r.check(
                "long content: background task writes chunk rows",
                chunk_count == expected,
                f"got {chunk_count}, expected {expected}",
            )

            query = "crystallization threshold boundary"
            recall_results = await memory.recall_similar(
                query, session=SESSION, limit=10
            )
            long_hits = [res for res in recall_results if res["id"] == live_id]
            r.check(
                "late-body phrase returned by recall_similar",
                len(long_hits) == 1,
                f"hits: {len(long_hits)}",
            )
            if long_hits:
                r.check(
                    "returned content is parent content not chunk text",
                    long_hits[0]["content"] == _LONG_BODY[:10000],
                )
        print()

        # ── Summary ────────────────────────────────────────────────────────
        print(SEP)
        failures = r.failures
        if failures:
            print(
                f"SMOKE FAILED — {len(failures)}/{r.total} check(s) failed at positions: {failures}"
            )
        else:
            print(f"SMOKE PASSED — {r.total} check(s) OK")
        print(SEP)
        return len(failures) == 0

    finally:
        if memory is not None:
            _close_pool(memory)
        try:
            os.unlink(db_path)
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Embedding chunking smoke harness")
    parser.add_argument(
        "--no-encoder-checks",
        action="store_true",
        help="Skip encoder-dependent checks instead of failing when encoder is unavailable",
    )
    args = parser.parse_args()

    passed = asyncio.run(run(require_encoder=not args.no_encoder_checks))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
