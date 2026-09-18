from signalboard.domain.models import Alert


def normalize_alerts(alerts: list[Alert]) -> list[Alert]:
    seen: set[tuple[str, str, str]] = set()
    normalized: list[Alert] = []
    for alert in alerts:
        key = (alert.service, alert.title.lower(), alert.severity)
        if key not in seen:
            seen.add(key)
            normalized.append(alert)
    return normalized
