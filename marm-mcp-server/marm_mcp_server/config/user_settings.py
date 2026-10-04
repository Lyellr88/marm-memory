"""Allowlisted boot-time settings saved to ~/.marm/settings.json and overlaid into os.environ."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .env_reference import ENV_REFERENCE
from .setting_definitions import KEY_ENV as _KEY_ENV
from .setting_definitions import SETTINGS, Setting

logger = logging.getLogger(__name__)

SHADOW_ENV = "MARM_SETTINGS_SHADOWED"
_NETWORK_ENVS = ("SERVER_HOST", "SERVER_PORT")


class SettingsError(ValueError):
    """An unknown key, a bad value, or a settings file that cannot be merged safely."""


_BY_KEY = {setting.key: setting for setting in SETTINGS}

_GROUP_LABELS = {
    "server": "Server",
    "security": "Security",
    "search": "Search",
    "graph": "Code graph",
    "memory": "Memory",
    "llm": "Local model",
    "logging": "Logging",
}


def _home() -> Path:
    return Path.home()


def settings_path() -> Path:
    override = os.environ.get("MARM_SETTINGS_PATH")
    return Path(override) if override else _home() / ".marm" / "settings.json"


def _in_container() -> bool:
    """Mirrors console/terminal/pty_session.in_container, which cannot be imported this early."""
    if os.environ.get("MARM_IN_DOCKER") or os.environ.get("KUBERNETES_SERVICE_HOST"):
        return True
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(m in cgroup for m in ("docker", "containerd", "kubepods", "lxc"))


def _validate(setting: Setting, value: Any) -> Any:
    if setting.type == "bool":
        if not isinstance(value, bool):
            raise SettingsError(f"{setting.key} must be true or false")
        return value
    if setting.type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise SettingsError(f"{setting.key} must be a whole number")
        assert setting.min is not None and setting.max is not None
        if not setting.min <= value <= setting.max:
            raise SettingsError(
                f"{setting.key} must be between {setting.min} and {setting.max}"
            )
        return value
    if not isinstance(value, str) or value not in (setting.choices or ()):
        raise SettingsError(
            f"{setting.key} must be one of {', '.join(setting.choices or ())}"
        )
    return value


def _encode(setting: Setting, value: Any) -> str:
    if setting.encoding == "01":
        return "1" if value else "0"
    if setting.encoding == "truefalse":
        return "true" if value else "false"
    if setting.encoding == "host":
        return "0.0.0.0" if value else "127.0.0.1"
    return str(value)


def _decode(setting: Setting, raw: str) -> Any:
    """Read a raw env string back into a value, or None when it is not valid."""
    if setting.encoding == "key":
        return bool(raw)
    if setting.encoding == "01":
        return raw == "1"
    if setting.encoding == "truefalse":
        return raw.lower() != "false"
    if setting.encoding == "host":
        return raw == "0.0.0.0"
    try:
        if setting.type == "int":
            return _validate(setting, int(raw))
    except (SettingsError, ValueError):
        return None
    return next(
        (c for c in setting.choices or () if c.lower() == raw.strip().lower()), None
    )


def _read_raw() -> dict[str, Any]:
    """The whole file as an object; raises when it is unreadable or not an object."""
    path = settings_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("settings file is not a JSON object")
    return data


def load() -> dict[str, Any]:
    """Saved allowlisted values keyed by dotted name; never raises."""
    try:
        raw = _read_raw()
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable settings file %s: %s", settings_path(), exc)
        return {}
    saved: dict[str, Any] = {}
    for setting in SETTINGS:
        section, _, name = setting.key.partition(".")
        block = raw.get(section)
        if not isinstance(block, dict) or name not in block:
            continue
        try:
            saved[setting.key] = _validate(setting, block[name])
        except SettingsError as exc:
            logger.warning("Ignoring saved setting: %s", exc)
    return saved


def _prepare(values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    checked: dict[str, Any] = {}
    for key, value in values.items():
        setting = _BY_KEY.get(key)
        if setting is None:
            raise SettingsError(f"Unknown setting: {key}")
        checked[key] = _validate(setting, value)
    try:
        raw = _read_raw()
    except (OSError, ValueError) as exc:
        raise SettingsError(f"Settings file cannot be read: {exc}") from exc
    return checked, raw


def validate(values: dict[str, Any]) -> None:
    """Raise SettingsError exactly when save() would, without writing anything."""
    _prepare(values)


def save(values: dict[str, Any]) -> dict[str, Any]:
    """Validate against the allowlist, merge into the file, and replace it atomically."""
    checked, raw = _prepare(values)
    for key, value in checked.items():
        section, _, name = key.partition(".")
        block = raw.get(section)
        if not isinstance(block, dict):
            block = raw[section] = {}
        block[name] = value
    _write_raw(raw)
    return load()


def _write_raw(raw: dict[str, Any]) -> None:
    path = settings_path()
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


DOCKER_SECTION = "docker"
DOCKER_PROFILES = ("standard", "swarm", "swarm-max", "trusted")


def docker_defaults() -> dict[str, Any]:
    return {
        "port": 8001,
        "tag": "latest",
        "data_dir": str(_home() / ".marm"),
        "repos": [],
        "memory": None,
        "cpus": None,
        "expose_network": False,
        "profile": "standard",
        "rate_limit_rpm": None,
    }


def _short_token(value: Any, name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 32:
        raise SettingsError(f"docker.{name} must be a short value or empty")
    if any(char.isspace() for char in value):
        raise SettingsError(f"docker.{name} must not contain spaces")
    return value


def _validate_docker(config: dict[str, Any]) -> dict[str, Any]:
    checked = docker_defaults()
    for key, value in config.items():
        if key not in checked:
            raise SettingsError(f"Unknown docker setting: {key}")
        if key == "port":
            if isinstance(value, bool) or not isinstance(value, int):
                raise SettingsError("docker.port must be a whole number")
            if not 1 <= value <= 65535:
                raise SettingsError("docker.port must be between 1 and 65535")
        elif key == "tag":
            if (
                not isinstance(value, str)
                or not value
                or any(c.isspace() for c in value)
            ):
                raise SettingsError("docker.tag must be a single word")
        elif key == "profile":
            if value not in DOCKER_PROFILES:
                raise SettingsError(
                    f"docker.profile must be one of {', '.join(DOCKER_PROFILES)}"
                )
        elif key == "rate_limit_rpm":
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise SettingsError("docker.rate_limit_rpm must be 0 or greater")
        elif key in ("memory", "cpus"):
            value = _short_token(value, key)
        elif key == "repos":
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item for item in value
            ):
                raise SettingsError("docker.repos must be a list of paths")
        elif key == "data_dir":
            if not isinstance(value, str) or not value.strip():
                raise SettingsError("docker.data_dir must be a path")
        elif not isinstance(value, bool):
            raise SettingsError("docker.expose_network must be true or false")
        checked[key] = value
    return checked


def load_docker() -> dict[str, Any]:
    """The saved Docker run configuration over its defaults; never raises."""
    config = docker_defaults()
    try:
        block = _read_raw().get(DOCKER_SECTION)
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable settings file %s: %s", settings_path(), exc)
        return config
    if not isinstance(block, dict):
        return config
    for key in config:
        if key not in block:
            continue
        try:
            config[key] = _validate_docker({key: block[key]})[key]
        except SettingsError as exc:
            logger.warning("Ignoring saved setting: %s", exc)
    return config


def save_docker(config: dict[str, Any]) -> dict[str, Any]:
    """Validate and replace only the docker section; the allowlisted keys are untouched."""
    checked = _validate_docker(config)
    try:
        raw = _read_raw()
    except (OSError, ValueError) as exc:
        raise SettingsError(f"Settings file cannot be read: {exc}") from exc
    raw[DOCKER_SECTION] = checked
    _write_raw(raw)
    return load_docker()


def _read_shadow() -> dict[str, str | None]:
    try:
        data = json.loads(os.environ.get(SHADOW_ENV, ""))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def apply_overlay() -> None:
    """Saved settings beat the shell env; pre-overlay values go to MARM_SETTINGS_SHADOWED."""
    try:
        saved = load()
        shadow = _read_shadow()
        skip_network = os.environ.get("MARM_TRANSPORT") == "stdio" or _in_container()
        applied: set[str] = set()
        for setting in SETTINGS:
            if setting.key not in saved:
                continue
            if skip_network and setting.env in _NETWORK_ENVS:
                continue
            if setting.encoding == "key":
                if not saved[setting.key]:
                    continue
                if os.environ.get(_KEY_ENV) and _KEY_ENV not in shadow:
                    continue
                from ..services.key_management import read_managed_key

                value = read_managed_key()
                if not value:
                    continue
            else:
                value = _encode(setting, saved[setting.key])
            if setting.env not in shadow:
                shadow[setting.env] = os.environ.get(setting.env)
            os.environ[setting.env] = value
            applied.add(setting.env)
        # A parent's overlay reaches children through the env, so a setting that is no longer saved must be undone here.
        for env, original in list(shadow.items()):
            if env in applied or (skip_network and env in _NETWORK_ENVS):
                continue
            if original is None:
                os.environ.pop(env, None)
            else:
                os.environ[env] = original
            del shadow[env]
        if shadow:
            os.environ[SHADOW_ENV] = json.dumps(shadow)
        else:
            os.environ.pop(SHADOW_ENV, None)
    except Exception:
        logger.warning("Settings overlay failed; applying nothing more", exc_info=True)


def key_required(current_key: str) -> bool:
    try:
        saved = load()
    except (SettingsError, OSError, ValueError):
        return bool(current_key)
    if any(saved.get(s.key) for s in SETTINGS if s.encoding == "key"):
        return True
    if current_key and _KEY_ENV in _read_shadow():
        return False
    return bool(current_key)


def describe() -> dict[str, Any]:
    saved = load()
    shadow = _read_shadow()
    groups: dict[str, list[dict[str, Any]]] = {}
    for setting in SETTINGS:
        original = (
            shadow[setting.env]
            if setting.env in shadow
            else os.environ.get(setting.env)
        )
        env_value = _decode(setting, original) if original is not None else None
        help_text = setting.help
        value: bool | int | str
        if (
            setting.encoding == "key"
            and os.environ.get(_KEY_ENV)
            and _KEY_ENV not in shadow
        ):
            value, source = True, "env"
            help_text = "MARM_API_KEY is set outside this page (your shell or network mode), so a key is always required."
        elif setting.key in saved:
            value, source = saved[setting.key], "saved"
        elif env_value is not None:
            value, source = env_value, "env"
        else:
            value, source = setting.default, "default"
        item: dict[str, Any] = {
            "key": setting.key,
            "label": setting.label,
            "help": help_text,
            "type": setting.type,
            "default": setting.default,
            "value": value,
            "source": source,
            "overrides_env": (
                source == "saved" and original is not None and setting.encoding != "key"
            ),
            "live": False,
        }
        if setting.choices:
            item["choices"] = list(setting.choices)
        if setting.min is not None:
            item["min"] = setting.min
            item["max"] = setting.max
        groups.setdefault(setting.group, []).append(item)
    return {
        "path": str(settings_path()),
        "groups": [
            {"id": gid, "label": _GROUP_LABELS[gid], "items": items}
            for gid, items in groups.items()
        ],
    }


def _shown(value: Any) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def _env_item(setting: Setting, described: dict[str, Any]) -> dict[str, Any]:
    is_key = setting.encoding == "key"
    if is_key:
        current = "set" if os.environ.get(_KEY_ENV) else "not set"
    else:
        current = _shown(described["value"])
    return {
        "name": setting.env,
        "group": _GROUP_LABELS[setting.group],
        "default": "not set" if is_key else _shown(setting.default),
        "current": current,
        "source": described["source"],
        "setting_key": setting.key,
        "description": setting.help,
    }


def env_reference() -> list[dict[str, Any]]:
    """Allowlisted settings first, then the read-only registry; the API key value is never shown."""
    described = {
        item["key"]: item for group in describe()["groups"] for item in group["items"]
    }
    items = [_env_item(setting, described[setting.key]) for setting in SETTINGS]
    for var in ENV_REFERENCE:
        raw = os.environ.get(var.name)
        items.append(
            {
                "name": var.name,
                "group": var.group,
                "default": var.default,
                "current": raw or var.default,
                "source": "env" if raw else "default",
                "setting_key": None,
                "description": var.description,
            }
        )
    return items
