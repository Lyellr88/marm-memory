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

from ..config.settings import FTS_EXTRA_STOPWORDS, FTS_QUERY_MODE


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


# English function words dropped by the or_nostop query mode.
#
# Deliberately limited to words that are ubiquitous *and* carry no content sense,
# because the FTS5 tokenizer is case-insensitive ("porter ascii", see
# core/memory_db.py) so a query term cannot be distinguished from its capitalized
# proper-noun twin. Each word is therefore all-or-nothing: listing it loses the
# proper-noun sense entirely, omitting it keeps the function-word sense in play.
#
# Words with a real content sense are intentionally absent -- month and name
# collisions ("May", "Will"), acronyms ("US"), content verbs ("won", "get",
# "need", "know"), and contraction fragments that double as words ("don", "won").
# Omitting them costs little: BM25 already discounts frequent terms by inverse
# document frequency, so a mid-frequency word ranks low on its own rather than
# swamping the candidate pool.
#
# Scoped to the default English embedding model; non-English queries keep every
# token and simply OR them, which is less precise but never an error.
# FTS_EXTRA_STOPWORDS extends this per deployment.
_FTS_BASE_STOPWORDS = frozenset(
    """
    a an the this that these those there here
    i me my you your he him his she her hers it its
    we our they them their
    what who whom whose when where why how which
    is are was were be been being am do does did
    have has had
    of to in into for on at by with from about as
    and or but if then than so not no too very
    s t
    """.split()
)

_FTS_STOPWORDS = _FTS_BASE_STOPWORDS | FTS_EXTRA_STOPWORDS


def _wide_fts_query(query: str) -> str | None:
    """Build the semantic lane's FTS5 MATCH string, widened beyond strict AND.

    `_safe_fts_query` space-joins tokens, which FTS5 reads as an implicit AND, so
    a natural-language question only matched a memory containing *every* word --
    measured at 0 of 400 LoCoMo questions producing candidates. This ORs the
    tokens instead so the lane produces a real candidate pool for semantic
    reranking to filter.

    Used by the semantic lane and, since v2.33.0, by the semantic-fallback lane.
    The exact/lexical lane keeps `_safe_fts_query`, because its BM25 hits are
    returned to the caller without any semantic rerank to clean up over-broad
    matches.

    Returns None when nothing searchable survives, matching `_safe_fts_query`'s
    contract so callers keep their existing fail-open path.
    """
    if FTS_QUERY_MODE == "and":
        return _safe_fts_query(query)

    tokens = re.findall(r"\w+", query)
    if not tokens:
        return None

    if FTS_QUERY_MODE == "or_nostop":
        kept = [t for t in tokens if t.lower() not in _FTS_STOPWORDS]
        # An all-stopword query ("what is the") has nothing worth matching;
        # returning None routes it to pure semantic recall rather than OR-ing
        # filler words against every memory in the store.
        if not kept:
            return None
        tokens = kept

    # Quoting each token is a safety control, not formatting: it stops user input
    # from being parsed as FTS5 syntax (NEAR, *, ^, column filters).
    return " OR ".join(f'"{t}"' for t in tokens)


# Sized for jina-embeddings-v2-small-en's 8,192-token window (config/settings.py's
# DEFAULT_SEMANTIC_MODEL) -- roughly 30x the 256-token window the old 150-word
# chunks were tuned for. Starting points to tune from real usage, not
# validated-forever constants -- same framing as this codebase's other
# embedding-adjacent thresholds (CONCEPT_DUPLICATE_SIMILARITY_THRESHOLD).
MEMORY_CHUNK_THRESHOLD_WORDS = 500
MEMORY_CHUNK_TARGET_WORDS = 250
MEMORY_CHUNK_OVERLAP_WORDS = 50

DOC_CHUNK_THRESHOLD_WORDS = 1000
DOC_CHUNK_TARGET_WORDS = 800
DOC_CHUNK_OVERLAP_WORDS = 100


def _embedding_to_bytes(vector) -> bytes:
    """Store embeddings in the float32 layout expected by recall scoring."""
    return np.asarray(vector, dtype=np.float32).tobytes()


def _split_evenly(words: list, num_chunks: int) -> list:
    """Divide word indices into num_chunks contiguous, near-equal spans.

    Remainder words are distributed across the first few spans (not dumped
    entirely on the last one), so a memory just over threshold never
    produces one full-size chunk plus a tiny low-value fragment.
    """
    n = len(words)
    base = n // num_chunks
    remainder = n % num_chunks
    spans = []
    start = 0
    for i in range(num_chunks):
        size = base + (1 if i < remainder else 0)
        spans.append((start, start + size))
        start += size
    return spans


def _chunk_text(
    text: str, *, threshold: int, target_size: int, overlap: int
) -> list[str]:
    """Split text into evenly-sized chunks once it exceeds threshold words.

    Replaces the old fixed-window sliding approach, which could leave a
    tiny, low-value trailing fragment (e.g. a 280-word memory splitting
    into 250+30 words) instead of evenly-sized, coherent chunks.
    """
    words = text.split()
    n = len(words)
    if n <= threshold:
        return []
    num_chunks = max(1, -(-n // target_size))  # ceil division
    spans = _split_evenly(words, num_chunks)
    chunks = []
    for start, end in spans:
        pad_start = max(0, start - overlap // 2)
        pad_end = min(n, end + overlap // 2)
        chunks.append(" ".join(words[pad_start:pad_end]))
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
            "INSERT OR REPLACE INTO memory_chunks"
            " (memory_id, chunk_index, chunk_text, embedding)"
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
