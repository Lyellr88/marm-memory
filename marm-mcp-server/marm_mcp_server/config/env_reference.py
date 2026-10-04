from dataclasses import dataclass


@dataclass(frozen=True)
class EnvVar:
    name: str
    group: str
    default: str
    description: str


ENV_REFERENCE: tuple[EnvVar, ...] = (
    EnvVar(
        "MARM_PROJECT",
        "Server",
        "",
        "Project name for new memories. Defaults to the current folder name.",
    ),
    EnvVar(
        "MARM_PLATFORM",
        "Server",
        "",
        "Agent name recorded with memories. Detected from the environment when empty.",
    ),
    EnvVar(
        "MARM_RATE_LIMIT_RPM",
        "Rate limit",
        "80",
        "HTTP requests per minute per address. 0 disables the limit.",
    ),
    EnvVar(
        "RATE_LIMIT_WINDOW_SECONDS",
        "Rate limit",
        "60",
        "Length of the rate-limit window.",
    ),
    EnvVar(
        "RATE_LIMIT_BLOCK_SECONDS",
        "Rate limit",
        "30",
        "How long an address stays blocked after passing the limit.",
    ),
    EnvVar(
        "WRITE_QUEUE_ENABLED",
        "Write queue",
        "1",
        "Serialize memory writes through a queue. 1 is on, 0 is off.",
    ),
    EnvVar(
        "MAX_QUEUE_SIZE",
        "Write queue",
        "100",
        "Most writes the queue holds before refusing new ones.",
    ),
    EnvVar(
        "CONCEPT_AUTO_INDEX",
        "Concept index",
        "true",
        "Extract concepts from new memories automatically.",
    ),
    EnvVar(
        "CONCEPT_INDEX_DEBOUNCE_SECONDS",
        "Concept index",
        "30",
        "Quiet time after a write before concepts are extracted.",
    ),
    EnvVar(
        "CONCEPT_INDEX_BATCH_SIZE",
        "Concept index",
        "20",
        "Memories processed per concept extraction pass (1 to 500).",
    ),
    EnvVar(
        "GRAPH_AUTO_INDEX",
        "Code graph",
        "true",
        "Re-index changed projects automatically.",
    ),
    EnvVar(
        "GRAPH_AUTO_INDEX_DEBOUNCE_SECONDS",
        "Code graph",
        "2.0",
        "Quiet time after a file change before re-indexing (minimum 0.5).",
    ),
    EnvVar(
        "GRAPH_AUTO_INDEX_RECONCILE_SECONDS",
        "Code graph",
        "300",
        "How often indexed projects are checked for drift (minimum 60).",
    ),
    EnvVar(
        "CONSOLIDATION_THRESHOLD",
        "Memory",
        "0.92",
        "Similarity at or above which a new memory counts as a duplicate.",
    ),
    EnvVar(
        "COMPACTION_SIMILARITY_THRESHOLD",
        "Memory",
        "0.88",
        "Similarity needed for memories to be compaction candidates.",
    ),
    EnvVar(
        "COMPACTION_TRIGGER_COUNT",
        "Memory",
        "5",
        "New memories in a session before compaction is suggested. The profile can change the default.",
    ),
    EnvVar(
        "COMPACTION_MIN_CLUSTER_SIZE",
        "Memory",
        "3",
        "Fewest memories in a compaction cluster.",
    ),
    EnvVar(
        "COMPACTION_STAGING_TTL_HOURS",
        "Memory",
        "168",
        "How long a staged compaction is kept before it expires.",
    ),
    EnvVar(
        "COMPACTION_AUTO_APPLY_INTERVAL_MINUTES",
        "Memory",
        "60",
        "How often automatic compaction runs.",
    ),
    EnvVar(
        "MARM_DISTILL_MAX_NUDGES",
        "Distill",
        "3",
        "Most reminders to save learnings per session.",
    ),
    EnvVar(
        "MARM_DISTILL_NUDGE_COOLDOWN",
        "Distill",
        "900",
        "Seconds between distill reminders.",
    ),
    EnvVar(
        "MARM_DISTILL_INPUT_CHARS",
        "Distill",
        "48000",
        "Most characters of a session sent to the local model when distilling.",
    ),
    EnvVar(
        "MARM_LLM_ENABLED",
        "Local model",
        "false",
        "Use the local model. A Console switch overrides this.",
    ),
    EnvVar(
        "MARM_LLM_URL",
        "Local model",
        "http://127.0.0.1:18080",
        "Address of the local model server.",
    ),
    EnvVar(
        "MARM_LLM_MODEL_ROOTS",
        "Local model",
        "",
        "Extra folders searched for model files, separated by the OS path separator.",
    ),
    EnvVar(
        "MARM_CODE_CONTEXT_DETAIL",
        "Code graph",
        "1",
        "Detail level of code context results, 1 to 3.",
    ),
    EnvVar(
        "MARM_DB_PATH", "Storage", "~/.marm/marm_memory.db", "Memory database file."
    ),
    EnvVar(
        "MARM_CONCEPT_DB_PATH",
        "Storage",
        "~/.marm/index/marm_index.db",
        "Concept graph database file.",
    ),
    EnvVar(
        "MARM_ANALYTICS_DB_PATH",
        "Storage",
        "~/.marm/marm_usage_analytics.db",
        "Usage analytics database file.",
    ),
    EnvVar(
        "MARM_STDIO_LOG_DIR", "Storage", "~/.marm/logs", "Folder for STDIO server logs."
    ),
    EnvVar(
        "MARM_CONSOLE_HOST",
        "Console",
        "127.0.0.1",
        "Address the Console binds to.",
    ),
    EnvVar("MARM_CONSOLE_PORT", "Console", "8002", "Port the Console listens on."),
    EnvVar(
        "MARM_MCP_URL",
        "Console",
        "",
        "Address the Console uses to reach the runtime. Defaults to the running runtime.",
    ),
    EnvVar(
        "MARM_DOCKER_REPOSITORY",
        "Docker",
        "lyellr88/marm-mcp-server",
        "Image repository used by Docker commands.",
    ),
    EnvVar(
        "FTS_QUERY_MODE",
        "Search",
        "or_nostop",
        "How keyword search combines words: or_nostop, or, or and.",
    ),
    EnvVar(
        "HYBRID_SEARCH_TEXT_WEIGHT",
        "Search",
        "0.05",
        "Weight of keyword matches when blended with semantic search.",
    ),
    EnvVar(
        "TEMPORAL_HALF_LIFE_DAYS",
        "Search",
        "30",
        "Days for the recency boost on a memory to halve.",
    ),
)
