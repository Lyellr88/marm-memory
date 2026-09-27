"""Remove credentials from text before it is stored.

Memory is recalled into every agent that shares this server, so a secret
written once is handed back to all of them. Patterns favour precision: text
that merely talks about a key by name must pass through unchanged.
"""

import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Order matters where prefixes overlap: `sk-ant-` before the generic `sk-`.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "private-key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?"
            r"(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
            re.DOTALL,
        ),
    ),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "github-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})"),
    ),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}")),
    ("slack-token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("stripe-key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{16,}")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ),
    ("bearer-token", re.compile(r"(?i)(?<=bearer )[A-Za-z0-9._~+/-]{20,}=*")),
]

# `NAME=value` where NAME ends in a secret word; the name stays, the value
# goes. Templates (`${VAR}`, `<placeholder>`), numbers and booleans are not
# values, and a value must look like a credential rather than a word: it has a
# digit or symbol, or is long. "session token: invalidated" stays prose.
_SECRET_NAME = (
    r"API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY|SECRET|TOKEN|PASSWORD|PASSWD"
    r"|CREDENTIALS?"
)
_ASSIGNED = re.compile(
    rf"(?i)(\b[A-Z0-9_]*(?:{_SECRET_NAME})\s*[:=]\s*[\"']?)"
    r"(?![$<{%])(?!(?:\d+|true|false|null|none|yes|no)\b)"
    r"(?=[^\s\"'`]*[\d/+=._-]|[^\s\"'`]{16,})"
    r"([^\s\"'`]{6,})"
)


def redact_secrets(text: str) -> tuple[str, dict[str, int]]:
    """Return `text` with credentials replaced, and how many of each kind."""
    if not text:
        return text, {}
    counts: dict[str, int] = {}
    for kind, pattern in _PATTERNS:
        text, n = pattern.subn(f"[redacted:{kind}]", text)
        if n:
            counts[kind] = n
    text, n = _ASSIGNED.subn(r"\1[redacted:assigned-secret]", text)
    if n:
        counts["assigned-secret"] = n
    if counts:
        logger.warning("memory.secrets_redacted", kinds=counts)
    return text, counts


def redact_value(value: Any) -> Any:
    """Redact every string inside a JSON-shaped value."""
    if isinstance(value, str):
        return redact_secrets(value)[0]
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value
