"""The registry entry must launch the transport it declares."""

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

from marm_mcp_server.services import docker_commands

SERVER_JSON = Path(__file__).resolve().parents[1] / "server.json"


class _Reached(BaseException):
    # Not an Exception: the server launchers catch those and exit 1.
    pass


def _packages() -> dict[str, dict]:
    config = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
    return {p["registryType"]: p for p in config["packages"]}


def _values(arguments: list[dict]) -> list[str]:
    out: list[str] = []
    for argument in arguments:
        if argument["type"] == "named":
            out.append(argument["name"])
        if "value" in argument:
            out.append(argument["value"])
    return out


def _launch(monkeypatch, argv: list[str]) -> str:
    def stdio() -> None:
        raise _Reached("stdio")

    async def http() -> None:
        raise _Reached("http")

    # Resolved now, not at import: other tests reload the package, and cli's
    # `from . import server_stdio` reads whichever package object is current.
    # The real module reroutes print() process-wide, so it is never imported.
    cli = importlib.import_module("marm_mcp_server.cli")
    package = sys.modules["marm_mcp_server"]
    fake = types.ModuleType("marm_mcp_server.server_stdio")
    fake.main = stdio
    monkeypatch.setitem(sys.modules, "marm_mcp_server.server_stdio", fake)
    monkeypatch.setattr(package, "server_stdio", fake, raising=False)
    monkeypatch.setattr(cli, "run_server_with_shutdown", http)
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(_Reached) as reached:
        cli.main()
    return str(reached.value)


@pytest.mark.parametrize("registry_type", ["pypi", "oci"])
def test_every_package_declares_stdio(registry_type):
    assert _packages()[registry_type]["transport"] == {"type": "stdio"}


def test_the_pypi_package_starts_stdio_not_http(monkeypatch):
    package = _packages()["pypi"]
    assert package["runtimeHint"] == "uvx"
    argv = [package["identifier"], *_values(package["packageArguments"])]
    assert _launch(monkeypatch, argv) == "stdio"


def test_the_oci_image_starts_stdio_not_http(monkeypatch):
    # The image's entrypoint is `python -m marm_mcp_server`.
    package = _packages()["oci"]
    argv = ["__main__.py", *_values(package["packageArguments"])]
    assert _launch(monkeypatch, argv) == "stdio"


def test_a_bare_launch_is_http_which_is_why_the_argument_is_needed(monkeypatch):
    assert _launch(monkeypatch, ["marm-mcp-server"]) == "http"


def test_the_oci_image_keeps_memory_in_its_data_directory():
    package = _packages()["oci"]
    assert package["runtimeHint"] == "docker"
    mounts = [
        a["value"] for a in package["runtimeArguments"] if a.get("name") == "--mount"
    ]
    assert mounts, "a stdio container is removed after each session"
    assert any(
        f"dst={docker_commands.CONTAINER_DATA_DIR}" in m and "type=volume" in m
        for m in mounts
    )


def test_the_docker_command_a_client_builds_is_interactive_and_removed():
    # A registry client builds `docker run <runtimeArguments> <image> <args>`.
    package = _packages()["oci"]
    command = [
        "docker",
        "run",
        *_values(package["runtimeArguments"]),
        package["identifier"],
        *_values(package["packageArguments"]),
    ]
    image = command.index(package["identifier"])
    assert "-i" in command[:image], "STDIO needs the container's stdin open"
    assert "--rm" in command[:image], "each session would leave a container"
    assert command[image + 1 :] == ["stdio"]
