from signalboard.domain.models import ReleaseSnapshot
from signalboard.intake import normalize_alerts, rehearsal_events
from signalboard.services.dependencies import has_failure, run_dependency_checks
from signalboard.services.readiness import next_action, readiness_score


def prepare_release() -> ReleaseSnapshot:
    alerts = normalize_alerts(rehearsal_events())
    checks = run_dependency_checks()
    return ReleaseSnapshot(
        ready=not has_failure(checks),
        open_alerts=alerts,
        next_action=next_action(alerts, checks),
        readiness_score=readiness_score(alerts, checks),
    )
