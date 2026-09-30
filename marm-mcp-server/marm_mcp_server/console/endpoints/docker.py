"""Docker tab API: engine detection, the MARM container lifecycle, run config, and compose file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...config import user_settings
from ...services import docker_commands
from .. import jobs
from .setup import _require_loopback

router = APIRouter()

_registry = jobs.JobRegistry("marm-console-docker")

READ_ONLY_REASON = (
    "The Console is running inside a container, so it cannot manage Docker."
)


class ComposePayload(BaseModel):
    overwrite: bool = False


def _read_only_reason() -> str | None:
    return READ_ONLY_REASON if user_settings._in_container() else None


def _require_managing() -> None:
    reason = _read_only_reason()
    if reason:
        raise HTTPException(status_code=409, detail=reason)


def _guard_write(action: str) -> None:
    _require_loopback(action)
    _require_managing()


def docker_url(config: dict[str, Any]) -> str:
    return f"http://127.0.0.1:{config['port']}/mcp"


def _options(config: dict[str, Any]) -> docker_commands.DockerRunOptions:
    return docker_commands.DockerRunOptions(
        profile=config["profile"],
        port=config["port"],
        data_dir=Path(config["data_dir"]),
        tag=config["tag"],
        repositories=tuple(Path(repo) for repo in config["repos"]),
        expose_network=config["expose_network"],
        rate_limit_rpm=config["rate_limit_rpm"],
        memory=config["memory"],
        cpus=config["cpus"],
    )


def _container(engine: dict[str, Any]) -> dict[str, Any]:
    name = docker_commands.DEFAULT_CONTAINER_NAME
    if not engine["daemon"]:
        return {"state": "absent", "name": name}
    try:
        return docker_commands.docker_status(name)
    except docker_commands.DockerCommandError as exc:
        return {"state": "conflict", "name": name, "detail": str(exc)}


def _body() -> dict[str, Any]:
    engine = docker_commands.engine_status()
    config = user_settings.load_docker()
    return {
        "engine": engine,
        "in_container": user_settings._in_container(),
        "read_only_reason": _read_only_reason(),
        "container": _container(engine),
        "config": config,
        "url": docker_url(config),
    }


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/api/connections/docker")
def get_docker() -> dict:
    return _body()


@router.put("/api/connections/docker/config")
def put_docker_config(payload: dict[str, Any]) -> dict:
    _guard_write("Saving the Docker configuration")
    try:
        user_settings.save_docker(payload)
    except user_settings.SettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=409, detail=f"Could not write settings: {exc.strerror or exc}"
        ) from exc
    return _body()


def _pull() -> str:
    image = docker_commands.pull_image(user_settings.load_docker()["tag"])
    return f"Pulled {image}"


def _start() -> str:
    options = _options(user_settings.load_docker())
    state = docker_commands.docker_status(options.name)["state"]
    if state == "absent":
        docker_commands.run_container(options)
        return "Started a new container."
    if state == "running":
        return "Already running."
    docker_commands.start_container(options.name)
    return "Started the existing container."


def _recreate() -> str:
    options = _options(user_settings.load_docker())
    docker_commands.stop_container(options.name)
    docker_commands.remove_container(options.name)
    docker_commands.run_container(options)
    return "Recreated the container."


def _start_job(kind: str, work: Any) -> dict[str, str]:
    return {"job_id": _registry.start(kind, "docker", work)}


@router.post("/api/connections/docker/pull", status_code=202)
def post_pull() -> dict:
    _guard_write("Pull")
    return _start_job("pull", _pull)


@router.post("/api/connections/docker/start", status_code=202)
def post_start() -> dict:
    _guard_write("Start")
    return _start_job("start", _start)


@router.post("/api/connections/docker/recreate", status_code=202)
def post_recreate() -> dict:
    _guard_write("Recreate")
    return _start_job("recreate", _recreate)


@router.post("/api/connections/docker/stop")
def post_stop() -> dict:
    _guard_write("Stop")
    try:
        docker_commands.stop_container(docker_commands.DEFAULT_CONTAINER_NAME)
    except docker_commands.DockerCommandError as exc:
        raise _conflict(exc) from exc
    return _body()


@router.post("/api/connections/docker/restart")
def post_restart() -> dict:
    _guard_write("Restart")
    try:
        present = docker_commands.restart_container(
            docker_commands.DEFAULT_CONTAINER_NAME
        )
    except docker_commands.DockerCommandError as exc:
        raise _conflict(exc) from exc
    if not present:
        raise HTTPException(
            status_code=409, detail="There is no MARM container to restart."
        )
    return _body()


@router.get("/api/connections/docker/jobs/{job_id}")
def get_docker_job(job_id: str) -> dict:
    job = _registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown Docker job.")
    return job


@router.get("/api/connections/docker/logs")
def get_logs(lines: int = 200) -> dict:
    _require_managing()
    try:
        return {
            "lines": docker_commands.logs_tail(
                docker_commands.DEFAULT_CONTAINER_NAME, lines
            )
        }
    except docker_commands.DockerCommandError as exc:
        raise _conflict(exc) from exc


def _compose_path() -> Path:
    return user_settings.settings_path().parent / "marm-compose.yaml"


def _compose_preview(path: Path) -> dict[str, Any]:
    try:
        payload = docker_commands.compose_document(
            _options(user_settings.load_docker())
        )
    except docker_commands.DockerCommandError as exc:
        raise _conflict(exc) from exc
    command = ["docker", "compose", "-f", str(path), *payload["command"][2:]]
    return {
        "path": str(path),
        "exists": path.exists(),
        "yaml": docker_commands.compose_yaml(payload["document"]),
        "command": docker_commands.shell_command(command),
    }


@router.get("/api/connections/docker/compose")
def get_compose() -> dict:
    _require_managing()
    return _compose_preview(_compose_path())


@router.post("/api/connections/docker/compose")
def post_compose(payload: ComposePayload) -> dict:
    _guard_write("Writing the Compose file")
    path = _compose_path().resolve()
    if path.exists() and not payload.overwrite:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "exists",
                "path": str(path),
                "message": f"{path} already exists. Overwrite it to replace it.",
            },
        )
    try:
        written = docker_commands.write_compose_file(
            _options(user_settings.load_docker()), path, overwrite=payload.overwrite
        )
    except (docker_commands.DockerCommandError, OSError) as exc:
        raise _conflict(exc) from exc
    result = _compose_preview(path)
    result["backup_path"] = written.get("backup_path")
    return result
