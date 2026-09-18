from signalboard.domain.models import Alert


def rehearsal_events() -> list[Alert]:
    return [
        Alert(
            "Release notes are incomplete",
            "medium",
            "docs",
            "Maya",
            "python -m signalboard.cli",
        ),
        Alert(
            "Webhook retry backlog",
            "low",
            "notifications",
            "Nora",
            "python -m signalboard.cli",
        ),
        Alert(
            "Worker latency check",
            "low",
            "worker",
            "Rowan",
            "python -m signalboard.cli",
        ),
    ]
