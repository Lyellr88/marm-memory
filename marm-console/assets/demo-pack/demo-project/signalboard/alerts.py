from dataclasses import dataclass


@dataclass(frozen=True)
class Alert:
    title: str
    severity: str
    owner: str | None = None
    verification_command: str | None = None


def unresolved_alerts(alerts: list[Alert]) -> list[Alert]:
    return [
        alert for alert in alerts if not alert.owner or not alert.verification_command
    ]


def ready_for_release(alerts: list[Alert]) -> bool:
    return not unresolved_alerts(alerts)
