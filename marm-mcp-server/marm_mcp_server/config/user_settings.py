"""Allowlisted boot-time settings saved to ~/.marm/settings.json and overlaid into os.environ."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SHADOW_ENV = "MARM_SETTINGS_SHADOWED"
_KEY_ENV = "MARM_API_KEY"
_NETWORK_ENVS = ("SERVER_HOST", "SERVER_PORT")


class SettingsError(ValueError):
    """An unknown key, a bad value, or a settings file that cannot be merged safely."""


@dataclass(frozen=True)
class Setting:
    key: str
    env: str
    type: str
    encoding: str
    group: str
    label: str
    help: str
    default: bool | int | str
    choices: tuple[str, ...] | None = None
    min: int | None = None
    max: int | None = None


SETTINGS: tuple[Setting, ...] = (
    Setting(
        "server.port",
        "SERVER_PORT",
        "int",
        "plain",
        "server",
        "Port",
        "Port the MARM server listens on.",
        8001,
        min=1,
        max=65535,
    ),
    Setting(
        "server.expose_network",
        "SERVER_HOST",
        "bool",
        "host",
        "server",
        "Expose to the network",
        "Listen on every interface instead of this computer only. Requires a key.",
        False,
    ),
    Setting(
        "auth.require_key",
        _KEY_ENV,
        "bool",
        "key",
        "security",
        "Require a key",
        "Clients must send the MARM key. A key is created for you if none exists.",
        False,
    ),
    Setting(
        "search.semantic",
        "SEMANTIC_SEARCH_ENABLED",
        "bool",
        "01",
        "search",
        "Semantic search",
        "Find memories by meaning, using the local embedding model.",
        True,
    ),
    Setting(
        "graph.enabled",
        "GRAPH_ENABLED",
        "bool",
        "truefalse",
        "graph",
        "Code graph",
        "Build and serve the code graph for indexed projects.",
        True,
    ),
    Setting(
        "graph.auto_index_mode",
        "GRAPH_AUTO_INDEX_MODE",
        "choice",
        "plain",
        "graph",
        "Auto-index depth",
        "How thorough automatic code indexing is.",
        "moderate",
        choices=("full", "moderate", "fast"),
    ),
    Setting(
        "compaction.enabled",
        "COMPACTION_ENABLED",
        "bool",
        "01",
        "memory",
        "Compaction",
        "Find old memories that can be merged.",
        False,
    ),
    Setting(
        "compaction.auto_apply",
        "COMPACTION_AUTO_APPLY_ENABLED",
        "bool",
        "01",
        "memory",
        "Apply compaction automatically",
        "Merge compaction candidates without asking.",
        False,
    ),
    Setting(
        "compaction.min_age_hours",
        "COMPACTION_MIN_AGE_HOURS",
        "int",
        "plain",
        "memory",
        "Compaction minimum age (hours)",
        "Memories younger than this are never compacted.",
        24,
        min=0,
        max=8760,
    ),
    Setting(
        "consolidation.enabled",
        "CONSOLIDATION_ENABLED",
        "bool",
        "01",
        "memory",
        "Consolidation",
        "Merge near-duplicate memories when they are saved.",
        False,
    ),
    Setting(
        "distill.nudge",
        "MARM_DISTILL_NUDGE",
        "bool",
        "01",
        "memory",
        "Distill reminders",
        "Remind the agent to save what it learned.",
        True,
    ),
    Setting(
        "distill.ttl_hours",
        "MARM_DISTILL_TTL_HOURS",
        "int",
        "plain",
        "memory",
        "Distill lifetime (hours)",
        "How long a distill draft is kept.",
        168,
        min=1,
        max=8760,
    ),
    Setting(
        "llm.timeout_seconds",
        "MARM_LLM_TIMEOUT",
        "int",
        "plain",
        "llm",
        "Local model timeout (seconds)",
        "How long to wait for the local model.",
        120,
        min=1,
        max=3600,
    ),
    Setting(
        "logging.stdio_level",
        "MARM_STDIO_LOG_LEVEL",
        "choice",
        "plain",
        "logging",
        "STDIO log level",
        "How much the STDIO server writes to its log.",
        "INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    ),
)

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


@dataclass(frozen=True)
class EnvVar:
    name: str
    group: str
    default: str
    description: str


ENV_REFERENCE: tuple[EnvVar, ...] = (
    EnvVar(
        "MARM_PROJECT",
        "Server",
        "",
        "Project name for new memories. Defaults to the current folder name.",
    ),
    EnvVar(
        "MARM_PLATFORM",
        "Server",
        "",
        "Agent name recorded with memories. Detected from the environment when empty.",
    ),
    EnvVar(
        "MARM_RATE_LIMIT_RPM",
        "Rate limit",
        "80",
        "HTTP requests per minute per address. 0 disables the limit.",
    ),
    EnvVar(
        "RATE_LIMIT_WINDOW_SECONDS",
        "Rate limit",
        "60",
        "Length of the rate-limit window.",
    ),
    EnvVar(
        "RATE_LIMIT_BLOCK_SECONDS",
        "Rate limit",
        "30",
        "How long an address stays blocked after passing the limit.",
    ),
    EnvVar(
        "WRITE_QUEUE_ENABLED",
        "Write queue",
        "1",
        "Serialize memory writes through a queue. 1 is on, 0 is off.",
    ),
    EnvVar(
        "MAX_QUEUE_SIZE",
        "Write queue",
        "100",
        "Most writes the queue holds before refusing new ones.",
    ),
    EnvVar(
        "CONCEPT_AUTO_INDEX",
        "Concept index",
        "true",
        "Extract concepts from new memories automatically.",
    ),
    EnvVar(
        "CONCEPT_INDEX_DEBOUNCE_SECONDS",
        "Concept index",
        "30",
        "Quiet time after a write before concepts are extracted.",
    ),
    EnvVar(
        "CONCEPT_INDEX_BATCH_SIZE",
        "Concept index",
        "20",
        "Memories processed per concept extraction pass (1 to 500).",
    ),
    EnvVar(
        "GRAPH_AUTO_INDEX",
        "Code graph",
        "true",
        "Re-index changed projects automatically.",
    ),
    EnvVar(
        "GRAPH_AUTO_INDEX_DEBOUNCE_SECONDS",
        "Code graph",
        "2.0",
        "Quiet time after a file change before re-indexing (minimum 0.5).",
    ),
    EnvVar(
        "GRAPH_AUTO_INDEX_RECONCILE_SECONDS",
        "Code graph",
        "300",
        "How often indexed projects are checked for drift (minimum 60).",
    ),
    EnvVar(
        "CONSOLIDATION_THRESHOLD",
        "Memory",
        "0.92",
        "Similarity at or above which a new memory counts as a duplicate.",
    ),
    EnvVar(
        "COMPACTION_SIMILARITY_THRESHOLD",
        "Memory",
        "0.88",
        "Similarity needed for memories to be compaction candidates.",
    ),
    EnvVar(
        "COMPACTION_TRIGGER_COUNT",
        "Memory",
        "5",
        "New memories in a session before compaction is suggested. The profile can change the default.",
    ),
    EnvVar(
        "COMPACTION_MIN_CLUSTER_SIZE",
        "Memory",
        "3",
        "Fewest memories in a compaction cluster.",
    ),
    EnvVar(
        "COMPACTION_STAGING_TTL_HOURS",
        "Memory",
        "168",
        "How long a staged compaction is kept before it expires.",
    ),
    EnvVar(
        "COMPACTION_AUTO_APPLY_INTERVAL_MINUTES",
        "Memory",
        "60",
        "How often automatic compaction runs.",
    ),
    EnvVar(
        "MARM_DISTILL_MAX_NUDGES",
        "Distill",
        "3",
        "Most reminders to save learnings per session.",
    ),
    EnvVar(
        "MARM_DISTILL_NUDGE_COOLDOWN",
        "Distill",
        "900",
        "Seconds between distill reminders.",
    ),
    EnvVar(
        "MARM_DISTILL_INPUT_CHARS",
        "Distill",
        "48000",
        "Most characters of a session sent to the local model when distilling.",
    ),
    EnvVar(
        "MARM_LLM_ENABLED",
        "Local model",
        "false",
        "Use the local model. A Console switch overrides this.",
    ),
    EnvVar(
        "MARM_LLM_URL",
        "Local model",
        "http://127.0.0.1:18080",
        "Address of the local model server.",
    ),
    EnvVar(
        "MARM_LLM_MODEL_ROOTS",
        "Local model",
        "",
        "Extra folders searched for model files, separated by the OS path separator.",
    ),
    EnvVar(
        "MARM_CODE_CONTEXT_DETAIL",
        "Code graph",
        "1",
        "Detail level of code context results, 1 to 3.",
    ),
    EnvVar(
        "MARM_DB_PATH", "Storage", "~/.marm/marm_memory.db", "Memory database file."
    ),
    EnvVar(
        "MARM_CONCEPT_DB_PATH",
        "Storage",
        "~/.marm/index/marm_index.db",
        "Concept graph database file.",
    ),
    EnvVar(
        "MARM_ANALYTICS_DB_PATH",
        "Storage",
        "~/.marm/marm_usage_analytics.db",
        "Usage analytics database file.",
    ),
    EnvVar(
        "MARM_STDIO_LOG_DIR", "Storage", "~/.marm/logs", "Folder for STDIO server logs."
    ),
    EnvVar(
        "MARM_CONSOLE_HOST",
        "Console",
        "127.0.0.1",
        "Address the Console binds to.",
    ),
    EnvVar("MARM_CONSOLE_PORT", "Console", "8002", "Port the Console listens on."),
    EnvVar(
        "MARM_MCP_URL",
        "Console",
        "",
        "Address the Console uses to reach the runtime. Defaults to the running runtime.",
    ),
    EnvVar(
        "MARM_DOCKER_REPOSITORY",
        "Docker",
        "lyellr88/marm-mcp-server",
        "Image repository used by Docker commands.",
    ),
    EnvVar(
        "FTS_QUERY_MODE",
        "Search",
        "or_nostop",
        "How keyword search combines words: or_nostop, or, or and.",
    ),
    EnvVar(
        "HYBRID_SEARCH_TEXT_WEIGHT",
        "Search",
        "0.05",
        "Weight of keyword matches when blended with semantic search.",
    ),
    EnvVar(
        "TEMPORAL_HALF_LIFE_DAYS",
        "Search",
        "30",
        "Days for the recency boost on a memory to halve.",
    ),
)


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
