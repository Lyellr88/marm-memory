import asyncio
import html
import math
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

import numpy as np

from ..config.settings import FTS_EXTRA_STOPWORDS, FTS_QUERY_MODE

if TYPE_CHECKING:
    from .memory import MARMMemory


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


def _temporal_score(
    timestamp: str, half_life_days: float, now: datetime | None = None
) -> float:
    """Return a recency score in [0, 1]: 1.0 for brand-new, 0.5 at half_life_days.

    Pass `now` to score a whole candidate set against one reference instant.
    Reading the clock per candidate instead makes two rows with the same stored
    timestamp score fractionally apart, which is enough to decide their order
    whenever the relevance scores are tied, so recall would rank them by
    microsecond timing rather than by anything reproducible. Defaults to the
    current time so existing callers are unaffected.
    """
    try:
        ts = datetime.fromisoformat(timestamp)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        reference = now if now is not None else datetime.now(timezone.utc)
        age_days = (reference - ts).total_seconds() / 86400
        return min(1.0, math.exp(-age_days * math.log(2) / half_life_days))
    except Exception:
        return 0.5


def _safe_fts_query(query: str) -> str | None:
    tokens = re.findall(r"\w+", query)
    if not tokens:
        return None
    return " ".join(f'"{t}"' for t in tokens)


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
        if not kept:
            return None
        tokens = kept

    return " OR ".join(f'"{t}"' for t in tokens)


def log_search_terms(query: str, limit: int = 12) -> list[str]:
    """Tokens for the log lane's LIKE search, stopwords dropped.

    The lane has no FTS index, so it substring-matched the whole query and a
    natural-language question could only hit if it appeared verbatim in a topic
    or summary. Falls back to the raw tokens when every one is a stopword, and
    to an empty list when nothing is searchable, so callers keep a fail-open
    path consistent with the FTS helpers above.
    """
    tokens = re.findall(r"\w+", query)
    if not tokens:
        return []
    kept = [t for t in tokens if t.lower() not in _FTS_STOPWORDS]
    seen: set[str] = set()
    unique: list[str] = []
    for token in kept or tokens:
        folded = token.lower()
        if folded not in seen:
            seen.add(folded)
            unique.append(token)
    return unique[:limit]


def build_log_search(
    query: str,
    *,
    session_name: str | None,
    search_all: bool,
    project: str | None,
    platform: str | None,
    limit: int,
) -> tuple[str, list]:
    """Build the log lane's query once, so HTTP and STDIO cannot drift apart.

    Both transports had their own copy of this SQL, and repairing only the HTTP
    copy left STDIO returning nothing for natural-language queries.
    """
    terms = log_search_terms(query) or [query]
    likes = [f"%{term}%" for term in terms]
    match_expr = " + ".join(
        ["(CASE WHEN topic LIKE ? OR summary LIKE ? THEN 1 ELSE 0 END)"] * len(terms)
    )
    where_expr = " OR ".join(["topic LIKE ? OR summary LIKE ?"] * len(terms))
    sql = (
        "SELECT id, session_name, topic, summary, entry_date, project, platform, "
        f"({match_expr}) AS match_count FROM log_entries WHERE ({where_expr})"
    )
    params: list = [value for like in likes for value in (like, like)] * 2
    if not search_all:
        sql += " AND session_name = ?"
        params.append(session_name)
    if project is not None:
        sql += " AND project = ?"
        params.append(project)
    if platform is not None:
        sql += " AND platform = ?"
        params.append(platform)
    sql += " ORDER BY match_count DESC, entry_date DESC LIMIT ?"
    params.append(limit)
    return sql, params


MEMORY_CHUNK_THRESHOLD_WORDS = 500
MEMORY_CHUNK_TARGET_WORDS = 250
MEMORY_CHUNK_OVERLAP_WORDS = 50

DOC_CHUNK_THRESHOLD_WORDS = 1000
DOC_CHUNK_TARGET_WORDS = 800
DOC_CHUNK_OVERLAP_WORDS = 100


def _embedding_to_bytes(vector: np.ndarray) -> bytes:
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
    num_chunks = max(1, -(-n // target_size))
    spans = _split_evenly(words, num_chunks)
    chunks = []
    for start, end in spans:
        pad_start = max(0, start - overlap // 2)
        pad_end = min(n, end + overlap // 2)
        chunks.append(" ".join(words[pad_start:pad_end]))
    return chunks


def _spawn_chunk_write(
    mem_instance: Any,
    memory_id: str,
    chunks: list[str],
    expected_content_hash: str,
) -> asyncio.Task:
    """Start a chunk write and keep its handle so shutdown can wait for it.

    The done-callback is what keeps the set from growing for the life of the
    process; every caller must go through here rather than create_task directly.
    """
    task = asyncio.create_task(
        _write_chunks(
            mem_instance, mem_instance.db_path, memory_id, chunks, expected_content_hash
        )
    )
    mem_instance._pending_chunk_writes.add(task)
    task.add_done_callback(mem_instance._pending_chunk_writes.discard)
    return task


async def drain_chunk_writes(
    mem_instance: Any, timeout: float, log: Callable[[str], None]
) -> int:
    """Wait up to `timeout` for in-flight chunk writes. Returns the count still pending.

    Deliberately does not cancel: the point is to let the writes land. Callers
    accept that an expired wait loses rows, which `--rechunk` then repairs.
    """
    pending = {task for task in mem_instance._pending_chunk_writes if not task.done()}
    if not pending:
        return 0
    done, still_pending = await asyncio.wait(pending, timeout=timeout)
    if still_pending:
        log(
            f"{len(still_pending)} chunk write(s) did not finish within {timeout}s; "
            "run 'marm-mcp-server --rechunk' to restore the missing chunks"
        )
    else:
        log(f"Chunk writes drained ({len(done)} task(s))")
    return len(still_pending)


async def _write_chunks(
    mem_instance: "MARMMemory",
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
            conn.execute("ROLLBACK")
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
        if conn.in_transaction:
            conn.execute("ROLLBACK")
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


_EXACT_PATTERNS = [
    re.compile(r"[A-Z][A-Z0-9_]{2,}"),
    re.compile(r"[\w./\-]+\.(py|js|ts|json|yaml|yml|toml|cfg|ini|sh|md|env|conf)\b"),
    re.compile(r"--[\w\-]+=?"),
    re.compile(r"/[\w./\-]{3,}"),
    re.compile(r"[A-Za-z_]\w*\("),
    re.compile(r"\b\w+\.\w+\.\w+\b"),
    re.compile(r"[A-Za-z_]\w*:[A-Za-z_/\d]"),
    re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE|HEAD)\s+/"),
    re.compile(r"https?://\S+"),
    re.compile(r'["`][^"`]{1,80}["`]'),
    re.compile(r"\b\w+_[A-Z][A-Z0-9_]*\b"),
]


def _is_exact_query(query: str) -> bool:
    """Return True when the query looks syntax-heavy and warrants exact/lexical retrieval.

    Heuristic: a query is considered exact when it is short (≤ 12 words) AND
    matches at least one syntax pattern (CLI flags, file paths, UPPER_SNAKE constants,
    function calls, API names, dotted namespaces, HTTP verbs, URLs, quoted strings).
    """
    word_count = len(query.split())
    if word_count > 12:
        return False
    return any(pat.search(query) for pat in _EXACT_PATTERNS)
