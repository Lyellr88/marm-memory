"""The CLI catalog is introspected from the real argparse tree, so it must track it exactly."""

from __future__ import annotations

import argparse
from pathlib import Path

from marm_mcp_server.services import cli_catalog
from marm_mcp_server.services.cli_parser import _product_parser


def by_command() -> dict:
    return {c["command"]: c for c in cli_catalog.catalog()}


def arg(command: str, name: str) -> dict:
    return next(a for a in by_command()[command]["args"] if a["name"] == name)


def leaf_paths(parser: argparse.ArgumentParser, prefix: tuple = ()) -> set[str]:
    sub = next(
        (a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None
    )
    if sub is None:
        return {" ".join(prefix)}
    found: set[str] = set()
    for name, child in sub.choices.items():
        if name != "update":
            found |= leaf_paths(child, (*prefix, name))
    return found


def test_every_leaf_command_of_the_real_parser_is_listed() -> None:
    listed = set(by_command())
    assert listed == leaf_paths(_product_parser())
    assert {"start", "projects index", "docker run", "maintenance chunks rechunk"} <= (
        listed
    )
    assert "projects" not in listed and "docker" not in listed


def test_projects_index_has_a_positional_path_and_mode_choices() -> None:
    index = by_command()["projects index"]
    assert index["cli_only"] is False
    path = arg("projects index", "path")
    assert (path["kind"], path["required"], path["flag"]) == ("positional", True, None)
    mode = arg("projects index", "mode")
    assert mode["kind"] == "option" and mode["flag"] == "--mode"
    assert mode["choices"] == ["fast", "moderate", "full"]
    assert mode["default"] == "moderate" and mode["required"] is False


def test_docker_run_repo_is_repeatable_and_typed_as_a_path() -> None:
    repo = arg("docker run", "repo")
    assert repo["repeatable"] is True and repo["type"] == "path"
    assert repo["default"] == []
    assert arg("docker run", "port")["type"] == "int"
    assert arg("docker run", "port")["default"] == 8001
    assert arg("docker run", "profile")["choices"] == [
        "standard",
        "swarm",
        "swarm-max",
        "trusted",
    ]
    assert arg("docker run", "expose-network")["kind"] == "flag"
    assert arg("docker run", "dry-run")["kind"] == "flag"


def test_path_defaults_show_a_tilde_instead_of_this_machines_home() -> None:
    data_dir = arg("docker run", "data-dir")
    assert data_dir["type"] == "path" and data_dir["default"] == "~/.marm"
    assert str(Path.home()) not in str(cli_catalog.catalog())


def test_suppressed_arguments_and_help_are_excluded() -> None:
    names = {a["name"] for a in by_command()["start"]["args"]}
    assert "runtime-id" not in names and "help" not in names
    assert names == {"profile", "rate-limit-rpm", "foreground"}
    for command in cli_catalog.catalog():
        assert all(a["flag"] not in ("-h", "--help") for a in command["args"])


def test_cli_only_commands_and_flags() -> None:
    commands = by_command()
    for name in ("key reveal", "key generate", "uninstall", "stdio", "http"):
        assert commands[name]["cli_only"] is True
        assert commands[name]["cli_only_reason"]
    assert commands["key init"]["cli_only"] is False
    for command, flag in (
        ("start", "foreground"),
        ("logs", "follow"),
        ("docker logs", "follow"),
        ("console", "foreground"),
    ):
        entry = arg(command, flag)
        assert entry["cli_only"] is True and entry["cli_only_reason"]
    assert "cli_only" not in arg("logs", "lines")
    assert arg("logs", "lines")["default"] == 100


def test_required_and_optional_positionals() -> None:
    assert arg("projects status", "project")["required"] is False
    assert arg("projects remove", "project")["required"] is True
    assert arg("projects remove", "confirm")["required"] is True
    assert arg("knowledge auto", "state")["choices"] == ["on", "off", "status"]


def test_help_text_comes_from_the_subparser_registration() -> None:
    commands = by_command()
    assert commands["start"]["help"] == "Start the local MARM runtime"
    assert commands["key init"]["help"] == "Create or reuse the managed local key file"
    assert arg("key init", "keychain")["help"].startswith("Also store the managed key")


def test_aliases_are_not_listed_twice() -> None:
    listed = [c["command"] for c in cli_catalog.catalog()]
    assert listed.count("upgrade") == 1 and "update" not in listed
    assert len(listed) == len(set(listed))
