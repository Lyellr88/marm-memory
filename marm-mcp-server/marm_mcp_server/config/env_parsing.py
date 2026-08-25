import os
import sys


def _safe_int(env_key: str, default: int) -> int:
    """Parse an env var as int, falling back to default on malformed input."""
    raw = os.environ.get(env_key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        print(
            f"WARNING: {env_key}={raw!r} is not a valid integer, using default {default}",
            file=sys.stderr,
        )
        return default


def _safe_float(env_key: str, default: float) -> float:
    """Parse an env var as float, falling back to default on malformed input."""
    raw = os.environ.get(env_key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        print(
            f"WARNING: {env_key}={raw!r} is not a valid number, using default {default}",
            file=sys.stderr,
        )
        return default


def _safe_unit_float(env_key: str, default: float) -> float:
    """Parse an env var as a float clamped to [0, 1], warning when it was out of range.

    Several settings are weights or similarity scores that only mean anything
    inside the unit interval; this keeps the parse, the clamp, and the warning in
    one tested place instead of re-deriving them per setting.
    """
    raw = _safe_float(env_key, default)
    clamped = max(0.0, min(1.0, raw))
    if raw != clamped:
        print(
            f"WARNING: {env_key}={raw} out of [0, 1], clamped to {clamped}",
            file=sys.stderr,
        )
    return clamped


_TRUE_WORDS = ("1", "true", "yes", "on")
_FALSE_WORDS = ("0", "false", "no", "off")


def _safe_bool(env_key: str, default: bool) -> bool:
    """Read an on/off env var, accepting the spellings people actually type.

    Comparing against a single literal is what makes a flag lie: a check for
    != "0" reads CONCEPT_AUTO_INDEX=false as on, which is the opposite of what
    the user asked for and of what the docs promise.
    """
    raw = os.environ.get(env_key)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_WORDS:
        return True
    if value in _FALSE_WORDS:
        return False
    print(
        f"WARNING: {env_key}={raw!r} is not a true/false value, "
        f"using default {default}",
        file=sys.stderr,
    )
    return default


def _safe_choice(env_key: str, default: str, allowed: tuple[str, ...]) -> str:
    """Read an env var constrained to a fixed set, falling back on anything else."""
    raw = os.environ.get(env_key)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in allowed:
        return value
    print(
        f"WARNING: {env_key}={raw!r} is not one of {', '.join(allowed)}, "
        f"using default {default!r}",
        file=sys.stderr,
    )
    return default


def _csv_frozenset(env_key: str) -> frozenset[str]:
    """Parse a comma-separated env var into a lowercased set, dropping blanks."""
    raw = os.environ.get(env_key, "")
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())
