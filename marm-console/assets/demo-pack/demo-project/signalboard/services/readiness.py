from signalboard.config.policy import is_blocking
from signalboard.domain.models import Alert, DependencyCheck
from signalboard.services.dependencies import has_failure


def readiness_score(alerts: list[Alert], checks: list[DependencyCheck]) -> int:
    penalty = sum(30 for alert in alerts if is_blocking(alert))
    penalty += sum(15 for check in checks if check.status == "warn")
    return max(0, 100 - penalty)


def next_action(alerts: list[Alert], checks: list[DependencyCheck]) -> str:
    if has_failure(checks):
        return "Resolve failed dependency checks"
    if any(is_blocking(alert) for alert in alerts):
        return "Assign owners and verification commands"
    return "Review routine alerts in the next planning cycle"
