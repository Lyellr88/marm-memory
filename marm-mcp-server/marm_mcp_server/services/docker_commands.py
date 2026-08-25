from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .key_management import initialize_managed_key, managed_key_path, read_managed_key

DEFAULT_IMAGE_REPOSITORY = "lyellr88/marm-mcp-server"
DEFAULT_CONTAINER_NAME = "marm-mcp-server"
CONTAINER_DATA_DIR = "/home/marm/.marm"


class DockerCommandError(RuntimeError):
    """A Docker command could not be planned or safely completed."""


@dataclass(frozen=True)
class DockerRunOptions:
    """Validated options shared by Docker run and command preview."""

    profile: str = "standard"
    port: int = 8001
    data_dir: Path = field(default_factory=lambda: Path.home() / ".marm")
    name: str = DEFAULT_CONTAINER_NAME
    tag: str = "latest"
    repositories: tuple[Path, ...] = ()
    pull: bool = False
    expose_network: bool = False
    rate_limit_rpm: int | None = None
    env_file: Path | None = None
    memory: str | None = None
    cpus: str | None = None


def managed_env_file() -> Path:
    """Return the shared managed MARM key-file location."""
    return managed_key_path()


def image_reference(tag: str) -> str:
    if not tag or any(char.isspace() for char in tag):
        raise DockerCommandError("Docker image tag must be a non-empty single token.")
    repository = os.environ.get("MARM_DOCKER_REPOSITORY", DEFAULT_IMAGE_REPOSITORY)
    return f"{repository}:{tag}"


def _resolved_directory(
    path: Path, *, label: str, create: bool, require_exists: bool = True
) -> Path:
    resolved = path.expanduser().resolve()
    if create:
        resolved.mkdir(parents=True, exist_ok=True)
    if require_exists and not resolved.is_dir():
        raise DockerCommandError(f"{label} must be an existing directory: {resolved}")
    return resolved


def ensure_managed_env_file(path: Path | None = None) -> Path:
    """Return an env file containing a key, creating only MARM's default one."""
    env_file = (path or managed_env_file()).expanduser().resolve()
    if read_managed_key(env_file):
        return env_file
    if path is not None:
        raise DockerCommandError(
            f"{env_file} does not contain MARM_API_KEY. Add one or omit --env-file "
            "to use MARM's managed key file."
        )
    created_path, _created = initialize_managed_key(env_file)
    return created_path


def _repository_mounts(repositories: tuple[Path, ...]) -> tuple[list[str], list[str]]:
    arguments: list[str] = []
    mappings: list[str] = []
    for index, repository in enumerate(repositories, start=1):
        resolved = _resolved_directory(
            repository, label="Repository path", create=False
        )
        target = f"/workspace/repo-{index}"
        arguments.extend(["--mount", f"type=bind,src={resolved},dst={target},readonly"])
        mappings.append(f"{resolved} -> {target}")
    return arguments, mappings


def _container_user() -> str | None:
    """Map Linux bind-mount writes to the invoking host user."""
    if not sys.platform.startswith("linux"):
        return None
    return f"{os.getuid()}:{os.getgid()}"


