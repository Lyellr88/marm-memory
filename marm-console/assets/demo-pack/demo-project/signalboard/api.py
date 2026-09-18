from signalboard.delivery.outbox import queue_digest
from signalboard.reporting.digest import build_release_digest
from signalboard.services.release import prepare_release


def health() -> dict[str, str]:
    return {"status": "ok", "mode": "demo"}


def readiness() -> dict[str, object]:
    return build_release_digest(prepare_release())


def delivery_preview() -> dict[str, object]:
    return queue_digest()
