from signalboard.domain.models import Alert

CRITICAL_ACKNOWLEDGEMENT_MINUTES = 15


def is_blocking(alert: Alert) -> bool:
    return (
        alert.severity == "critical"
        or not alert.owner
        or not alert.verification_command
    )
