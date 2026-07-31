"""Stopped-server backfill that brings memory_chunks in line with current config.

Repairs three states: chunk rows split under superseded size constants, memories
over threshold with no chunk rows at all (a lost fire-and-forget write), and
memories now under threshold that still carry chunks.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable

from ..core.memory_utils import (
    DOC_CHUNK_OVERLAP_WORDS,
    DOC_CHUNK_TARGET_WORDS,
    DOC_CHUNK_THRESHOLD_WORDS,
    MEMORY_CHUNK_OVERLAP_WORDS,
    MEMORY_CHUNK_TARGET_WORDS,
    MEMORY_CHUNK_THRESHOLD_WORDS,
    _chunk_text,
    _embedding_to_bytes,
)
from .embedding_migration import _encode_all, _load_encoder
from .embedding_state import get_default_concept_db_path, inspect_embedding_state

_MEMORY_PROFILE = {
    "threshold": MEMORY_CHUNK_THRESHOLD_WORDS,
    "target_size": MEMORY_CHUNK_TARGET_WORDS,
    "overlap": MEMORY_CHUNK_OVERLAP_WORDS,
}
_DOC_PROFILE = {
    "threshold": DOC_CHUNK_THRESHOLD_WORDS,
    "target_size": DOC_CHUNK_TARGET_WORDS,
    "overlap": DOC_CHUNK_OVERLAP_WORDS,
}


class RechunkRefused(RuntimeError):
    """Raised when preconditions make re-chunking unsafe."""


def _profile_for(context_type: str | None) -> dict:
    """Doc mirrors are identified by context_type = 'doc' and nothing else.

    _store_doc_mirror is the only writer of that value, and auto_classify_content
    never produces it. Docs indexed by services/documentation.py go through
    _store_memory, so they take the memory profile despite doc-ish context types.
    """
    return _DOC_PROFILE if context_type == "doc" else _MEMORY_PROFILE


def _stored_chunks(conn: sqlite3.Connection, memory_id: str) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT chunk_text FROM memory_chunks WHERE memory_id = ?"
            " ORDER BY chunk_index",
            (memory_id,),
        )
    ]


def _plan(conn: sqlite3.Connection) -> tuple[list[dict], int]:
    """Compare desired against stored chunks for every eligible memory.

    Textual and encoder-free on purpose: a database that needs nothing must not
    pay a model load. Returns the work list and the count already correct.
    """
    work: list[dict] = []
    already_correct = 0
    rows = conn.execute(
        "SELECT id, content, context_type, content_hash FROM memories"
        " WHERE content IS NOT NULL"
        " AND (compaction_role IS NULL OR compaction_role != 'source')"
    ).fetchall()
    for memory_id, content, context_type, content_hash in rows:
        desired = _chunk_text(content, **_profile_for(context_type))
        stored = _stored_chunks(conn, memory_id)
        if desired == stored:
            if stored:
                already_correct += 1
            continue
        work.append(
            {
                "memory_id": memory_id,
                "content_hash": content_hash,
                "desired": desired,
                "stored_count": len(stored),
            }
        )
    return work, already_correct


def _apply(conn: sqlite3.Connection, item: dict, embeddings: list[bytes]) -> bool:
    """Rewrite one memory's chunk rows in a single transaction.

    Deletes first rather than relying on the INSERT OR REPLACE upsert: re-splitting
    shrinks counts, so an upsert alone would leave the tail chunk_index rows behind
    as orphans.
    """
    memory_id = item["memory_id"]
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = conn.execute(
            "SELECT content_hash FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if current is None or current[0] != item["content_hash"]:
            conn.execute("ROLLBACK")
            return False
        conn.execute("DELETE FROM memory_chunks WHERE memory_id = ?", (memory_id,))
        if item["desired"]:
            conn.executemany(
                "INSERT INTO memory_chunks"
                " (memory_id, chunk_index, chunk_text, embedding)"
                " VALUES (?, ?, ?, ?)",
                [
                    (memory_id, index, chunk, embedding)
                    for index, (chunk, embedding) in enumerate(
                        zip(item["desired"], embeddings)
                    )
                ],
            )
        conn.execute("COMMIT")
        return True
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def rechunk_memories(
    memory_db_path: str,
    concept_db_path: str | None = None,
    *,
    encoder_factory: Callable[[], object] | None = None,
    progress: Callable[[str], None] = print,
) -> dict:
    """Re-split stale chunks, fill missing ones, and drop chunks below threshold."""
    memory_path = Path(memory_db_path)
    empty = {
        "memories_rechunked": 0,
        "memories_skipped": 0,
        "chunks_before": 0,
        "chunks_after": 0,
    }
    if not memory_path.exists():
        return empty

    state = inspect_embedding_state(
        str(memory_path), str(concept_db_path or get_default_concept_db_path())
    )
    if state.marker_incompatible or state.incompatible:
        # New chunk vectors would land at a different dimension than the parent
        # rows, and _score_chunk_aware silently drops mismatched dimensions.
        raise RechunkRefused(
            "The stored vectors do not match the configured embedding model. "
            "Run 'marm-mcp-server --migrate-embeddings' first."
        )

    conn = sqlite3.connect(
        f"{memory_path.resolve().as_uri()}?mode=rw", uri=True, isolation_level=None
    )
    with closing(conn):
        work, already_correct = _plan(conn)
        if not work:
            progress(f"{already_correct} memories already correct, nothing to re-chunk")
            return {**empty, "memories_skipped": already_correct}

        progress(f"scanning {len(work) + already_correct} chunked memories")
        needs_encoder = any(item["desired"] for item in work)
        encoder = (encoder_factory or _load_encoder)() if needs_encoder else None
        rechunked = 0
        chunks_before = 0
        chunks_after = 0
        for item in work:
            embeddings: list[bytes] = []
            if item["desired"]:
                embeddings = [
                    _embedding_to_bytes(vector)
                    for vector in _encode_all(encoder, item["desired"])
                ]
            if not _apply(conn, item, embeddings):
                progress(f"  {item['memory_id'][:8]}: skipped, content changed")
                continue
            rechunked += 1
            chunks_before += item["stored_count"]
            chunks_after += len(item["desired"])
            if not item["desired"]:
                progress(
                    f"  {item['memory_id'][:8]}: removed {item['stored_count']} chunk(s),"
                    " now under threshold"
                )
            elif item["stored_count"] == 0:
                progress(
                    f"  {item['memory_id'][:8]}: filled {len(item['desired'])} missing chunk(s)"
                )
            else:
                progress(
                    f"  {item['memory_id'][:8]}: re-split"
                    f" ({item['stored_count']} chunks -> {len(item['desired'])})"
                )
        progress(f"  {already_correct} already correct, skipped")
    return {
        "memories_rechunked": rechunked,
        "memories_skipped": already_correct,
        "chunks_before": chunks_before,
        "chunks_after": chunks_after,
    }
