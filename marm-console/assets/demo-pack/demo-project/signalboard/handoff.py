from .alerts import Alert
from .digest import build_release_digest


def operator_handoff(alerts: list[Alert]) -> str:
    digest = build_release_digest(alerts)
    state = "ready" if digest["release_ready"] else "blocked"
    return f"Release is {state}. Next action: {digest['next_action']}."
