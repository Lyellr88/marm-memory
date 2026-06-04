"""Consolidation worker — hash dedup (Layer 1) and semantic merge (Layer 2)."""

import hashlib
import logging
from typing import Optional


logger = logging.getLogger(__name__)


def normalize_content(content: str) -> str:
    return content.lower().strip()


def compute_content_hash(content: str) -> str:
    """SHA-256 hash of normalized (lowercase, stripped) content."""
    normalized = normalize_content(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def find_exact_duplicate(
    conn, content_hash: str, session_name: str, normalized_content: str
) -> Optional[str]:
    """Return memory_id of an existing exact match within the session, or None.

    Verifies content equality after the hash match so SHA-256 collisions store
    as a new row rather than silently deduplicating different content.
    """
    rows = conn.execute(
        "SELECT id, content FROM memories WHERE content_hash = ? AND session_name = ?",
        (content_hash, session_name),
    ).fetchall()
    for row_id, row_content in rows:
        if normalize_content(row_content) == normalized_content:
            return row_id
    return None


async def find_semantic_duplicate(
    memory, content: str, session_name: str, threshold: float, query_vec=None
) -> Optional[str]:
    """Return memory_id of nearest semantic match at or above threshold in session, or None.

    Falls back to None if encoder unavailable — never blocks a write.
    Accepts a pre-computed query_vec to avoid re-encoding already-embedded content.
    """
    try:
        if query_vec is None and not memory._load_encoder_lazily():
            return None
        results = await memory.recall_similar(content, session=session_name, limit=1, query_vec=query_vec)
        if results and results[0]["similarity"] >= threshold:
            return results[0]["id"]
    except Exception:
        logger.exception("Semantic dedup check failed")
    return None
