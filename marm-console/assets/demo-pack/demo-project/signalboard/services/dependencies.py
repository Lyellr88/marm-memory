from signalboard.domain.models import DependencyCheck


def run_dependency_checks() -> list[DependencyCheck]:
    return [
        DependencyCheck("api", "pass"),
        DependencyCheck("worker", "pass"),
        DependencyCheck("notification adapter", "warn"),
    ]


def has_failure(checks: list[DependencyCheck]) -> bool:
    return any(check.status == "fail" for check in checks)
