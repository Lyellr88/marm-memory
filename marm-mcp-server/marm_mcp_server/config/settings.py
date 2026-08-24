"""Configuration settings for MARM MCP Server."""

import importlib.util
import os
import sys
from pathlib import Path

from .api_key_bootstrap import resolve_marm_api_key
from .env_parsing import (
    _csv_frozenset,
    _safe_bool,
    _safe_choice,
    _safe_float,
    _safe_int,
    _safe_unit_float,
)

# Setting this to 0 makes the server behave exactly as it does when fastembed is
# not installed: no model load, no embeddings written, recall served by the
# keyword/text lane. Two uses: exercising the degraded path without uninstalling
# the dependency (there is no other way to benchmark or verify it), and letting a
# low-memory host skip loading the model at all.
SEMANTIC_SEARCH_ENABLED = os.environ.get("SEMANTIC_SEARCH_ENABLED", "1") == "1"
_FASTEMBED_INSTALLED = importlib.util.find_spec("fastembed") is not None
SEMANTIC_SEARCH_AVAILABLE = SEMANTIC_SEARCH_ENABLED and _FASTEMBED_INSTALLED
if not _FASTEMBED_INSTALLED:
    print(
        "WARNING: Semantic search not available. Install: pip install fastembed",
        file=sys.stderr,
    )
elif not SEMANTIC_SEARCH_ENABLED:
    print(
        "WARNING: Semantic search disabled by SEMANTIC_SEARCH_ENABLED=0",
        file=sys.stderr,
    )

SCHEDULER_AVAILABLE = importlib.util.find_spec("apscheduler") is not None
if not SCHEDULER_AVAILABLE:
    print(
        "WARNING: Scheduler not available. Install: pip install apscheduler",
        file=sys.stderr,
    )

CONCEPT_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "en_core_web_sm"
# Same two files scripts/bundle-concept-model.py verifies after extraction, so a
# partial install cannot report ready here and then fail on the first build.
CONCEPT_MODEL_AVAILABLE = all(
    (CONCEPT_MODEL_PATH / required).is_file()
    for required in ("config.cfg", "ner/model")
)
CONCEPTS_AVAILABLE = (
    importlib.util.find_spec("spacy") is not None and CONCEPT_MODEL_AVAILABLE
)
if not CONCEPTS_AVAILABLE:
    # stderr, not stdout -- STDIO transport's stdout must stay JSON-RPC clean
    # (see core/memory_utils.py's _safe_print), and this module is imported
    # on every server start including the STDIO entrypoint.
    print(
        "WARNING: Concept graph extraction not available. Reinstall: "
        "python -m pip install -U --force-reinstall marm-mcp-server",
        file=sys.stderr,
    )


