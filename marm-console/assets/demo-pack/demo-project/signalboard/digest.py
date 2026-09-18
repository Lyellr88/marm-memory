from .alerts import Alert, ready_for_release, unresolved_alerts


def build_release_digest(alerts: list[Alert]) -> dict[str, object]:
    pending = unresolved_alerts(alerts)
    return {
        "release_ready": ready_for_release(alerts),
        "unresolved_alerts": [alert.title for alert in pending],
        "next_action": "Ship the release" if not pending else "Assign alert owners",
    }
