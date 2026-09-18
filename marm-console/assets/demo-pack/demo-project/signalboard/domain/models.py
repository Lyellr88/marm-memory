from dataclasses import dataclass


@dataclass(frozen=True)
class Alert:
    title: str
    severity: str
    service: str
    owner: str | None = None
    verification_command: str | None = None


@dataclass(frozen=True)
class DependencyCheck:
    name: str
    status: str


@dataclass(frozen=True)
class ReleaseSnapshot:
    ready: bool
    open_alerts: list[Alert]
    next_action: str
    readiness_score: int
