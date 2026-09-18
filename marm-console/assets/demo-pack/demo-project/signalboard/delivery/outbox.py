from signalboard.reporting.digest import build_release_digest
from signalboard.services.release import prepare_release


def queue_digest() -> dict[str, object]:
    return {
        "delivery_state": "pending",
        "payload": build_release_digest(prepare_release()),
    }
