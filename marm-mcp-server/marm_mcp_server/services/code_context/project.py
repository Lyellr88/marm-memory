"""Resolve a working directory to an indexed MARM project.

The engine names each project after the repository's absolute path, so the
mapping from "where the agent is" to "which project to query" is a path
containment check against the indexed roots -- not a name match. The deepest
containing root wins, so a nested repo resolves to itself rather than its parent.
"""

from __future__ import annotations

import os


def resolve(
    projects: list[dict], cwd: str | None = None, explicit: str | None = None
) -> dict | None:
    """Pick the project for `cwd`. `explicit` accepts a project name or a path."""
    if not projects:
        return None
    if explicit:
        for p in projects:
            if p.get("name") == explicit:
                return p
        want = os.path.realpath(os.path.expanduser(explicit))
        for p in projects:
            if os.path.realpath(p.get("root_path", "")) == want:
                return p
        # Fall through: an explicit value that matches nothing is a caller error,
        # and silently answering about a different project would be worse.
        return None

    here = os.path.realpath(cwd or os.getcwd())
    best, best_len = None, -1
    for p in projects:
        root = os.path.realpath(p.get("root_path", ""))
        if not root:
            continue
        if here == root or here.startswith(root.rstrip("/") + os.sep):
            if len(root) > best_len:
                best, best_len = p, len(root)
    return best


def short_name(project: dict) -> str:
    """Readable label; the engine id is a path slug and unreadable in prose."""
    root = (project.get("root_path") or "").rstrip("/")
    return os.path.basename(root) or project.get("name", "?")
