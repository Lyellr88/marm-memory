"""The marm-memory CLI as data, introspected from the real argparse tree for the Console's CLI builder."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .cli_parser import _product_parser

_BLOCKING = "Runs until stopped, so it needs a terminal of its own."
_SECRET = (
    "Prints a secret. Run it in your own terminal so it never reaches the browser."
)
CLI_ONLY_COMMANDS = {
    "key reveal": _SECRET,
    "key generate": _SECRET,
    "uninstall": "Removes MARM. Run it yourself in a terminal.",
    "stdio": _BLOCKING,
    "http": _BLOCKING,
}
CLI_ONLY_FLAGS = {
    ("start", "--foreground"): _BLOCKING,
    ("logs", "--follow"): _BLOCKING,
    ("docker logs", "--follow"): _BLOCKING,
    ("console", "--foreground"): _BLOCKING,
}


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    return next(
        (a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None
    )


def _display_default(value: Any) -> Any:
    if isinstance(value, Path):
        home = Path.home()
        return (
            "~/" + value.relative_to(home).as_posix()
            if value.is_relative_to(home)
            else str(value)
        )
    return value


def _arg_type(action: argparse.Action) -> str:
    if action.type is int:
        return "int"
    return "path" if action.type is Path else "str"


def _argument(command: str, action: argparse.Action) -> dict[str, Any]:
    positional = not action.option_strings
    flag = None if positional else max(action.option_strings, key=len)
    kind = "positional" if positional else ("flag" if action.nargs == 0 else "option")
    default = None if action.default is argparse.SUPPRESS else action.default
    argument: dict[str, Any] = {
        "name": action.dest if positional else (flag or "").lstrip("-"),
        "flag": flag,
        "kind": kind,
        "type": _arg_type(action),
        "choices": list(action.choices) if action.choices else None,
        "default": _display_default(default),
        "required": bool(action.required)
        or (positional and action.nargs not in ("?", "*")),
        "help": action.help or "",
        "repeatable": isinstance(action, argparse._AppendAction),
    }
    reason = CLI_ONLY_FLAGS.get((command, flag or ""))
    if reason:
        argument["cli_only"] = True
        argument["cli_only_reason"] = reason
    return argument


def _walk(
    parser: argparse.ArgumentParser, path: list[str], help_text: str
) -> list[dict[str, Any]]:
    sub = _subparsers(parser)
    if sub is None:
        command = " ".join(path)
        args = [
            _argument(command, action)
            for action in parser._actions
            if action.help != argparse.SUPPRESS
            and not isinstance(action, argparse._HelpAction)
        ]
        return [
            {
                "command": command,
                "help": help_text,
                "args": args,
                "cli_only": command in CLI_ONLY_COMMANDS,
                "cli_only_reason": CLI_ONLY_COMMANDS.get(command),
            }
        ]
    helps = {a.dest: a.help or "" for a in sub._choices_actions}
    commands: list[dict[str, Any]] = []
    seen: set[int] = set()
    for name, child in sub.choices.items():
        if id(child) in seen:
            continue
        seen.add(id(child))
        commands.extend(_walk(child, [*path, name], helps.get(name, "")))
    return commands


def catalog() -> list[dict[str, Any]]:
    """Every runnable leaf command; subcommand groups are not commands themselves."""
    return _walk(_product_parser(), [], "")