def get_marm_db_path() -> str:
    """Get the official MARM database path, respecting environment variable if set"""
    env_db_path = os.environ.get("MARM_DB_PATH")
    if env_db_path:
        db_dir = Path(env_db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        return env_db_path

    marm_dir = Path.home() / ".marm"

    marm_dir.mkdir(exist_ok=True)

    return str(marm_dir / "marm_memory.db")


DEFAULT_DB_PATH = get_marm_db_path()
MAX_DB_CONNECTIONS = 5


def get_analytics_db_path() -> str:
    """Get the analytics database path, respecting environment variable if set"""
    env_analytics_db_path = os.environ.get("MARM_ANALYTICS_DB_PATH")
    if env_analytics_db_path:
        analytics_dir = os.path.dirname(env_analytics_db_path)
        if analytics_dir:
            os.makedirs(analytics_dir, exist_ok=True)
        return env_analytics_db_path

    if os.path.exists("/app/data"):
        return "/app/data/marm_usage_analytics.db"

    # ~/.marm, matching get_marm_db_path above. A bare relative name resolved
    # against whatever directory the server was started from, so the file
    # followed the launch location instead of the install and landed in the
    # user's repo often enough to earn a .gitignore entry.
    marm_dir = Path.home() / ".marm"
    marm_dir.mkdir(exist_ok=True)
    return str(marm_dir / "marm_usage_analytics.db")


ANALYTICS_DB_PATH = get_analytics_db_path()

DEFAULT_SEMANTIC_MODEL = "jinaai/jina-embeddings-v2-small-en"
DEFAULT_SEMANTIC_DIM = 512

SERVER_HOST = os.environ.get("SERVER_HOST", "127.0.0.1")
_raw_port = _safe_int("SERVER_PORT", 8001)
SERVER_PORT = max(1, min(65535, _raw_port))
if not (1 <= _raw_port <= 65535):
    print(
        f"WARNING: SERVER_PORT={_raw_port} out of [1, 65535], clamped to {SERVER_PORT}",
        file=sys.stderr,
    )
SERVER_VERSION = "2.43.0"

GRAPH_ENABLED = os.environ.get("GRAPH_ENABLED", "true").lower() != "false"


def _detect_project() -> str:
    explicit = os.environ.get("MARM_PROJECT", "")
    if explicit:
        return explicit.lower().replace(" ", "-")
    cwd = Path.cwd()
    unsafe = {Path.home(), Path.home().parent, Path("/")}
    if sys.platform == "win32":
        unsafe.add(Path("C:\\"))
    if cwd in unsafe:
        return ""
    return cwd.name.lower().replace(" ", "-")


MARM_PROJECT = _detect_project()


def _detect_platform() -> str:
    explicit = os.environ.get("MARM_PLATFORM", "")
    if explicit:
        return explicit.lower()
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude-code"
    term = os.environ.get("TERM_PROGRAM", "").lower()
    if term in ("vscode", "cursor", "windsurf"):
        return term
    if os.environ.get("VSCODE_PID"):
        return "vscode"
    if os.environ.get("CURSOR_TRACE_ID"):
        return "cursor"
    return ""


MARM_PLATFORM = _detect_platform()

_raw_rpm = _safe_int("MARM_RATE_LIMIT_RPM", 80)
# 0 = disable rate limiting; negative values clamped to 0
MARM_RATE_LIMIT_RPM = max(0, _raw_rpm)
if _raw_rpm < 0:
    print(
        f"WARNING: MARM_RATE_LIMIT_RPM={_raw_rpm} below minimum 0, clamped to {MARM_RATE_LIMIT_RPM}",
        file=sys.stderr,
    )

_raw_rls = _safe_int("RATE_LIMIT_WINDOW_SECONDS", 60)
RATE_LIMIT_WINDOW_SECONDS = max(1, _raw_rls)
if _raw_rls < 1:
    print(
        f"WARNING: RATE_LIMIT_WINDOW_SECONDS={_raw_rls} below minimum 1, clamped to {RATE_LIMIT_WINDOW_SECONDS}",
        file=sys.stderr,
    )

_raw_rbs = _safe_int("RATE_LIMIT_BLOCK_SECONDS", 30)
RATE_LIMIT_BLOCK_SECONDS = max(0, _raw_rbs)
if _raw_rbs < 0:
    print(
        f"WARNING: RATE_LIMIT_BLOCK_SECONDS={_raw_rbs} below minimum 0, clamped to {RATE_LIMIT_BLOCK_SECONDS}",
        file=sys.stderr,
    )

WRITE_QUEUE_ENABLED = os.environ.get("WRITE_QUEUE_ENABLED", "1") == "1"

_raw_mqs = _safe_int("MAX_QUEUE_SIZE", 100)
MAX_QUEUE_SIZE = max(1, _raw_mqs)
if _raw_mqs < 1:
    print(
        f"WARNING: MAX_QUEUE_SIZE={_raw_mqs} below minimum 1, clamped to {MAX_QUEUE_SIZE}",
        file=sys.stderr,
    )

# Shutdown waits this long for in-flight chunk encodes. A memory maxes out at 7
# chunks (10,000-char content cap), which encodes in about 1s, so the default
# leaves room for several concurrent writes. Anything still pending is recovered
# by `marm-mcp-server --rechunk`, so the wait is allowed to expire.
_raw_cdt = _safe_int("CHUNK_DRAIN_TIMEOUT_SECONDS", 5)
CHUNK_DRAIN_TIMEOUT_SECONDS = max(0, _raw_cdt)
if _raw_cdt < 0:
    print(
        f"WARNING: CHUNK_DRAIN_TIMEOUT_SECONDS={_raw_cdt} below minimum 0, clamped to {CHUNK_DRAIN_TIMEOUT_SECONDS}",
        file=sys.stderr,
    )

_raw_rsl = _safe_int("RECALL_SCAN_LIMIT", 10000)
RECALL_SCAN_LIMIT = max(1, _raw_rsl)
if _raw_rsl < 1:
    print(
        f"WARNING: RECALL_SCAN_LIMIT={_raw_rsl} below minimum 1, clamped to {RECALL_SCAN_LIMIT}",
        file=sys.stderr,
    )

# Page size for concept builds, not a truncation limit. Lowering it makes a
# build read more, smaller pages; it no longer makes the build skip rows.
_raw_cbc = _safe_int("CONCEPT_BUILD_ROW_CAP", 500)
CONCEPT_BUILD_ROW_CAP = max(1, _raw_cbc)
if _raw_cbc < 1:
    print(
        f"WARNING: CONCEPT_BUILD_ROW_CAP={_raw_cbc} below minimum 1, clamped to {CONCEPT_BUILD_ROW_CAP}",
        file=sys.stderr,
    )

CONCEPT_AUTO_INDEX = _safe_bool("CONCEPT_AUTO_INDEX", True)

# Quiet period after the most recent write before the worker starts draining.
# An agent storing a burst of memories produces one drain, not one per write.
_raw_cids = _safe_int("CONCEPT_INDEX_DEBOUNCE_SECONDS", 30)
CONCEPT_INDEX_DEBOUNCE_SECONDS = max(1, _raw_cids)
if _raw_cids < 1:
    print(
        f"WARNING: CONCEPT_INDEX_DEBOUNCE_SECONDS={_raw_cids} below minimum 1, "
        f"clamped to {CONCEPT_INDEX_DEBOUNCE_SECONDS}",
        file=sys.stderr,
    )

# Upper bound as well as lower: a claimed batch becomes one IN (...) clause in
# three queries, and a batch past SQLite's variable ceiling would fail the same
# way on every cycle forever. 500 memories of spaCy extraction per batch is
# already far beyond anything useful.
CONCEPT_INDEX_BATCH_SIZE_MAX = 500
_raw_cibs = _safe_int("CONCEPT_INDEX_BATCH_SIZE", 20)
CONCEPT_INDEX_BATCH_SIZE = max(1, min(CONCEPT_INDEX_BATCH_SIZE_MAX, _raw_cibs))
if not (1 <= _raw_cibs <= CONCEPT_INDEX_BATCH_SIZE_MAX):
    print(
        f"WARNING: CONCEPT_INDEX_BATCH_SIZE={_raw_cibs} out of "
        f"[1, {CONCEPT_INDEX_BATCH_SIZE_MAX}], clamped to {CONCEPT_INDEX_BATCH_SIZE}",
        file=sys.stderr,
    )

# Pause between batches while draining a backlog. Extraction is CPU-bound and
# competes with recall for cores, so a worker at full throttle measurably slows
# interactive work; this trades drain duration for that latency. 0 disables it.
_raw_cibp = _safe_int("CONCEPT_INDEX_BATCH_PAUSE_MS", 250)
CONCEPT_INDEX_BATCH_PAUSE_MS = max(0, min(10_000, _raw_cibp))
if not (0 <= _raw_cibp <= 10_000):
    print(
        f"WARNING: CONCEPT_INDEX_BATCH_PAUSE_MS={_raw_cibp} out of [0, 10000], "
        f"clamped to {CONCEPT_INDEX_BATCH_PAUSE_MS}",
        file=sys.stderr,
    )

# How long a claimed task stays owned. A process killed mid-extraction leaves
# its tasks claimable again after this, without burning an attempt.
_raw_cils = _safe_int("CONCEPT_INDEX_LEASE_SECONDS", 300)
CONCEPT_INDEX_LEASE_SECONDS = max(1, _raw_cils)
if _raw_cils < 1:
    print(
        f"WARNING: CONCEPT_INDEX_LEASE_SECONDS={_raw_cils} below minimum 1, "
        f"clamped to {CONCEPT_INDEX_LEASE_SECONDS}",
        file=sys.stderr,
    )

_raw_cima = _safe_int("CONCEPT_INDEX_MAX_ATTEMPTS", 3)
CONCEPT_INDEX_MAX_ATTEMPTS = max(1, _raw_cima)
if _raw_cima < 1:
    print(
        f"WARNING: CONCEPT_INDEX_MAX_ATTEMPTS={_raw_cima} below minimum 1, "
        f"clamped to {CONCEPT_INDEX_MAX_ATTEMPTS}",
        file=sys.stderr,
    )

# ── Code graph auto-indexing ───────────────────────────────────────
# A saved override in runtime_flags beats this; see core/runtime_flags.py.
GRAPH_AUTO_INDEX = _safe_bool("GRAPH_AUTO_INDEX", True)

# Git-signature cycle. 30s rather than the engine's own 5s base: a git signature
# costs ~100ms per project on Windows, where process spawn dominates, and a code
# graph does not need sub-minute freshness.
_raw_gaii = _safe_int("GRAPH_AUTO_INDEX_INTERVAL", 30)
GRAPH_AUTO_INDEX_INTERVAL = max(5, _raw_gaii)
if _raw_gaii < 5:
    print(
        f"WARNING: GRAPH_AUTO_INDEX_INTERVAL={_raw_gaii} below minimum 5, "
        f"clamped to {GRAPH_AUTO_INDEX_INTERVAL}",
        file=sys.stderr,
    )

# Non-git projects have no cheap signature, so their only option is an
# unconditional re-index. That holds the engine lock, so it gets a slow lane.
_raw_gaifi = _safe_int("GRAPH_AUTO_INDEX_FULL_INTERVAL", 300)
GRAPH_AUTO_INDEX_FULL_INTERVAL = max(60, _raw_gaifi)
if _raw_gaifi < 60:
    print(
        f"WARNING: GRAPH_AUTO_INDEX_FULL_INTERVAL={_raw_gaifi} below minimum 60, "
        f"clamped to {GRAPH_AUTO_INDEX_FULL_INTERVAL}",
        file=sys.stderr,
    )

# Validated here, not at use: an unrecognized mode fails GraphIndexRequest's
# Literal deep inside the poll cycle, which logs a project failure every cycle
# forever and never indexes anything.
GRAPH_AUTO_INDEX_MODE = _safe_choice(
    "GRAPH_AUTO_INDEX_MODE", "moderate", ("full", "moderate", "fast")
)

# Heartbeat-renewed, so this bounds a crashed holder rather than a long index.
# Kept short because a dead event loop leaves the lease to expire on its own.
_raw_gails = _safe_int("GRAPH_AUTO_INDEX_LEASE_SECONDS", 120)
GRAPH_AUTO_INDEX_LEASE_SECONDS = max(1, _raw_gails)
if _raw_gails < 1:
    print(
        f"WARNING: GRAPH_AUTO_INDEX_LEASE_SECONDS={_raw_gails} below minimum 1, "
        f"clamped to {GRAPH_AUTO_INDEX_LEASE_SECONDS}",
        file=sys.stderr,
    )

# list_projects costs ~265ms and holds the engine lock, so the watch set is
# cached rather than refreshed every cycle.
_raw_gaipt = _safe_int("GRAPH_AUTO_INDEX_PROJECT_TTL", 300)
GRAPH_AUTO_INDEX_PROJECT_TTL = max(10, _raw_gaipt)
if _raw_gaipt < 10:
    print(
        f"WARNING: GRAPH_AUTO_INDEX_PROJECT_TTL={_raw_gaipt} below minimum 10, "
        f"clamped to {GRAPH_AUTO_INDEX_PROJECT_TTL}",
        file=sys.stderr,
    )

# Starting point to tune from real usage, not a validated-forever constant --
# fastembed's model is tuned for sentence-length input; behavior on single-
# word/short-phrase entity names is less validated than on the full-memory-
# content strings this encoder already handles elsewhere. Same band as this
# codebase's two existing analogous "is this basically the same thing"
# embedding thresholds (CONSOLIDATION_THRESHOLD=0.92, COMPACTION_SIMILARITY_
# THRESHOLD=0.88).
_raw_cdst = _safe_float("CONCEPT_DUPLICATE_SIMILARITY_THRESHOLD", 0.90)
CONCEPT_DUPLICATE_SIMILARITY_THRESHOLD = max(0.0, min(1.0, _raw_cdst))
if not (0.0 <= _raw_cdst <= 1.0):
    print(
        f"WARNING: CONCEPT_DUPLICATE_SIMILARITY_THRESHOLD={_raw_cdst} out of [0, 1], "
        f"clamped to {CONCEPT_DUPLICATE_SIMILARITY_THRESHOLD}",
        file=sys.stderr,
    )

# 0.05 is swept, not guessed -- do not "restore" it to the old 0.35.
# Until v2.31.0 widened candidate generation this weight never applied to
# natural-language recall, so it had never been validated. Swept in v2.32.0 over
# 0.00-0.50 on LoCoMo (1,977 questions, 5,882 memories, deterministic pool):
# any-hit peaks in a broad 0.04-0.08 plateau at 62.0-62.5%, against 57.4% at 0.0
# and 57.6% at the old 0.35. High weights collapse single-hop accuracy (56.9% at
# 0.05 -> 47.3% at 0.35). 0.05 is the plateau centre rather than the argmax, so
# the default is not fitted to one corpus.
_raw_hsw = _safe_float("HYBRID_SEARCH_TEXT_WEIGHT", 0.05)
_raw_tw = _safe_float("TEMPORAL_WEIGHT", 0.1)
_raw_hld = _safe_float("TEMPORAL_HALF_LIFE_DAYS", 30)
HYBRID_SEARCH_TEXT_WEIGHT = max(0.0, min(1.0, _raw_hsw))
TEMPORAL_WEIGHT = max(0.0, min(1.0, _raw_tw))
TEMPORAL_HALF_LIFE_DAYS = max(1.0, _raw_hld)
if not (0.0 <= _raw_hsw <= 1.0):
    print(
        f"WARNING: HYBRID_SEARCH_TEXT_WEIGHT={_raw_hsw} out of [0, 1], clamped to {HYBRID_SEARCH_TEXT_WEIGHT}",
        file=sys.stderr,
    )
if not (0.0 <= _raw_tw <= 1.0):
    print(
        f"WARNING: TEMPORAL_WEIGHT={_raw_tw} out of [0, 1], clamped to {TEMPORAL_WEIGHT}",
        file=sys.stderr,
    )
if _raw_hld < 1.0:
    print(
        f"WARNING: TEMPORAL_HALF_LIFE_DAYS={_raw_hld} below minimum 1.0, clamped to {TEMPORAL_HALF_LIFE_DAYS}",
        file=sys.stderr,
    )

# Raised 50 -> 200 in v2.32.0. v2.31.0 made this knob load-bearing for the first
# time (99.4% of LoCoMo queries saturated the old 50) and its cost was a 5.6pp
# multi-hop regression, since a keyword-filtered pool can drop a required memory
# that shares no wording with the question. Swept over 50/100/200/500: 200
# recovers multi-hop to 39.3% (from 34.8% at 50, matching the pre-v2.31.0
# baseline) and lifts single-hop 1.1pp with adversarial precision unchanged, for
# roughly 3ms more per recall. 500 buys another 1.1pp of multi-hop but starts
# giving back the adversarial gain, because a pool that large stops acting as a
# precision gate.
_raw_fcl = _safe_int("FTS_CANDIDATE_LIMIT", 200)
FTS_CANDIDATE_LIMIT = max(1, _raw_fcl)
if _raw_fcl < 1:
    print(
        f"WARNING: FTS_CANDIDATE_LIMIT={_raw_fcl} below minimum 1, clamped to {FTS_CANDIDATE_LIMIT}",
        file=sys.stderr,
    )

# How the semantic lane builds its FTS5 MATCH string. The exact/lexical lane is
# unaffected and always uses strict AND.
#   or_nostop : drop stopwords, then OR the rest (default)
#   or        : OR every token, stopwords included
#   and       : strict AND, the pre-v2.31.0 behavior
FTS_QUERY_MODES = ("or_nostop", "or", "and")
FTS_QUERY_MODE = _safe_choice("FTS_QUERY_MODE", "or_nostop", FTS_QUERY_MODES)

# Extra stopwords appended to the built-in English list used by or_nostop.
# Additive only -- it cannot remove built-ins. Comma-separated, case-insensitive.
FTS_EXTRA_STOPWORDS = _csv_frozenset("FTS_EXTRA_STOPWORDS")

# Lexical score given to a degenerate candidate set (one row, or every row tied on
# BM25), where per-query min-max has no spread to normalize against. Applies to
# both lanes that match on a wide OR: the semantic lane, and since v2.33.0 the
# semantic-fallback lane. The exact lane always uses 1.0, because its strict AND
# means a lone hit contained every query term.
#
# Stays at 1.0: swept over 0.0/0.3/0.5/1.0 in v2.32.0 with no measurable effect,
# because on a corpus of any size the wide OR fills the candidate pool. An offline
# diagnostic found one degenerate set across 1,982 FTS calls (a call count, not the
# benchmark's 1,977 scored questions); 1,964 of those calls saturated the pool.
# Exposed for small stores, where a query matching a single memory is common and
# awarding it a perfect lexical score may not be wanted.
FTS_LONE_HIT_SCORE = _safe_unit_float("FTS_LONE_HIT_SCORE", 1.0)

CONSOLIDATION_ENABLED = os.environ.get("CONSOLIDATION_ENABLED", "0") == "1"
_raw_ct = _safe_float("CONSOLIDATION_THRESHOLD", 0.92)
CONSOLIDATION_THRESHOLD = max(0.0, min(1.0, _raw_ct))
if not (0.0 <= _raw_ct <= 1.0):
    print(
        f"WARNING: CONSOLIDATION_THRESHOLD={_raw_ct} out of [0, 1], clamped to {CONSOLIDATION_THRESHOLD}",
        file=sys.stderr,
    )

COMPACTION_ENABLED = os.environ.get("COMPACTION_ENABLED", "0") == "1"
_raw_cst = _safe_float("COMPACTION_SIMILARITY_THRESHOLD", 0.88)
COMPACTION_SIMILARITY_THRESHOLD = max(0.0, min(1.0, _raw_cst))
if not (0.0 <= _raw_cst <= 1.0):
    print(
        f"WARNING: COMPACTION_SIMILARITY_THRESHOLD={_raw_cst} out of [0, 1], clamped to {COMPACTION_SIMILARITY_THRESHOLD}",
        file=sys.stderr,
    )

_raw_ctc = _safe_int("COMPACTION_TRIGGER_COUNT", 5)
COMPACTION_TRIGGER_COUNT = max(1, _raw_ctc)
if _raw_ctc < 1:
    print(
        f"WARNING: COMPACTION_TRIGGER_COUNT={_raw_ctc} below minimum 1, clamped to {COMPACTION_TRIGGER_COUNT}",
        file=sys.stderr,
    )

_raw_cmcs = _safe_int("COMPACTION_MIN_CLUSTER_SIZE", 3)
COMPACTION_MIN_CLUSTER_SIZE = max(1, _raw_cmcs)
if _raw_cmcs < 1:
    print(
        f"WARNING: COMPACTION_MIN_CLUSTER_SIZE={_raw_cmcs} below minimum 1, clamped to {COMPACTION_MIN_CLUSTER_SIZE}",
        file=sys.stderr,
    )

_raw_cmah = _safe_int("COMPACTION_MIN_AGE_HOURS", 24)
COMPACTION_MIN_AGE_HOURS = max(0, _raw_cmah)
if _raw_cmah < 0:
    print(
        f"WARNING: COMPACTION_MIN_AGE_HOURS={_raw_cmah} below minimum 0, clamped to {COMPACTION_MIN_AGE_HOURS}",
        file=sys.stderr,
    )

_raw_casm = _safe_int("COMPACTION_ACTIVE_SESSION_GRACE_MINUTES", 15)
COMPACTION_ACTIVE_SESSION_GRACE_MINUTES = max(0, _raw_casm)
if _raw_casm < 0:
    print(
        f"WARNING: COMPACTION_ACTIVE_SESSION_GRACE_MINUTES={_raw_casm} below minimum 0, clamped to {COMPACTION_ACTIVE_SESSION_GRACE_MINUTES}",
        file=sys.stderr,
    )

_raw_csttl = _safe_int("COMPACTION_STAGING_TTL_HOURS", 168)
COMPACTION_STAGING_TTL_HOURS = max(1, _raw_csttl)
if _raw_csttl < 1:
    print(
        f"WARNING: COMPACTION_STAGING_TTL_HOURS={_raw_csttl} below minimum 1, clamped to {COMPACTION_STAGING_TTL_HOURS}",
        file=sys.stderr,
    )

COMPACTION_AUTO_APPLY_ENABLED = (
    os.environ.get("COMPACTION_AUTO_APPLY_ENABLED", "0") == "1"
)

_raw_caai = _safe_int("COMPACTION_AUTO_APPLY_INTERVAL_MINUTES", 60)
COMPACTION_AUTO_APPLY_INTERVAL_MINUTES = max(1, _raw_caai)
if _raw_caai < 1:
    print(
        f"WARNING: COMPACTION_AUTO_APPLY_INTERVAL_MINUTES={_raw_caai} below minimum 1, clamped to {COMPACTION_AUTO_APPLY_INTERVAL_MINUTES}",
        file=sys.stderr,
    )

_raw_cmn = _safe_int("COMPACTION_MAX_NUDGES", 5)
COMPACTION_MAX_NUDGES = max(1, _raw_cmn)
if _raw_cmn < 1:
    print(
        f"WARNING: COMPACTION_MAX_NUDGES={_raw_cmn} below minimum 1, clamped to {COMPACTION_MAX_NUDGES}",
        file=sys.stderr,
    )

_raw_cncs = _safe_int("COMPACTION_NUDGE_COOLDOWN_SECONDS", 2)
COMPACTION_NUDGE_COOLDOWN_SECONDS = max(0, _raw_cncs)
if _raw_cncs < 0:
    print(
        f"WARNING: COMPACTION_NUDGE_COOLDOWN_SECONDS={_raw_cncs} below minimum 0, clamped to {COMPACTION_NUDGE_COOLDOWN_SECONDS}",
        file=sys.stderr,
    )

_raw_cibb = _safe_int("COMPACTION_INJECTION_BYTE_BUDGET", 2048)
COMPACTION_INJECTION_BYTE_BUDGET = max(0, _raw_cibb)
if _raw_cibb < 0:
    print(
        f"WARNING: COMPACTION_INJECTION_BYTE_BUDGET={_raw_cibb} below minimum 0, clamped to {COMPACTION_INJECTION_BYTE_BUDGET}",
        file=sys.stderr,
    )

MARM_API_KEY = resolve_marm_api_key(SERVER_HOST)
