"""Allowlist, atomic save, env overlay, and source reporting for ~/.marm/settings.json."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from marm_mcp_server.config import user_settings


def _key_management():
    """Resolve at call time: other tests replace this module, so a bound import goes stale."""
    return importlib.import_module("marm_mcp_server.services.key_management")


ALL_ENV = [s.env for s in user_settings.SETTINGS] + [
    user_settings.SHADOW_ENV,
    "MARM_TRANSPORT",
]


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name in ALL_ENV:
        # setenv first so teardown also removes a var the overlay creates later.
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    monkeypatch.delenv("MARM_SETTINGS_PATH", raising=False)
    monkeypatch.setattr(user_settings, "_home", lambda: tmp_path)
    monkeypatch.setattr(user_settings, "_in_container", lambda: False)
    return tmp_path


def write_settings(home, data) -> None:
    (home / ".marm").mkdir(exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data)
    (home / ".marm" / "settings.json").write_text(text, encoding="utf-8")


def item(described: dict, key: str) -> dict:
    return next(i for g in described["groups"] for i in g["items"] if i["key"] == key)


def test_registry_is_the_spec_allowlist() -> None:
    assert {s.key: s.env for s in user_settings.SETTINGS} == {
        "server.port": "SERVER_PORT",
        "server.expose_network": "SERVER_HOST",
        "auth.require_key": "MARM_API_KEY",
        "search.semantic": "SEMANTIC_SEARCH_ENABLED",
        "graph.enabled": "GRAPH_ENABLED",
        "graph.auto_index_mode": "GRAPH_AUTO_INDEX_MODE",
        "compaction.enabled": "COMPACTION_ENABLED",
        "compaction.auto_apply": "COMPACTION_AUTO_APPLY_ENABLED",
        "compaction.min_age_hours": "COMPACTION_MIN_AGE_HOURS",
        "consolidation.enabled": "CONSOLIDATION_ENABLED",
        "distill.nudge": "MARM_DISTILL_NUDGE",
        "distill.ttl_hours": "MARM_DISTILL_TTL_HOURS",
        "llm.timeout_seconds": "MARM_LLM_TIMEOUT",
        "logging.stdio_level": "MARM_STDIO_LOG_LEVEL",
    }


def test_saved_value_beats_shell_env(home, monkeypatch) -> None:
    monkeypatch.setenv("SERVER_PORT", "9000")
    write_settings(home, {"server": {"port": 8123}})

    user_settings.apply_overlay()

    assert os.environ["SERVER_PORT"] == "8123"


@pytest.mark.parametrize(
    ("key", "on", "off"),
    [
        ("search.semantic", "1", "0"),
        ("compaction.enabled", "1", "0"),
        ("compaction.auto_apply", "1", "0"),
        ("consolidation.enabled", "1", "0"),
        ("distill.nudge", "1", "0"),
        ("graph.enabled", "true", "false"),
        ("server.expose_network", "0.0.0.0", "127.0.0.1"),
    ],
)
def test_bool_encoding_matches_how_each_module_reads_it(home, key, on, off) -> None:
    setting = next(s for s in user_settings.SETTINGS if s.key == key)
    for value, expected in ((True, on), (False, off)):
        os.environ.pop(setting.env, None)
        os.environ.pop(user_settings.SHADOW_ENV, None)
        section, _, name = key.partition(".")
        write_settings(home, {section: {name: value}})
        user_settings.apply_overlay()
        assert os.environ[setting.env] == expected


def test_int_and_choice_are_written_as_plain_strings(home) -> None:
    write_settings(
        home,
        {
            "compaction": {"min_age_hours": 6},
            "graph": {"auto_index_mode": "fast"},
            "logging": {"stdio_level": "DEBUG"},
        },
    )
    user_settings.apply_overlay()
    assert os.environ["COMPACTION_MIN_AGE_HOURS"] == "6"
    assert os.environ["GRAPH_AUTO_INDEX_MODE"] == "fast"
    assert os.environ["MARM_STDIO_LOG_LEVEL"] == "DEBUG"


def test_semantic_off_is_read_as_off_by_the_settings_module(home) -> None:
    write_settings(home, {"search": {"semantic": False}})
    env = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "PYTHONIOENCODING": "utf-8",
    }
    for name in ALL_ENV:
        env.pop(name, None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import marm_mcp_server.config.settings as s; print(s.SEMANTIC_SEARCH_ENABLED)",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.stdout.strip().splitlines()[-1] == "False", result.stderr


def test_stdio_transport_never_gets_host_or_port(home, monkeypatch) -> None:
    monkeypatch.setenv("MARM_TRANSPORT", "stdio")
    monkeypatch.setenv("SERVER_HOST", "127.0.0.1")
    write_settings(
        home,
        {
            "server": {"port": 9999, "expose_network": True},
            "search": {"semantic": False},
        },
    )

    user_settings.apply_overlay()

    assert os.environ["SERVER_HOST"] == "127.0.0.1"
    assert "SERVER_PORT" not in os.environ
    assert os.environ["SEMANTIC_SEARCH_ENABLED"] == "0"


def test_container_never_gets_host_or_port(home, monkeypatch) -> None:
    monkeypatch.setattr(user_settings, "_in_container", lambda: True)
    monkeypatch.setenv("SERVER_HOST", "0.0.0.0")
    write_settings(home, {"server": {"port": 9999, "expose_network": False}})

    user_settings.apply_overlay()

    assert os.environ["SERVER_HOST"] == "0.0.0.0"
    assert "SERVER_PORT" not in os.environ


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[1, 2]",
        json.dumps({"server": {"port": "8001"}, "search": {"semantic": "yes"}}),
        json.dumps({"server": {"port": 70000}, "graph": {"auto_index_mode": "x"}}),
        json.dumps({"server": 5}),
    ],
)
def test_invalid_file_applies_nothing_and_never_raises(home, content) -> None:
    write_settings(home, content)
    before = dict(os.environ)

    user_settings.apply_overlay()

    assert dict(os.environ) == before


def test_one_bad_value_does_not_block_the_valid_ones(home) -> None:
    write_settings(home, {"server": {"port": 70000}, "compaction": {"enabled": True}})
    user_settings.apply_overlay()
    assert "SERVER_PORT" not in os.environ
    assert os.environ["COMPACTION_ENABLED"] == "1"


def test_overlay_is_idempotent_and_keeps_the_original(home, monkeypatch) -> None:
    monkeypatch.setenv("SERVER_PORT", "9000")
    write_settings(home, {"server": {"port": 8123}})

    user_settings.apply_overlay()
    first = dict(os.environ)
    user_settings.apply_overlay()

    assert dict(os.environ) == first
    assert json.loads(os.environ[user_settings.SHADOW_ENV]) == {"SERVER_PORT": "9000"}


def test_absent_env_is_recorded_as_none_in_shadow(home) -> None:
    write_settings(home, {"search": {"semantic": False}})
    user_settings.apply_overlay()
    assert json.loads(os.environ[user_settings.SHADOW_ENV]) == {
        "SEMANTIC_SEARCH_ENABLED": None
    }


def test_require_key_loads_managed_key_when_env_lacks_one(home, monkeypatch) -> None:
    monkeypatch.setattr(_key_management(), "read_managed_key", lambda: "managed-secret")
    write_settings(home, {"auth": {"require_key": True}})

    user_settings.apply_overlay()

    assert os.environ["MARM_API_KEY"] == "managed-secret"


def test_require_key_keeps_an_explicit_env_key(home, monkeypatch) -> None:
    monkeypatch.setenv("MARM_API_KEY", "explicit")

    def boom() -> str:
        raise AssertionError("managed key must not be read when env has one")

    monkeypatch.setattr(_key_management(), "read_managed_key", boom)
    write_settings(home, {"auth": {"require_key": True}})

    user_settings.apply_overlay()

    assert os.environ["MARM_API_KEY"] == "explicit"


def test_require_key_without_a_managed_key_creates_nothing(home, monkeypatch) -> None:
    monkeypatch.setattr(_key_management(), "read_managed_key", lambda: "")
    write_settings(home, {"auth": {"require_key": True}})

    user_settings.apply_overlay()

    assert "MARM_API_KEY" not in os.environ
    assert sorted(p.name for p in (home / ".marm").iterdir()) == ["settings.json"]


def test_require_key_false_leaves_the_env_alone(home, monkeypatch) -> None:
    monkeypatch.setattr(_key_management(), "read_managed_key", lambda: "managed-secret")
    write_settings(home, {"auth": {"require_key": False}})
    user_settings.apply_overlay()
    assert "MARM_API_KEY" not in os.environ


def test_saved_require_key_false_is_reported_on_when_the_shell_sets_a_key(
    home, monkeypatch
) -> None:
    monkeypatch.setenv("MARM_API_KEY", "explicit")
    write_settings(home, {"auth": {"require_key": False}})

    user_settings.apply_overlay()
    require_key = item(user_settings.describe(), "auth.require_key")

    assert os.environ["MARM_API_KEY"] == "explicit"
    assert (require_key["value"], require_key["source"]) == (True, "env")
    assert "always required" in require_key["help"]
    assert "explicit" not in json.dumps(require_key)


def test_save_validates_merges_and_keeps_the_docker_section(home) -> None:
    write_settings(
        home,
        {
            "docker": {"port": 8002, "tag": "latest"},
            "server": {"port": 8001},
            "unrelated": {"keep": [1, 2]},
        },
    )

    saved = user_settings.save(
        {"search.semantic": False, "compaction.min_age_hours": 12}
    )

    on_disk = json.loads((home / ".marm" / "settings.json").read_text("utf-8"))
    assert on_disk == {
        "docker": {"port": 8002, "tag": "latest"},
        "server": {"port": 8001},
        "unrelated": {"keep": [1, 2]},
        "search": {"semantic": False},
        "compaction": {"min_age_hours": 12},
    }
    assert saved == {
        "server.port": 8001,
        "search.semantic": False,
        "compaction.min_age_hours": 12,
    }
    assert [p.name for p in (home / ".marm").iterdir()] == ["settings.json"]


@pytest.mark.parametrize(
    "values",
    [
        {"unknown.key": 1},
        {"server.port": 0},
        {"server.port": 65536},
        {"server.port": "8001"},
        {"server.port": True},
        {"search.semantic": 1},
        {"search.semantic": "true"},
        {"graph.auto_index_mode": "turbo"},
        {"logging.stdio_level": "debug"},
        {"distill.ttl_hours": 0},
        {"docker.port": 1},
    ],
)
def test_save_rejects_bad_input_and_writes_nothing(home, values) -> None:
    write_settings(home, {"server": {"port": 8001}})
    before = (home / ".marm" / "settings.json").read_text("utf-8")

    with pytest.raises(user_settings.SettingsError):
        user_settings.save({"search.semantic": False, **values})

    assert (home / ".marm" / "settings.json").read_text("utf-8") == before


def test_save_refuses_to_clobber_a_corrupt_file(home) -> None:
    write_settings(home, "{corrupt")
    with pytest.raises(user_settings.SettingsError):
        user_settings.save({"search.semantic": False})
    assert (home / ".marm" / "settings.json").read_text("utf-8") == "{corrupt"


def test_failed_atomic_replace_leaves_no_tmp_and_the_old_file(
    home, monkeypatch
) -> None:
    write_settings(home, {"server": {"port": 8001}})
    before = (home / ".marm" / "settings.json").read_text("utf-8")

    def locked(src, dst):
        raise PermissionError("locked")

    monkeypatch.setattr(user_settings.os, "replace", locked)
    with pytest.raises(PermissionError):
        user_settings.save({"server.port": 9000})

    assert [p.name for p in (home / ".marm").iterdir()] == ["settings.json"]
    assert (home / ".marm" / "settings.json").read_text("utf-8") == before


def test_describe_reports_source_for_saved_env_and_default(home, monkeypatch) -> None:
    monkeypatch.setenv("GRAPH_AUTO_INDEX_MODE", "full")
    monkeypatch.setenv("SERVER_PORT", "9000")
    write_settings(home, {"server": {"port": 8123}})

    described = user_settings.describe()

    port = item(described, "server.port")
    assert (port["value"], port["source"], port["overrides_env"]) == (
        8123,
        "saved",
        True,
    )
    mode = item(described, "graph.auto_index_mode")
    assert (mode["value"], mode["source"], mode["overrides_env"]) == (
        "full",
        "env",
        False,
    )
    semantic = item(described, "search.semantic")
    assert (semantic["value"], semantic["source"], semantic["default"]) == (
        True,
        "default",
        True,
    )
    assert described["path"] == str(home / ".marm" / "settings.json")
    assert all(i["live"] is False for g in described["groups"] for i in g["items"])
    assert item(described, "server.port")["min"] == 1
    assert item(described, "graph.auto_index_mode")["choices"] == [
        "full",
        "moderate",
        "fast",
    ]


def test_describe_decodes_env_per_encoding(home, monkeypatch) -> None:
    monkeypatch.setenv("SEMANTIC_SEARCH_ENABLED", "0")
    monkeypatch.setenv("GRAPH_ENABLED", "false")
    monkeypatch.setenv("SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("MARM_API_KEY", "x")
    monkeypatch.setenv("SERVER_PORT", "not-a-number")

    described = user_settings.describe()

    assert item(described, "search.semantic")["value"] is False
    assert item(described, "graph.enabled")["value"] is False
    assert item(described, "server.expose_network")["value"] is True
    assert item(described, "auth.require_key")["value"] is True
    port = item(described, "server.port")
    assert (port["value"], port["source"]) == (8001, "default")


def test_shadowed_originals_survive_a_child_process(home, monkeypatch) -> None:
    monkeypatch.setenv("GRAPH_AUTO_INDEX_MODE", "full")
    write_settings(
        home,
        {"graph": {"auto_index_mode": "fast"}, "search": {"semantic": False}},
    )
    user_settings.apply_overlay()
    parent = user_settings.describe()

    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    program = (
        "import json; from marm_mcp_server.config import user_settings as u;"
        "print(json.dumps(u.describe()))"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    child = json.loads(result.stdout.strip().splitlines()[-1])

    for described in (parent, child):
        mode = item(described, "graph.auto_index_mode")
        assert (mode["value"], mode["source"], mode["overrides_env"]) == (
            "fast",
            "saved",
            True,
        )
        semantic = item(described, "search.semantic")
        assert (semantic["value"], semantic["source"], semantic["overrides_env"]) == (
            False,
            "saved",
            False,
        )


def test_setting_removed_from_file_is_undone_on_the_next_overlay(
    home, monkeypatch
) -> None:
    monkeypatch.setenv("SEMANTIC_SEARCH_ENABLED", "1")
    write_settings(home, {"search": {"semantic": False}})
    user_settings.apply_overlay()
    assert os.environ["SEMANTIC_SEARCH_ENABLED"] == "0"

    write_settings(home, {})
    user_settings.apply_overlay()

    assert os.environ["SEMANTIC_SEARCH_ENABLED"] == "1"
    assert user_settings.SHADOW_ENV not in os.environ


def test_turning_require_key_off_removes_the_overlaid_key(home, monkeypatch) -> None:
    monkeypatch.setattr(_key_management(), "read_managed_key", lambda: "managed-secret")
    write_settings(home, {"auth": {"require_key": True}})
    user_settings.apply_overlay()
    assert os.environ["MARM_API_KEY"] == "managed-secret"

    write_settings(home, {"auth": {"require_key": False}})
    user_settings.apply_overlay()

    assert "MARM_API_KEY" not in os.environ


def test_stdio_child_keeps_its_forced_host_when_parent_exposed_network(home) -> None:
    write_settings(home, {"server": {"expose_network": True}})
    user_settings.apply_overlay()
    assert os.environ["SERVER_HOST"] == "0.0.0.0"

    os.environ["SERVER_HOST"] = "127.0.0.1"
    os.environ["MARM_TRANSPORT"] = "stdio"
    write_settings(home, {})
    user_settings.apply_overlay()

    assert os.environ["SERVER_HOST"] == "127.0.0.1"


def test_load_docker_defaults_match_docker_run_options(home) -> None:
    from marm_mcp_server.services.docker_commands import DockerRunOptions

    config = user_settings.load_docker()
    options = DockerRunOptions()

    assert config == {
        "port": options.port,
        "tag": options.tag,
        "data_dir": str(home / ".marm"),
        "repos": [],
        "memory": options.memory,
        "cpus": options.cpus,
        "expose_network": options.expose_network,
        "profile": options.profile,
        "rate_limit_rpm": options.rate_limit_rpm,
    }


def test_save_docker_round_trips_and_leaves_the_allowlist_alone(home) -> None:
    write_settings(
        home,
        {"server": {"port": 9100}, "search": {"semantic": False}, "extra": {"a": 1}},
    )

    saved = user_settings.save_docker(
        {
            "port": 9002,
            "tag": "2.55.0",
            "data_dir": str(home / "marm-data"),
            "repos": [str(home / "repo")],
            "memory": "2g",
            "cpus": "1.5",
            "expose_network": True,
            "profile": "swarm",
            "rate_limit_rpm": 0,
        }
    )

    on_disk = json.loads((home / ".marm" / "settings.json").read_text("utf-8"))
    assert saved == on_disk["docker"] == user_settings.load_docker()
    assert saved["rate_limit_rpm"] == 0
    assert on_disk["server"] == {"port": 9100}
    assert on_disk["search"] == {"semantic": False}
    assert on_disk["extra"] == {"a": 1}
    assert user_settings.load()["server.port"] == 9100
    assert not (home / ".marm" / "settings.json.tmp").exists()


def test_docker_section_is_never_overlaid_into_the_environment(home) -> None:
    user_settings.save_docker({"port": 9555, "profile": "trusted", "tag": "x"})
    before = dict(os.environ)

    user_settings.apply_overlay()

    assert dict(os.environ) == before


def test_save_allowlist_keeps_a_saved_docker_section(home) -> None:
    user_settings.save_docker({"port": 9555})

    user_settings.save({"server.port": 8100})

    assert user_settings.load_docker()["port"] == 9555


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"port": 0}, "docker.port"),
        ({"port": 65536}, "docker.port"),
        ({"port": "8001"}, "docker.port"),
        ({"port": True}, "docker.port"),
        ({"tag": ""}, "docker.tag"),
        ({"tag": "a b"}, "docker.tag"),
        ({"profile": "turbo"}, "docker.profile"),
        ({"rate_limit_rpm": -1}, "docker.rate_limit_rpm"),
        ({"rate_limit_rpm": "5"}, "docker.rate_limit_rpm"),
        ({"memory": "2 g"}, "docker.memory"),
        ({"cpus": "x" * 40}, "docker.cpus"),
        ({"repos": "not-a-list"}, "docker.repos"),
        ({"repos": [1]}, "docker.repos"),
        ({"data_dir": ""}, "docker.data_dir"),
        ({"data_dir": 5}, "docker.data_dir"),
        ({"expose_network": "yes"}, "docker.expose_network"),
        ({"nope": 1}, "Unknown docker setting"),
    ],
)
def test_save_docker_rejects_bad_values_and_writes_nothing(
    home, config, message
) -> None:
    with pytest.raises(user_settings.SettingsError, match=message):
        user_settings.save_docker(config)

    assert not (home / ".marm" / "settings.json").exists()


def test_save_docker_treats_empty_limits_as_unset(home) -> None:
    saved = user_settings.save_docker({"memory": "", "cpus": None})

    assert saved["memory"] is None
    assert saved["cpus"] is None


def test_load_docker_keeps_good_fields_and_defaults_bad_ones(home) -> None:
    write_settings(
        home, {"docker": {"port": "bad", "tag": "v9", "profile": "nope", "cpus": "2"}}
    )

    config = user_settings.load_docker()

    assert config["port"] == 8001
    assert config["profile"] == "standard"
    assert config["tag"] == "v9"
    assert config["cpus"] == "2"


@pytest.mark.parametrize("content", ["{broken", "[1]", json.dumps({"docker": 5})])
def test_load_docker_never_raises_on_a_bad_file(home, content) -> None:
    write_settings(home, content)

    assert user_settings.load_docker() == user_settings.docker_defaults()


def test_save_docker_refuses_to_overwrite_an_unreadable_file(home) -> None:
    write_settings(home, "{broken")

    with pytest.raises(user_settings.SettingsError, match="cannot be read"):
        user_settings.save_docker({"port": 9000})

    assert (home / ".marm" / "settings.json").read_text("utf-8") == "{broken"


def package_source() -> str:
    root = Path(user_settings.__file__).resolve().parents[1]
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in root.rglob("*.py")
        if path.name != "user_settings.py"
    )


def test_every_env_reference_name_is_read_somewhere_in_the_package() -> None:
    source = package_source()
    names = [var.name for var in user_settings.ENV_REFERENCE]
    missing = [n for n in names if f'"{n}"' not in source and f"'{n}'" not in source]
    assert missing == []
    assert len(names) == len(set(names))


def test_env_reference_does_not_repeat_an_allowlisted_variable() -> None:
    allowlisted = {s.env for s in user_settings.SETTINGS}
    assert not allowlisted & {var.name for var in user_settings.ENV_REFERENCE}


def test_env_reference_defaults_match_the_live_settings_module() -> None:
    from marm_mcp_server.config import settings

    defaults = {var.name: var.default for var in user_settings.ENV_REFERENCE}
    assert (
        float(defaults["CONSOLIDATION_THRESHOLD"]) == settings.CONSOLIDATION_THRESHOLD
    )
    assert (
        float(defaults["HYBRID_SEARCH_TEXT_WEIGHT"])
        == settings.HYBRID_SEARCH_TEXT_WEIGHT
    )
    assert defaults["FTS_QUERY_MODE"] == "or_nostop"
    assert int(defaults["MAX_QUEUE_SIZE"]) == 100


def test_env_reference_reports_current_value_and_source(home, monkeypatch) -> None:
    monkeypatch.setenv("MARM_RATE_LIMIT_RPM", "17")
    write_settings(home, {"server": {"port": 9001}})
    items = {i["name"]: i for i in user_settings.env_reference()}
    assert items["MARM_RATE_LIMIT_RPM"]["current"] == "17"
    assert items["MARM_RATE_LIMIT_RPM"]["source"] == "env"
    assert items["MARM_PROJECT"]["source"] == "default"
    assert items["SERVER_PORT"]["current"] == "9001"
    assert items["SERVER_PORT"]["source"] == "saved"
    assert items["SERVER_PORT"]["setting_key"] == "server.port"
    assert len([i for i in items.values() if i["setting_key"]]) == len(
        user_settings.SETTINGS
    )


def test_env_reference_never_exposes_the_api_key_value(home, monkeypatch) -> None:
    secret = "sk-marm-reference-secret"
    monkeypatch.setenv("MARM_API_KEY", secret)
    items = user_settings.env_reference()
    assert secret not in json.dumps(items)
    key = next(i for i in items if i["name"] == "MARM_API_KEY")
    assert key["current"] == "set" and key["default"] == "not set"
    monkeypatch.delenv("MARM_API_KEY")
    key = next(i for i in user_settings.env_reference() if i["name"] == "MARM_API_KEY")
    assert key["current"] == "not set"
