"""Code-index project commands for the marm-memory product CLI."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable


def dispatch_projects(
    args: argparse.Namespace,
    *,
    ensure_runtime: Callable[[], dict],
    runtime_post: Callable[[str, dict], dict],
    print_payload: Callable,
) -> int:
    """Run bounded project-index commands against the managed runtime."""
    from ..core.runtime_manager import (
        RuntimeRequestError,
        RuntimeUnavailable,
        request_runtime,
        request_runtime_strict,
    )

    ensure_runtime()

    if args.projects_command == "list":
        payload = runtime_post("/internal/projects/list", {})
    elif args.projects_command == "status":
        if args.project is None:
            payload = request_runtime("/internal/runtime/status") or {}
            payload = payload.get("graph", payload)
        else:
            payload = runtime_post(
                "/internal/projects/status", {"project": args.project}
            )
    elif args.projects_command == "remove":
        if args.confirm != args.project:
            print("--confirm must exactly match the project name.", file=sys.stderr)
            return 2
        payload = runtime_post(
            "/internal/projects/delete",
            {"project": args.project, "name": args.confirm, "confirm": True},
        )
    else:
        path = Path(args.path).expanduser()
        if not path.is_absolute() or not path.is_dir():
            print(
                "Repository path must be an existing absolute directory.",
                file=sys.stderr,
            )
            return 2
        job = runtime_post(
            "/internal/projects/index",
            {"repo_path": str(path.resolve()), "mode": args.mode},
        )
        job_id = job.get("job_id")
        if not job_id:
            print_payload(job)
            return 1
        poll_failures = 0
        while True:
            try:
                payload = request_runtime_strict(
                    f"/internal/projects/jobs/{job_id}", timeout=5.0
                )
                poll_failures = 0
            except RuntimeRequestError as exc:
                if exc.status_code != 429 and exc.status_code < 500:
                    raise
                poll_failures += 1
                if poll_failures >= 5:
                    raise RuntimeError(
                        "Project index status could not be read after 5 attempts."
                    ) from exc
                time.sleep(exc.retry_after or 1)
                continue
            except RuntimeUnavailable as exc:
                poll_failures += 1
                if poll_failures >= 5:
                    raise RuntimeError(
                        "Lost contact with the runtime while indexing the project."
                    ) from exc
                time.sleep(1)
                continue
            status = payload.get("status")
            if status in {"success", "error"}:
                break
            if status not in {"queued", "running"}:
                raise RuntimeError("The project index job returned an invalid status.")
            time.sleep(1)
    print_payload(payload)
    return 1 if payload.get("status") == "error" else 0
