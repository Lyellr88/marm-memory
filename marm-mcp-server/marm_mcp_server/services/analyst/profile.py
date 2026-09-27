"""Operator-selected limits on one analysis.

A profile is chosen by the operator and never inferred from the model. The
task contract and the verifier are the same under every profile; what a
profile changes is how much evidence the model reads, how many tokens it may
spend, how long it may run, and whether its narrow operations share one call.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass, field, replace

import structlog

from ...config.env_parsing import _safe_float, _safe_int

logger = structlog.get_logger(__name__)

PROFILE_ENV = "MARM_ANALYST_PROFILE"
DEFAULT_PROFILE = "general"

#: Ceilings a setting may raise a limit to, not defaults. Reasoning tokens are
#: not reported the same way by every local server, so the requested token cap
#: and wall time are what is enforced. Thinking models are documented to need
#: up to 32768 tokens, so a lower ceiling would rule them out rather than
#: bound them.
MAX_OUTPUT_TOKENS = 8192
MAX_REASONING_TOKENS = 32768
MIN_TIME_S, MAX_TIME_S = 5.0, 600.0


@dataclass(frozen=True)
class Profile:
    name: str
    #: Characters of rendered evidence the model reads, whatever the caller's
    #: Code Context budget.
    context_chars: int
    max_symbols: int
    max_memories: int
    #: Tokens for the answer itself, per model call.
    output_tokens: int
    #: Extra tokens a reasoning model may spend before answering, per call.
    reasoning_tokens: int
    time_s: float
    #: Narrow structured operations rather than one free-form answer.
    structured: bool
    #: Run every operation in one call. Each result still parses and verifies
    #: on its own.
    batch: bool

    @property
    def max_tokens(self) -> int:
        """The cap requested from the server for one call. Never widened."""
        return self.output_tokens + self.reasoning_tokens

    def calls(self, operations: int) -> int:
        return 1 if (not self.structured or self.batch) else operations

    def to_public(self) -> dict:
        return {**asdict(self), "max_tokens": self.max_tokens}

    def start(self) -> Run:
        return Run(self)


PROFILES: dict[str, Profile] = {
    # The free-form answer #218 introduced, now under hard limits.
    "general": Profile(
        name="general",
        context_chars=12000,
        max_symbols=24,
        max_memories=8,
        output_tokens=900,
        reasoning_tokens=0,
        time_s=90.0,
        structured=False,
        batch=False,
    ),
    # One narrow operation per call over a small packet: the 8B baseline.
    "small": Profile(
        name="small",
        context_chars=6000,
        max_symbols=12,
        max_memories=4,
        # The largest reply one operation's schema admits, so a complete
        # answer is never cut off by the cap.
        output_tokens=1024,
        reasoning_tokens=0,
        time_s=60.0,
        structured=True,
        batch=False,
    ),
    # The same operations and checks, batched, over more evidence.
    "large": Profile(
        name="large",
        context_chars=24000,
        max_symbols=40,
        max_memories=12,
        # Every operation's largest reply, in one call.
        output_tokens=4096,
        reasoning_tokens=8192,
        time_s=180.0,
        structured=True,
        batch=True,
    ),
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def selected_name() -> tuple[str, str]:
    """(profile name, where it came from): a saved setting, the env, or default."""
    try:
        from ...core import runtime_flags

        saved = runtime_flags.get(runtime_flags.ANALYST_PROFILE)
    except Exception:  # pragma: no cover - a flag read must never fail an answer
        saved = None
    if saved in PROFILES:
        return saved, "runtime"
    env = (os.environ.get(PROFILE_ENV) or "").strip().lower()
    if env:
        if env in PROFILES:
            return env, "environment"
        logger.warning("analyst.unknown_profile", value=env, allowed=list(PROFILES))
    return DEFAULT_PROFILE, "default"


def resolve(name: str | None = None, *, context_chars: int | None = None) -> Profile:
    """The profile to run, with operator overrides applied inside the ceilings.

    `context_chars` is the caller's Code Context budget; it can only lower the
    profile's evidence cap.
    """
    base = PROFILES.get(name or selected_name()[0], PROFILES[DEFAULT_PROFILE])
    output = base.output_tokens
    if base.name == "general":
        output = _safe_int("MARM_CODE_CONTEXT_ANSWER_TOKENS", output)
    reasoning = _safe_int("MARM_ANALYST_REASONING_TOKENS", base.reasoning_tokens)
    time_s = _safe_float("MARM_ANALYST_TIME_BUDGET", base.time_s)
    chars = base.context_chars
    if context_chars:
        chars = min(chars, max(500, context_chars))
    return replace(
        base,
        context_chars=chars,
        output_tokens=int(_clamp(output, 64, MAX_OUTPUT_TOKENS)),
        reasoning_tokens=int(_clamp(reasoning, 0, MAX_REASONING_TOKENS)),
        time_s=_clamp(time_s, MIN_TIME_S, MAX_TIME_S),
    )


@dataclass
class Run:
    profile: Profile
    cancel: threading.Event = field(default_factory=threading.Event)
    started: float = field(default_factory=time.monotonic)

    @property
    def deadline(self) -> float:
        """The monotonic instant the run must end by; passed to every call."""
        return self.started + self.profile.time_s

    def remaining(self) -> float:
        return max(0.0, self.profile.time_s - (time.monotonic() - self.started))

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def stop_reason(self) -> str | None:
        if self.cancel.is_set():
            return "cancelled"
        if self.expired():
            return "deadline"
        return None

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)
