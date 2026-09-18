from signalboard.domain.models import ReleaseSnapshot


def build_release_digest(snapshot: ReleaseSnapshot) -> dict[str, object]:
    return {
        "release_ready": snapshot.ready,
        "readiness_score": snapshot.readiness_score,
        "unresolved_alerts": [alert.title for alert in snapshot.open_alerts],
        "next_action": snapshot.next_action,
    }
