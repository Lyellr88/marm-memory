from dataclasses import dataclass

KEY_ENV = "MARM_API_KEY"


@dataclass(frozen=True)
class Setting:
    key: str
    env: str
    type: str
    encoding: str
    group: str
    label: str
    help: str
    default: bool | int | str
    choices: tuple[str, ...] | None = None
    min: int | None = None
    max: int | None = None


SETTINGS: tuple[Setting, ...] = (
    Setting(
        "server.port",
        "SERVER_PORT",
        "int",
        "plain",
        "server",
        "Port",
        "Port the MARM server listens on.",
        8001,
        min=1,
        max=65535,
    ),
    Setting(
        "server.expose_network",
        "SERVER_HOST",
        "bool",
        "host",
        "server",
        "Expose to the network",
        "Listen on every interface instead of this computer only. Requires a key.",
        False,
    ),
    Setting(
        "auth.require_key",
        KEY_ENV,
        "bool",
        "key",
        "security",
        "Require a key",
        "Clients must send the MARM key. A key is created for you if none exists.",
        False,
    ),
    Setting(
        "search.semantic",
        "SEMANTIC_SEARCH_ENABLED",
        "bool",
        "01",
        "search",
        "Semantic search",
        "Find memories by meaning, using the local embedding model.",
        True,
    ),
    Setting(
        "graph.enabled",
        "GRAPH_ENABLED",
        "bool",
        "truefalse",
        "graph",
        "Code graph",
        "Build and serve the code graph for indexed projects.",
        True,
    ),
    Setting(
        "graph.auto_index_mode",
        "GRAPH_AUTO_INDEX_MODE",
        "choice",
        "plain",
        "graph",
        "Auto-index depth",
        "How thorough automatic code indexing is.",
        "moderate",
        choices=("full", "moderate", "fast"),
    ),
    Setting(
        "compaction.enabled",
        "COMPACTION_ENABLED",
        "bool",
        "01",
        "memory",
        "Compaction",
        "Find old memories that can be merged.",
        False,
    ),
    Setting(
        "compaction.auto_apply",
        "COMPACTION_AUTO_APPLY_ENABLED",
        "bool",
        "01",
        "memory",
        "Apply compaction automatically",
        "Merge compaction candidates without asking.",
        False,
    ),
    Setting(
        "compaction.min_age_hours",
        "COMPACTION_MIN_AGE_HOURS",
        "int",
        "plain",
        "memory",
        "Compaction minimum age (hours)",
        "Memories younger than this are never compacted.",
        24,
        min=0,
        max=8760,
    ),
    Setting(
        "consolidation.enabled",
        "CONSOLIDATION_ENABLED",
        "bool",
        "01",
        "memory",
        "Consolidation",
        "Merge near-duplicate memories when they are saved.",
        False,
    ),
    Setting(
        "distill.nudge",
        "MARM_DISTILL_NUDGE",
        "bool",
        "01",
        "memory",
        "Distill reminders",
        "Remind the agent to save what it learned.",
        True,
    ),
    Setting(
        "distill.ttl_hours",
        "MARM_DISTILL_TTL_HOURS",
        "int",
        "plain",
        "memory",
        "Distill lifetime (hours)",
        "How long a distill draft is kept.",
        168,
        min=1,
        max=8760,
    ),
    Setting(
        "llm.timeout_seconds",
        "MARM_LLM_TIMEOUT",
        "int",
        "plain",
        "llm",
        "Local model timeout (seconds)",
        "How long to wait for the local model.",
        120,
        min=1,
        max=3600,
    ),
    Setting(
        "logging.stdio_level",
        "MARM_STDIO_LOG_LEVEL",
        "choice",
        "plain",
        "logging",
        "STDIO log level",
        "How much the STDIO server writes to its log.",
        "INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    ),
)