def build_run_plan(
    options: DockerRunOptions,
    *,
    create_data_dir: bool = False,
    require_data_dir: bool = True,
) -> dict[str, Any]:
    """Build a deterministic Docker HTTP command without executing or writing secrets."""
    if not 1 <= options.port <= 65535:
        raise DockerCommandError("--port must be between 1 and 65535.")
    if options.profile not in {"standard", "swarm", "swarm-max", "trusted"}:
        raise DockerCommandError(
            "--profile must be standard, swarm, swarm-max, or trusted."
        )
    if options.rate_limit_rpm is not None and options.rate_limit_rpm < 0:
        raise DockerCommandError("--rate-limit-rpm must be 0 or greater.")
    if not options.name or any(char.isspace() for char in options.name):
        raise DockerCommandError("--name must be a non-empty Docker container name.")

    data_dir = _resolved_directory(
        options.data_dir,
        label="Data directory",
        create=create_data_dir,
        require_exists=require_data_dir,
    )
    env_file = (options.env_file or managed_env_file()).expanduser().resolve()
    host_binding = "0.0.0.0" if options.expose_network else "127.0.0.1"
    container_user = _container_user()
    arguments = [
        "docker",
        "run",
        "-d",
        "--name",
        options.name,
        "--restart",
        "unless-stopped",
        "--label",
        f"com.marm.profile={options.profile}",
        "--mount",
        f"type=bind,src={data_dir},dst={CONTAINER_DATA_DIR}",
        "--env-file",
        str(env_file),
        "-e",
        "SERVER_HOST=0.0.0.0",
        "-e",
        "HOME=/home/marm",
        "-e",
        "XDG_CACHE_HOME=/home/marm/.marm/cache",
        "-p",
        f"{host_binding}:{options.port}:8001",
    ]
    if container_user:
        arguments.extend(["--user", container_user])
    if options.pull:
        arguments.extend(["--pull", "always"])
    if options.memory:
        arguments.extend(["--memory", options.memory])
    if options.cpus:
        arguments.extend(["--cpus", options.cpus])
    if options.rate_limit_rpm is not None:
        arguments.extend(["-e", f"MARM_RATE_LIMIT_RPM={options.rate_limit_rpm}"])

    profile_args = {
        "standard": [],
        "swarm": ["--swarm"],
        "swarm-max": ["--swarm-max"],
        "trusted": ["--trusted"],
    }[options.profile]
    repository_args, repository_mappings = _repository_mounts(options.repositories)
    arguments.extend(repository_args)
    arguments.append(image_reference(options.tag))
    arguments.extend(profile_args)
    return {
        "arguments": arguments,
        "data_dir": str(data_dir),
        "env_file": str(env_file),
        "image": image_reference(options.tag),
        "host_binding": host_binding,
        "container_user": container_user,
        "repository_mappings": repository_mappings,
    }


def shell_command(arguments: list[str], *, windows: bool | None = None) -> str:
    """Render command arguments using the host shell's quoting convention."""
    use_windows = os.name == "nt" if windows is None else windows
    return subprocess.list2cmdline(arguments) if use_windows else shlex.join(arguments)


