"""Hard limits on one analysis: context, output, wall time, follow-ups."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from ...config.env_parsing import _safe_float, _safe_int


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass
class Budget:
    context_chars: int = 12000
    output_tokens: int = 900
    time_s: float = 90.0
    follow_ups: int = 0

    @classmethod
    def from_env(
        cls, *, context_chars: int | None = None, follow_ups: int | None = None
    ) -> Budget:
        ceiling = int(_clamp(_safe_int("MARM_ANALYST_FOLLOW_UPS", 0), 0, 2))
        return cls(
            context_chars=context_chars or 12000,
            output_tokens=_safe_int("MARM_CODE_CONTEXT_ANSWER_TOKENS", 900),
            time_s=_clamp(_safe_float("MARM_ANALYST_TIME_BUDGET", 90.0), 5.0, 600.0),
            # The operator sets the ceiling; a caller may only ask for less.
            follow_ups=(
                ceiling if follow_ups is None else min(max(follow_ups, 0), ceiling)
            ),
        )

    def start(self) -> Run:
        return Run(self)


@dataclass
class Run:
    budget: Budget
    cancel: threading.Event = field(default_factory=threading.Event)
    started: float = field(default_factory=time.monotonic)

    def remaining(self) -> float:
        return max(0.0, self.budget.time_s - (time.monotonic() - self.started))

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def stop_reason(self) -> str | None:
        if self.cancel.is_set():
            return "cancelled"
        if self.expired():
            return "deadline"
        return None
