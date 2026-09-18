from signalboard.reporting.digest import build_release_digest
from signalboard.services.release import prepare_release


def operator_handoff() -> str:
    digest = build_release_digest(prepare_release())
    state = "ready" if digest["release_ready"] else "blocked"
    return f"Release is {state}. Next action: {digest['next_action']}."
