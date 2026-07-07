"""Shared helpers and chunking utilities for the MARM memory system."""

import asyncio
import html
import math
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

import numpy as np


def _safe_print(msg: str) -> None:
    """Write diagnostics to stderr so STDIO stdout stays JSON-RPC clean."""
    stderr_buffer = getattr(sys.stderr, "buffer", None)
    if stderr_buffer is not None:
        stderr_buffer.write((msg + "\n").encode("utf-8", errors="replace"))
        stderr_buffer.flush()
    else:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()


_RECALL_DEBUG = os.environ.get("MARM_RECALL_DEBUG", "0") == "1"


def _recall_debug(msg: str) -> None:
    """Lightweight debug logging for recall-path observability.

    Only emits when MARM_RECALL_DEBUG=1. Writes to stderr to keep
    STDIO stdout JSON-RPC clean.
    """
    if _RECALL_DEBUG:
        _safe_print(f"[recall-debug] {msg}")


def _strip_script_tags(text: str) -> str:
    lower = text.lower()
    result = []
    i = 0
    while i < len(text):
        start = lower.find("<script", i)
        if start == -1:
            result.append(text[i:])
            break
        after = start + 7
        if after < len(text) and text[after] not in (" ", "\t", "\n", "\r", ">"):
            result.append(text[i:after])
            i = after
            continue
        result.append(text[i:start])
        open_end = text.find(">", start)
        if open_end == -1:
            break
        j = open_end + 1
        close_end = -1
        while j < len(text):
            cs = lower.find("</script", j)
            if cs == -1:
                break
            close_end = text.find(">", cs)
            if close_end != -1:
                i = close_end + 1
                break
            j = cs + 8
        if close_end == -1:
            result.append(text[open_end + 1 :])
            break
    return "".join(result)


def _temporal_score(timestamp: str, half_life_days: float) -> float:
    """Return a recency score in [0, 1]: 1.0 for brand-new, 0.5 at half_life_days."""
    try:
        ts = datetime.fromisoformat(timestamp)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
        return min(1.0, math.exp(-age_days * math.log(2) / half_life_days))
    except Exception:
        return 0.5


def _safe_fts_query(query: str) -> str | None:
    tokens = re.findall(r"\w+", query)
    if not tokens:
        return None
    return " ".join(f'"{t}"' for t in tokens)


CHUNK_TOKEN_LIMIT = 150
CHUNK_OVERLAP_TOKENS = 50
CHUNK_THRESHOLD_WORDS = 180


def _embedding_to_bytes(vector) -> bytes:
    """Store embeddings in the float32 layout expected by recall scoring."""
    return np.asarray(vector, dtype=np.float32).tobytes()


def _chunk_text(text: str) -> list[str]:
    words = text.split()
    if len(words) <= CHUNK_THRESHOLD_WORDS:
        return []
    step = CHUNK_TOKEN_LIMIT - CHUNK_OVERLAP_TOKENS
    chunks = []
    i = 0
    while i < len(words):
        chunks.append(" ".join(words[i : i + CHUNK_TOKEN_LIMIT]))
        i += step
    return chunks


async def _write_chunks(
    mem_instance,
    db_path: str,
    memory_id: str,
    chunks: list[str],
    expected_content_hash: str,
) -> None:
    embeddings = []
    for chunk in chunks:
        try:
            vec = await asyncio.to_thread(mem_instance._encode_sync, chunk)
            embeddings.append(_embedding_to_bytes(vec))
        except Exception as e:
            _safe_print(f"Chunk encoding failed for memory {memory_id}: {e}")
            return
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        current_hash = conn.execute(
            "SELECT content_hash FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if current_hash is None or current_hash[0] != expected_content_hash:
            _safe_print(
                f"Chunk write aborted for memory {memory_id}: content changed before insert"
            )
            return
        conn.executemany(
            "INSERT INTO memory_chunks (memory_id, chunk_index, chunk_text, embedding)"
            " VALUES (?, ?, ?, ?)",
            [
                (memory_id, i, chunk, emb)
                for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
            ],
        )
        conn.commit()
    except Exception as e:
        _safe_print(f"Chunk DB write failed for memory {memory_id}: {e}")
    finally:
        conn.close()


def sanitize_content(content: str) -> str:
    """Sanitize content to prevent XSS attacks while preserving readability"""
    if not content:
        return content

    if len(content) > 10000:
        content = content[:10000]

    sanitized = content

    sanitized = _strip_script_tags(sanitized)

    sanitized = re.sub(
        r"javascript:", "blocked-protocol:", sanitized, flags=re.IGNORECASE
    )

    sanitized = re.sub(
        r'\son\w+\s*=\s*["\'][^"\']*["\']', "", sanitized, flags=re.IGNORECASE
    )

    sanitized = html.escape(sanitized)

    return sanitized


# ---------------------------------------------------------------------------
# Exact-query detection
# ---------------------------------------------------------------------------

# Patterns that strongly suggest a syntax-heavy, exact-lookup query.
_EXACT_PATTERNS = [
    re.compile(r"[A-Z][A-Z0-9_]{2,}"),  # UPPER_SNAKE_CASE constants / env vars
    re.compile(
        r"[\w./\-]+\.(py|js|ts|json|yaml|yml|toml|cfg|ini|sh|md|env|conf)\b"
    ),  # file paths
    re.compile(r"--[\w\-]+=?"),  # CLI flags  --flag or --flag=value
    re.compile(r"/[\w./\-]{3,}"),  # Unix paths  /home/user/...
    re.compile(r"[A-Za-z_]\w*\("),  # function calls  my_func(
    re.compile(r"\b\w+\.\w+\.\w+\b"),  # dotted namespaces  a.b.c
    re.compile(r"[A-Za-z_]\w*:[A-Za-z_/\d]"),  # key:value or namespace:item
    re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE|HEAD)\s+/"),  # HTTP verbs + path
    re.compile(r"https?://\S+"),  # URLs
    re.compile(r'["`][^"`]{1,80}["`]'),  # backtick or double-quoted strings
    re.compile(r"\b\w+_[A-Z][A-Z0-9_]*\b"),  # mixed_CASE config keys  e.g. server_HOST
]


def _is_exact_query(query: str) -> bool:
    """Return True when the query looks syntax-heavy and warrants exact/lexical retrieval.

    Heuristic: a query is considered exact when it is short (≤ 12 words) AND
    matches at least one syntax pattern (CLI flags, file paths, UPPER_SNAKE constants,
    function calls, API names, dotted namespaces, HTTP verbs, URLs, quoted strings).
    """
    word_count = len(query.split())
    if word_count > 12:
        # Long natural-language sentences are almost never exact lookups.
        return False
    return any(pat.search(query) for pat in _EXACT_PATTERNS)
