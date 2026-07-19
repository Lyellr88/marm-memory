"""Inspect persisted embedding compatibility without initializing runtime stores."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from ..config.settings import (
    DEFAULT_DB_PATH,
    DEFAULT_SEMANTIC_DIM,
    DEFAULT_SEMANTIC_MODEL,
)

EMBEDDING_MODEL_SETTING = "embedding_model"
# notebook_entries.embedding is retired -- scratch writes no longer populate
# it (services/notebook.py's _add), so it's deliberately excluded here.
# Promoted docs get their recall reach through their memories mirror, which
# the "memories" table below already covers.
_MEMORY_TABLES = (
    ("memories", "embedding"),
    ("memory_chunks", "embedding"),
)
_CONCEPT_TABLES = (("entities", "name_embedding"),)


@dataclass(frozen=True)
class EmbeddingTableState:
    database: str
    table: str
    total: int
    incompatible: int


@dataclass(frozen=True)
class EmbeddingState:
    marker: str | None
    tables: tuple[EmbeddingTableState, ...]
    errors: tuple[str, ...] = ()

    @property
    def incompatible(self) -> int:
        return sum(table.incompatible for table in self.tables)

    @property
    def has_vectors(self) -> bool:
        return any(table.total for table in self.tables)

    @property
    def marker_incompatible(self) -> bool:
        return self.has_vectors and self.marker != DEFAULT_SEMANTIC_MODEL

    @property
    def compatible(self) -> bool:
        return (
            self.incompatible == 0 and not self.marker_incompatible and not self.errors
        )


def get_default_concept_db_path() -> str:
    """Resolve the concept DB path without creating its parent or database."""
    configured = os.environ.get("MARM_CONCEPT_DB_PATH")
    if configured:
        return configured
    return str(Path.home() / ".marm" / "index" / "marm_index.db")


def _open_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _open_existing_writable(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _inspect_tables(
    path: Path, database: str, tables: Iterable[tuple[str, str]]
) -> list[EmbeddingTableState]:
    if not path.exists():
        return []

    states = []
    with closing(_open_read_only(path)) as conn:
        for table, column in tables:
            if not _table_exists(conn, table) or not _column_exists(
                conn, table, column
            ):
                continue
            total, incompatible = conn.execute(
                f"SELECT COUNT(*), COALESCE(SUM(LENGTH({column}) != ?), 0) "
                f"FROM {table} WHERE {column} IS NOT NULL",
                (DEFAULT_SEMANTIC_DIM * 4,),
            ).fetchone()
            states.append(
                EmbeddingTableState(
                    database=database,
                    table=table,
                    total=int(total),
                    incompatible=int(incompatible),
                )
            )
    return states


def inspect_embedding_state(
    memory_db_path: str = DEFAULT_DB_PATH,
    concept_db_path: str | None = None,
) -> EmbeddingState:
    """Return persisted vector dimensions without creating either database."""
    memory_path = Path(memory_db_path)
    concept_path = Path(concept_db_path or get_default_concept_db_path())
    tables = []
    errors = []
    try:
        tables.extend(_inspect_tables(memory_path, "memory", _MEMORY_TABLES))
    except (OSError, sqlite3.Error) as exc:
        errors.append(f"memory database inspection failed: {exc}")
    try:
        tables.extend(_inspect_tables(concept_path, "concept", _CONCEPT_TABLES))
    except (OSError, sqlite3.Error) as exc:
        errors.append(f"concept database inspection failed: {exc}")

    marker = None
    if memory_path.exists():
        try:
            with closing(_open_read_only(memory_path)) as conn:
                if _table_exists(conn, "user_settings"):
                    row = conn.execute(
                        "SELECT value FROM user_settings WHERE key = ?",
                        (EMBEDDING_MODEL_SETTING,),
                    ).fetchone()
                    marker = row[0] if row else None
        except (OSError, sqlite3.Error) as exc:
            message = f"memory model marker inspection failed: {exc}"
            if message not in errors:
                errors.append(message)
    return EmbeddingState(marker=marker, tables=tuple(tables), errors=tuple(errors))


def write_embedding_model_marker(memory_db_path: str = DEFAULT_DB_PATH) -> None:
    """Persist the current model marker in an already-existing memory database."""
    memory_path = Path(memory_db_path)
    if not memory_path.exists():
        return
    with closing(_open_existing_writable(memory_path)) as conn:
        with conn:
            if not _table_exists(conn, "user_settings"):
                return
            conn.execute(
                "INSERT INTO user_settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (
                    EMBEDDING_MODEL_SETTING,
                    DEFAULT_SEMANTIC_MODEL,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )


def check_embedding_compatibility(
    *,
    memory_db_path: str = DEFAULT_DB_PATH,
    concept_db_path: str | None = None,
    warn: Callable[[str], None] | None = None,
) -> EmbeddingState:
    """Inspect vector/model compatibility or emit one migration warning."""
    state = inspect_embedding_state(memory_db_path, concept_db_path)
    if state.compatible:
        if not state.has_vectors and state.marker != DEFAULT_SEMANTIC_MODEL:
            write_embedding_model_marker(memory_db_path)
        return state

    if warn is not None:
        if state.errors:
            warn(
                "Embedding compatibility inspection was incomplete ("
                + "; ".join(state.errors)
                + "); core memory remains available, but inspect the database before "
                "running marm-mcp-server --migrate-embeddings"
            )
        elif state.marker_incompatible:
            prior_model = state.marker or "an unmarked prior model"
            warn(
                f"Found embeddings written by {prior_model}; stop MARM and run "
                "marm-mcp-server --migrate-embeddings"
            )
        else:
            warn(
                f"Found {state.incompatible} embedding vector(s) incompatible with "
                f"{DEFAULT_SEMANTIC_MODEL}; stop MARM and run "
                "marm-mcp-server --migrate-embeddings"
            )
    return state
