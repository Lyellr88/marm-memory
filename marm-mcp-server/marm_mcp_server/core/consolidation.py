"""Consolidation worker — hash dedup (Layer 1) and semantic merge (Layer 2)."""

import hashlib
import logging
import sqlite3
from typing import Optional

from ..config.settings import MARM_PROJECT, MARM_PLATFORM

logger = logging.getLogger(__name__)
_UNSET = object()

# Enough rows to absorb reordering by the lexical and recency signals.
_DUPLICATE_CANDIDATES = 5


def normalize_content(content: str) -> str:
    return content.lower().strip()


def compute_content_hash(content: str) -> str:
    """SHA-256 hash of normalized (lowercase, stripped) content."""
    normalized = normalize_content(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def find_exact_duplicate(
    conn: sqlite3.Connection,
    content_hash: str,
    session_name: str,
    normalized_content: str,
    project: object = _UNSET,
    platform: object = _UNSET,
) -> Optional[str]:
    """Return memory_id of an existing exact match within the session, or None.

    Verifies content equality after the hash match so SHA-256 collisions store
    as a new row rather than silently deduplicating different content.
    """
    scoped_project = MARM_PROJECT or None if project is _UNSET else project
    scoped_platform = MARM_PLATFORM or None if platform is _UNSET else platform
    rows = conn.execute(
        "SELECT id, content FROM memories WHERE content_hash = ? AND session_name = ? AND project IS ? AND platform IS ?",
        (content_hash, session_name, scoped_project, scoped_platform),
    ).fetchall()
    for row_id, row_content in rows:
        if normalize_content(row_content) == normalized_content:
            return row_id
    return None


async def find_semantic_duplicate(
    memory,
    content: str,
    session_name: str,
    threshold: float,
    query_vec=None,
    project: object = _UNSET,
    platform: object = _UNSET,
) -> Optional[str]:
    """Return memory_id of a semantic match at or above threshold in session, or None.

    Falls back to None if encoder unavailable — never blocks a write.
    Accepts a pre-computed query_vec to avoid re-encoding already-embedded content.

    threshold is a cosine threshold, so this compares raw cosine and not
    "similarity", which is blended with the lexical and recency signals. A row
    with no cosine is never a duplicate.
    """
    try:
        if query_vec is None and not memory._load_encoder_lazily():
            return None
        scoped_project = MARM_PROJECT or None if project is _UNSET else project
        scoped_platform = MARM_PLATFORM or None if platform is _UNSET else platform
        # exact_mode="semantic" because the exact lane produces no cosine.
        results = await memory.recall_similar(
            content,
            session=session_name,
            limit=_DUPLICATE_CANDIDATES,
            query_vec=query_vec,
            project=scoped_project,
            platform=scoped_platform,
            exact_mode="semantic",
            with_cosine=True,
        )
        scored = [r for r in results if "cosine" in r]
        if scored:
            nearest = max(scored, key=lambda r: r["cosine"])
            if nearest["cosine"] >= threshold:
                return nearest["id"]
    except Exception:
        logger.exception("Semantic dedup check failed")
    return None