def _run(
    arguments: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise DockerCommandError(
            "Docker is not installed or is not available on PATH."
        ) from exc
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip() or "Docker command failed."
        raise DockerCommandError(detail)
    return result


def container_inspect(name: str) -> dict[str, Any] | None:
    result = _run(["docker", "container", "inspect", name], check=False)
    if result.returncode:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DockerCommandError(
            "Docker returned invalid container inspection data."
        ) from exc
    return payload[0] if isinstance(payload, list) and payload else None


def _is_marm_container(payload: dict[str, Any]) -> bool:
    config = payload.get("Config", {})
    image = str(config.get("Image", ""))
    labels = config.get("Labels") or {}
    return (
        image.startswith(DEFAULT_IMAGE_REPOSITORY)
        or labels.get("mcp.name") == "marm-mcp-server"
    )


def docker_status(name: str = DEFAULT_CONTAINER_NAME) -> dict[str, Any]:
    payload = container_inspect(name)
    if payload is None:
        return {"state": "absent", "name": name}
    if not _is_marm_container(payload):
        raise DockerCommandError(f"Container {name!r} is not a MARM container.")
    state = payload.get("State", {})
    host_config = payload.get("HostConfig", {})
    mounts = payload.get("Mounts", [])
    ports = (payload.get("NetworkSettings", {}) or {}).get("Ports", {})
    return {
        "state": state.get("Status", "unknown"),
        "health": (state.get("Health") or {}).get("Status", "unknown"),
        "name": name,
        "image": payload.get("Config", {}).get("Image", "unknown"),
        "image_id": payload.get("Image", "unknown"),
        "profile": (payload.get("Config", {}).get("Labels") or {}).get(
            "com.marm.profile", "unknown"
        ),
        "ports": ports,
        "restart_policy": (host_config.get("RestartPolicy") or {}).get("Name", ""),
        "mounts": [
            {"source": mount.get("Source"), "destination": mount.get("Destination")}
            for mount in mounts
            if mount.get("Destination") == CONTAINER_DATA_DIR
            or str(mount.get("Destination", "")).startswith("/workspace/")
        ],
    }


def pull_image(tag: str = "latest") -> str:
    image = image_reference(tag)
    _run(["docker", "pull", image])
    return image


def _wait_for_health(port: int, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                payload = json.load(response)
            if payload.get("status") == "healthy":
                return
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(0.5)
    raise DockerCommandError(
        "MARM container did not become healthy. Run `marm-memory docker logs --follow`."
    )


def run_container(options: DockerRunOptions) -> dict[str, Any]:
    existing = container_inspect(options.name)
    if existing is not None:
        raise DockerCommandError(
            f"Container {options.name!r} already exists. Inspect it with "
            f"`marm-memory docker status --name {options.name}` or stop it with "
            f"`marm-memory docker stop --name {options.name}`; MARM will not replace it."
        )
    plan = build_run_plan(options, create_data_dir=True)
    ensure_managed_env_file(options.env_file)
    _run(plan["arguments"])
    _wait_for_health(options.port)
    return plan


def stdio_command(
    *, tag: str = "latest", data_dir: Path | None = None
) -> dict[str, Any]:
    resolved_data_dir = _resolved_directory(
        data_dir or (Path.home() / ".marm"), label="Data directory", create=False
    )
    arguments = [
        "docker",
        "run",
        "-i",
        "--rm",
        "--mount",
        f"type=bind,src={resolved_data_dir},dst={CONTAINER_DATA_DIR}",
        "-e",
        "HOME=/home/marm",
        "-e",
        "XDG_CACHE_HOME=/home/marm/.marm/cache",
    ]
    container_user = _container_user()
    if container_user:
        arguments.extend(["--user", container_user])
    arguments.extend(
        [
            "--entrypoint",
            "marm-mcp-stdio",
            image_reference(tag),
        ]
    )
    return {
        "arguments": arguments,
        "data_dir": str(resolved_data_dir),
        "image": image_reference(tag),
        "container_user": container_user,
    }


def compose_document(options: DockerRunOptions) -> dict[str, Any]:
    """Build a Compose configuration with the same safety defaults as docker run."""
    plan = build_run_plan(options, require_data_dir=False)
    command = ["docker", "compose", "up", "-d", "--pull", "always"]
    profile_args = {
        "standard": [],
        "swarm": ["--swarm"],
        "swarm-max": ["--swarm-max"],
        "trusted": ["--trusted"],
    }[options.profile]
    environment = {
        "SERVER_HOST": "0.0.0.0",
        "HOME": "/home/marm",
        "XDG_CACHE_HOME": "/home/marm/.marm/cache",
    }
    if options.rate_limit_rpm is not None:
        environment["MARM_RATE_LIMIT_RPM"] = str(options.rate_limit_rpm)
    service: dict[str, Any] = {
        "image": plan["image"],
        "container_name": options.name,
        "restart": "unless-stopped",
        "ports": [f"{plan['host_binding']}:{options.port}:8001"],
        "env_file": [plan["env_file"]],
        "environment": environment,
        "volumes": [
            {
                "type": "bind",
                "source": plan["data_dir"],
                "target": CONTAINER_DATA_DIR,
            }
        ],
        "labels": {"com.marm.profile": options.profile},
    }
    if profile_args:
        service["command"] = profile_args
    if plan["container_user"]:
        service["user"] = plan["container_user"]
    if options.memory or options.cpus:
        service["deploy"] = {"resources": {"limits": {}}}
        limits = service["deploy"]["resources"]["limits"]
        if options.memory:
            limits["memory"] = options.memory
        if options.cpus:
            limits["cpus"] = options.cpus
    for mapping in plan["repository_mappings"]:
        source, target = mapping.split(" -> ", 1)
        service["volumes"].append(
            {"type": "bind", "source": source, "target": target, "read_only": True}
        )
    document = {"services": {"marm-mcp-server": service}}
    return {"document": document, "plan": plan, "command": command}


def _yaml_scalar(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def compose_yaml(document: dict[str, Any]) -> str:
    """Serialize the small generated Compose structure without a YAML dependency."""

    def render(value: object, indent: int = 0) -> list[str]:
        prefix = " " * indent
        if isinstance(value, dict):
            lines: list[str] = []
            for key, child in value.items():
                if isinstance(child, (dict, list)):
                    lines.append(f"{prefix}{key}:")
                    lines.extend(render(child, indent + 2))
                else:
                    lines.append(f"{prefix}{key}: {_yaml_scalar(child)}")
            return lines
        if isinstance(value, list):
            lines = []
            for child in value:
                if isinstance(child, (dict, list)):
                    lines.append(f"{prefix}-")
                    lines.extend(render(child, indent + 2))
                else:
                    lines.append(f"{prefix}- {_yaml_scalar(child)}")
            return lines
        return [f"{prefix}{_yaml_scalar(value)}"]

    return "\n".join(render(document)) + "\n"


def write_compose_file(options: DockerRunOptions, output: Path) -> dict[str, Any]:
    """Write a new Compose file only after validating data and managed auth."""
    resolved_output = output.expanduser().resolve()
    if resolved_output.exists():
        raise DockerCommandError(
            f"Compose file already exists: {resolved_output}. MARM will not overwrite it."
        )
    build_run_plan(options, create_data_dir=True)
    ensure_managed_env_file(options.env_file)
    payload = compose_document(options)
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(compose_yaml(payload["document"]), encoding="utf-8")
    payload["path"] = str(resolved_output)
    payload["command"] = [
        "docker",
        "compose",
        "-f",
        str(resolved_output),
        *payload["command"][2:],
    ]
    return payload


def migrate_embeddings(
    *,
    tag: str = "latest",
    data_dir: Path | None = None,
    name: str = DEFAULT_CONTAINER_NAME,
) -> int:
    status = docker_status(name)
    if status["state"] not in {"absent", "exited", "created", "dead"}:
        raise DockerCommandError(
            "Embedding migration requires the managed HTTP container to be stopped. "
            f"Run `marm-memory docker stop --name {name}` first."
        )
    resolved_data_dir = _resolved_directory(
        data_dir or (Path.home() / ".marm"), label="Data directory", create=False
    )
    arguments = [
        "docker",
        "run",
        "--rm",
        "--mount",
        f"type=bind,src={resolved_data_dir},dst={CONTAINER_DATA_DIR}",
        image_reference(tag),
        "--migrate-embeddings",
    ]
    try:
        return subprocess.call(arguments)
    except OSError as exc:
        raise DockerCommandError(
            "Docker is not installed or is not available on PATH."
        ) from exc


def docker_logs(name: str, *, follow: bool = False) -> int:
    arguments = ["docker", "logs"]
    if follow:
        arguments.append("--follow")
    arguments.append(name)
    try:
        return subprocess.call(arguments)
    except OSError as exc:
        raise DockerCommandError(
            "Docker is not installed or is not available on PATH."
        ) from exc


def stop_container(name: str) -> bool:
    payload = container_inspect(name)
    if payload is None:
        return False
    if not _is_marm_container(payload):
        raise DockerCommandError(f"Container {name!r} is not a MARM container.")
    _run(["docker", "stop", name])
    return True
