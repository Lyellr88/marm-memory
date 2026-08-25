from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from ..config.settings import DEFAULT_SEMANTIC_DIM, DEFAULT_SEMANTIC_MODEL
from ..core.memory_utils import _embedding_to_bytes
from .embedding_state import (
    get_default_concept_db_path,
    inspect_embedding_state,
    write_embedding_model_marker,
)

_MEMORY_TABLES = (
    ("memories", "content", "embedding"),
    ("memory_chunks", "chunk_text", "embedding"),
)
_CONCEPT_TABLES = (("entities", "name", "name_embedding"),)


class _Encoder(Protocol):
    """All the migration needs from an encoder. Not TextEmbedding: encoder_factory
    exists so tests can inject a double, and pinning the concrete class would
    make every one of those call sites a type error.

    Positional-only because the doubles name the parameter `texts` while fastembed
    names it `documents`, and a named parameter would only accept one of them.
    """

    def embed(self, documents: list[str], /) -> Iterable[np.ndarray]: ...


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _load_encoder() -> _Encoder:
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=DEFAULT_SEMANTIC_MODEL)


MAX_BATCH_PADDED_CHARACTERS = 100_000


def _length_bounded_batches(texts: list[str]) -> list[list[str]]:
    """Group texts so no batch exceeds the padded-size budget.

    Budget is rows times the longest row, which is what the encoder actually
    allocates. Summing raw lengths underestimates a batch that mixes one long text
    with many short ones, which is the normal shape of a memory corpus. A single
    text over the budget forms its own batch; it cannot be split further without
    changing what gets embedded.
    """
    batches: list[list[str]] = []
    current: list[str] = []
    longest = 0
    for text in texts:
        candidate_longest = max(longest, len(text))
        if current and (len(current) + 1) * candidate_longest > (
            MAX_BATCH_PADDED_CHARACTERS
        ):
            batches.append(current)
            current, candidate_longest = [], len(text)
        current.append(text)
        longest = candidate_longest
    if current:
        batches.append(current)
    return batches


def _encode_all(encoder: _Encoder, texts: list[str]) -> list[np.ndarray]:
    """Encode every text, splitting into memory-safe batches first."""
    vectors: list[np.ndarray] = []
    for batch in _length_bounded_batches(texts):
        vectors.extend(_encode_batch(encoder, batch))
    return vectors


def _encode_batch(encoder: _Encoder, texts: list[str]) -> list[np.ndarray]:
    vectors = list(encoder.embed(texts))
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"Encoder returned {len(vectors)} vectors for {len(texts)} texts"
        )
    for vector in vectors:
        if getattr(vector, "shape", (len(vector),))[0] != DEFAULT_SEMANTIC_DIM:
            raise RuntimeError(
                "Configured embedding dimension does not match model output: "
                f"expected {DEFAULT_SEMANTIC_DIM}"
            )
    return vectors


def _migrate_database(
    path: Path,
    tables: tuple[tuple[str, str, str], ...],
    encoder: _Encoder,
    batch_size: int,
    progress: Callable[[str], None],
    force_reencode: bool = False,
) -> int:
    migrated = 0
    target_bytes = DEFAULT_SEMANTIC_DIM * 4
    conn = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=rw", uri=True, isolation_level=None
    )
    with closing(conn):
        for table, text_column, embedding_column in tables:
            if not _table_exists(conn, table):
                continue
            if not _column_exists(conn, table, embedding_column):
                if table == "entities" and embedding_column == "name_embedding":
                    conn.execute("ALTER TABLE entities ADD COLUMN name_embedding BLOB")
                else:
                    continue
            where_clause = f"{text_column} IS NOT NULL"
            params: tuple[int, ...] = ()
            if not force_reencode:
                where_clause += (
                    f" AND ({embedding_column} IS NULL "
                    f"OR LENGTH({embedding_column}) != ?)"
                )
                params = (target_bytes,)
            total = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {where_clause}", params
            ).fetchone()[0]
            completed = 0
            last_rowid = 0
            while completed < total:
                rows = conn.execute(
                    f"SELECT rowid, {text_column} FROM {table} "
                    f"WHERE {where_clause} AND rowid > ? ORDER BY rowid LIMIT ?",
                    (*params, last_rowid, batch_size),
                ).fetchall()
                if not rows:
                    break
                last_rowid = rows[-1][0]
                vectors = _encode_all(encoder, [row[1] for row in rows])
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.executemany(
                        f"UPDATE {table} SET {embedding_column} = ? WHERE rowid = ?",
                        [
                            (_embedding_to_bytes(vector), row[0])
                            for row, vector in zip(rows, vectors)
                        ],
                    )
                    conn.execute("COMMIT")
                except Exception:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise
                completed += len(rows)
                migrated += len(rows)
                progress(f"{table}: {completed}/{total}")
    return migrated


def migrate_embeddings(
    memory_db_path: str,
    concept_db_path: str | None = None,
    *,
    batch_size: int = 100,
    encoder_factory: Callable[[], _Encoder] | None = None,
    progress: Callable[[str], None] = print,
) -> dict:
    """Migrate incompatible vectors and mark success only after both DBs verify."""
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    memory_path = Path(memory_db_path)
    concept_path = Path(concept_db_path or get_default_concept_db_path())
    if not memory_path.exists():
        return {"rows_migrated": 0, "concept_db_present": concept_path.exists()}

    initial_state = inspect_embedding_state(str(memory_path), str(concept_path))
    force_reencode = (
        initial_state.marker != DEFAULT_SEMANTIC_MODEL
        and initial_state.has_vectors
        and initial_state.incompatible == 0
    )
    encoder = (encoder_factory or _load_encoder)()
    _encode_batch(encoder, ["MARM embedding migration dimension check"])

    migration_args = (force_reencode,) if force_reencode else ()
    rows_migrated = _migrate_database(
        memory_path, _MEMORY_TABLES, encoder, batch_size, progress, *migration_args
    )
    if concept_path.exists():
        rows_migrated += _migrate_database(
            concept_path,
            _CONCEPT_TABLES,
            encoder,
            batch_size,
            progress,
            *migration_args,
        )

    state = inspect_embedding_state(str(memory_path), str(concept_path))
    if state.incompatible or state.errors:
        detail = (
            "; ".join(state.errors)
            if state.errors
            else (f"{state.incompatible} incompatible vector(s) remain")
        )
        raise RuntimeError(f"Verification failed: {detail}")
    write_embedding_model_marker(str(memory_path))
    if not inspect_embedding_state(str(memory_path), str(concept_path)).compatible:
        raise RuntimeError(
            "Verification failed: embedding model marker was not recorded"
        )
    return {
        "rows_migrated": rows_migrated,
        "concept_db_present": concept_path.exists(),
    }
