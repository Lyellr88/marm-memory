"""Durable translation between memory scopes and code-graph projects."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import PurePath, PureWindowsPath
from typing import Any


@dataclass(frozen=True)
class CodeProjectBinding:
    graph_project: str
    memory_project: str
    root_path: str
    source: str
    created_at: str
    updated_at: str
    last_verified_at: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def normalize_project_key(value: str) -> str:
    """Normalize the user-facing project spellings used by MARM and CBM."""
    return "-".join(value.strip().split()).casefold()


def root_directory_key(root_path: str) -> str:
    normalized = root_path.rstrip("/\\")
    path = PureWindowsPath(normalized) if "\\" in normalized else PurePath(normalized)
    return normalize_project_key(path.name)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connection() -> Any:
    from .memory import memory

    return memory.get_connection()


def _binding(row: Any) -> CodeProjectBinding | None:
    if row is None:
        return None
    return CodeProjectBinding(*row)


def get_by_graph_project(graph_project: str) -> CodeProjectBinding | None:
    with _connection() as conn:
        row = conn.execute(
            "SELECT graph_project, memory_project, root_path, source, created_at, "
            "updated_at, last_verified_at FROM code_project_bindings "
            "WHERE graph_project = ?",
            (graph_project,),
        ).fetchone()
    return _binding(row)


def get_by_memory_project(memory_project: str | None) -> CodeProjectBinding | None:
    if not memory_project:
        return None
    with _connection() as conn:
        row = conn.execute(
            "SELECT graph_project, memory_project, root_path, source, created_at, "
            "updated_at, last_verified_at FROM code_project_bindings "
            "WHERE memory_project = ?",
            (memory_project,),
        ).fetchone()
    return _binding(row)


def memory_project_scopes() -> list[str]:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT project FROM memories "
            "WHERE project IS NOT NULL AND TRIM(project) != '' ORDER BY project"
        ).fetchall()
    return [str(row[0]) for row in rows]


def matching_memory_project_scopes(
    graph_project: str, root_path: str | None
) -> list[str]:
    keys = {normalize_project_key(graph_project)}
    if root_path:
        keys.add(root_directory_key(root_path))
    return [
        scope
        for scope in memory_project_scopes()
        if normalize_project_key(scope) in keys
    ]


def auto_bind(
    graph_project: str, root_path: str
) -> tuple[str, CodeProjectBinding | None]:
    """Record an automatic binding only for one unambiguous memory scope."""
    existing = get_by_graph_project(graph_project)
    now = _now()
    if existing is not None:
        with _connection() as conn:
            conn.execute(
                "UPDATE code_project_bindings SET root_path = ?, updated_at = ?, "
                "last_verified_at = ? WHERE graph_project = ?",
                (root_path, now, now, graph_project),
            )
        return "bound", get_by_graph_project(graph_project)

    candidates = matching_memory_project_scopes(graph_project, root_path)
    if len(candidates) != 1:
        return ("ambiguous" if candidates else "unbound"), None

    memory_project = candidates[0]
    conflict = get_by_memory_project(memory_project)
    if conflict is not None:
        return "conflict", None

    with _connection() as conn:
        try:
            conn.execute(
                "INSERT INTO code_project_bindings "
                "(graph_project, memory_project, root_path, source, created_at, "
                "updated_at, last_verified_at) VALUES (?, ?, ?, 'auto', ?, ?, ?)",
                (graph_project, memory_project, root_path, now, now, now),
            )
        except sqlite3.IntegrityError:
            return "conflict", None
    return "bound", get_by_graph_project(graph_project)


def set_user_binding(
    graph_project: str, memory_project: str, root_path: str
) -> CodeProjectBinding:
    if memory_project not in memory_project_scopes():
        raise ValueError("memory_project_not_found")
    current = get_by_graph_project(graph_project)
    if current is not None and current.memory_project != memory_project:
        raise ValueError("graph_project_already_bound")
    existing = get_by_memory_project(memory_project)
    if existing is not None and existing.graph_project != graph_project:
        raise ValueError("memory_project_already_bound")
    now = _now()
    with _connection() as conn:
        conn.execute(
            "INSERT INTO code_project_bindings "
            "(graph_project, memory_project, root_path, source, created_at, "
            "updated_at, last_verified_at) VALUES (?, ?, ?, 'user', ?, ?, ?) "
            "ON CONFLICT(graph_project) DO UPDATE SET memory_project = excluded.memory_project, "
            "root_path = excluded.root_path, source = 'user', updated_at = excluded.updated_at, "
            "last_verified_at = excluded.last_verified_at",
            (graph_project, memory_project, root_path, now, now, now),
        )
    binding = get_by_graph_project(graph_project)
    assert binding is not None
    return binding


def drop_graph_project(graph_project: str) -> bool:
    with _connection() as conn:
        cursor = conn.execute(
            "DELETE FROM code_project_bindings WHERE graph_project = ?",
            (graph_project,),
        )
    return bool(cursor.rowcount)
