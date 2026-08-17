"""Static Docker/Compose config validation -- no Docker daemon required.

Unlike test_docker_transports.py's container-level tests (which skip
whenever a daemon or pre-built image isn't available -- true in this
sandbox, and structurally true in CI's validate-and-test job too, since it
runs before publish-docker-server ever builds the image), these tests read
the actual Dockerfile/docker-compose.yml/.dockerignore/Dockerfile.glama
content directly and always run. They catch the class of bug that doesn't
need a running container to exist: drifted labels, mismatched healthchecks
between Dockerfile and docker-compose.yml, a port that no longer matches
settings.py's default, etc.
"""

import re
from pathlib import Path

from marm_mcp_server.config.settings import SERVER_PORT, SERVER_VERSION
from marm_mcp_server.server import MCP_TOOL_OPERATIONS

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (REPO_ROOT / "Dockerfile").read_text()
DOCKERFILE_GLAMA = (REPO_ROOT / "Dockerfile.glama").read_text()
COMPOSE = (REPO_ROOT / "docker-compose.yml").read_text()
DOCKERIGNORE = (REPO_ROOT / ".dockerignore").read_text()
PYPROJECT = (REPO_ROOT / "pyproject.toml").read_text()


def _pyproject_version() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT, re.MULTILINE)
    assert match, "pyproject.toml has no version field"
    return match.group(1)


def _dockerfile_healthcheck_cmd() -> str:
    # [^\n]+ (not DOTALL-affected) stops the capture at the CMD line's own
    # newline -- a bare .+ with DOTALL applied to the whole pattern would
    # swallow everything to the end of the file, including LABELs/ENV/etc.
    match = re.search(r"HEALTHCHECK.*?\n\s*CMD\s+([^\n]+)", DOCKERFILE, re.DOTALL)
    assert match, "Dockerfile has no HEALTHCHECK CMD"
    return match.group(1).strip()


def _compose_healthcheck_cmd() -> str:
    match = re.search(r'test:\s*\["CMD",\s*"python",\s*"-c",\s*"(.+?)"\]', COMPOSE)
    assert match, "docker-compose.yml has no python healthcheck test command"
    return match.group(1).strip()


def test_dockerfile_declares_a_healthcheck():
    assert "HEALTHCHECK" in DOCKERFILE


def test_dockerfile_and_compose_healthchecks_stay_in_sync():
    """docker-compose.yml's own comment says this must mirror the Dockerfile's
    HEALTHCHECK -- the compose file can't install curl (removed to shrink the
    CBM binary's runtime network surface) so it duplicates the pure-Python
    check by hand instead of inheriting it. Nothing enforces that duplication
    stays correct except this test."""
    dockerfile_cmd = _dockerfile_healthcheck_cmd()
    compose_cmd = _compose_healthcheck_cmd()
    assert "urllib.request.urlopen" in dockerfile_cmd
    assert compose_cmd in dockerfile_cmd


def test_dockerfile_runs_as_non_root_user():
    assert re.search(r"^USER\s+marm\s*$", DOCKERFILE, re.MULTILINE), (
        "final image must drop to a non-root user before ENTRYPOINT"
    )
    # USER must appear before ENTRYPOINT, not just anywhere in the file.
    user_pos = DOCKERFILE.index("USER marm")
    entrypoint_pos = DOCKERFILE.index("ENTRYPOINT")
    assert user_pos < entrypoint_pos


def test_dockerfile_expose_matches_settings_default_port():
    match = re.search(r"^EXPOSE\s+(\d+)", DOCKERFILE, re.MULTILINE)
    assert match, "Dockerfile has no EXPOSE directive"
    assert int(match.group(1)) == SERVER_PORT


def test_compose_port_mapping_matches_dockerfile_expose():
    match = re.search(r'"(\d+):(\d+)"', COMPOSE)
    assert match, "docker-compose.yml has no port mapping"
    _host_port, container_port = match.groups()
    assert int(container_port) == SERVER_PORT


def test_compose_server_version_matches_runtime_settings():
    match = re.search(r"SERVER_VERSION=([^\s]+)", COMPOSE)
    assert match, "docker-compose.yml has no SERVER_VERSION env entry"
    assert match.group(1) == SERVER_VERSION


def test_dockerfile_label_tool_count_matches_registered_tools():
    """LABEL mcp.tools is a plain string someone has to remember to bump by
    hand every time a tool is added or removed -- nothing else keeps it
    honest. Catches exactly the kind of drift the concept-graph branch
    would introduce (12 -> 14) if the label isn't updated alongside it."""
    match = re.search(r'LABEL mcp\.tools="(\d+)"', DOCKERFILE)
    assert match, "Dockerfile has no LABEL mcp.tools"
    assert int(match.group(1)) == len(MCP_TOOL_OPERATIONS)


def test_dockerfile_label_version_matches_pyproject():
    match = re.search(
        r'LABEL org\.opencontainers\.image\.version="([^"]+)"', DOCKERFILE
    )
    assert match, "Dockerfile has no image.version LABEL"
    assert match.group(1) == _pyproject_version()


def test_dockerfile_is_multi_stage_and_discards_build_toolchain():
    """gcc/g++ are only needed to build wheels -- the final runtime stage
    must not carry them forward, or every pulled image pays their size cost
    for nothing."""
    stages = re.findall(r"^FROM\s+\S+(?:\s+AS\s+(\S+))?", DOCKERFILE, re.MULTILINE)
    assert len(stages) >= 2, "Dockerfile should be a multi-stage build"
    assert stages[0] == "builder"

    final_stage = DOCKERFILE.rsplit("\nFROM ", 1)[-1]
    assert "gcc" not in final_stage
    assert "g++" not in final_stage


def test_dockerfile_verifies_binary_checksum_before_use():
    """The pinned codebase-memory-mcp binary is fetched from a GitHub release
    at build time -- this must be checksum-verified before it's copied into
    the final image, not trusted blindly over the network."""
    assert "sha256sum -c" in DOCKERFILE
    assert "checksums.txt" in DOCKERFILE


def test_dockerfile_entrypoint_is_the_http_server():
    assert 'ENTRYPOINT ["python", "-m", "marm_mcp_server"]' in DOCKERFILE


def test_dockerfile_glama_entrypoint_is_stdio_not_http():
    """The lean glama image is STDIO-only by design (see requirements-glama.txt's
    absence of the HTTP-serving extras) -- it must never default to the HTTP
    server's CMD."""
    assert "server_stdio" in DOCKERFILE_GLAMA
    assert "marm_mcp_server.server_stdio" in DOCKERFILE_GLAMA


def test_dockerfile_glama_does_not_bake_in_graph_binary():
    """The glama build intentionally excludes the graph engine -- it should
    not carry the same binary-download/checksum machinery the main Dockerfile
    has, or it stops being the lean build it's meant to be."""
    assert "codebase-memory-mcp" not in DOCKERFILE_GLAMA
    assert "checksums.txt" not in DOCKERFILE_GLAMA


def test_compose_declares_resource_limits():
    assert "limits:" in COMPOSE
    assert "memory:" in COMPOSE
    assert "cpus:" in COMPOSE


def test_compose_mounts_marm_home_directory():
    assert "~/.marm:/home/marm/.marm" in COMPOSE


def test_dockerignore_excludes_git_and_python_caches():
    assert ".git/" in DOCKERIGNORE
    assert "__pycache__" in DOCKERIGNORE
    assert ".venv" in DOCKERIGNORE or "venv/" in DOCKERIGNORE


def test_dockerignore_excludes_database_files_but_not_source():
    """Database files must never be baked into an image (each container gets
    a fresh DB via the volume mount), but this must not accidentally also
    exclude real source directories that happen to share a name pattern."""
    assert "*.db" in DOCKERIGNORE
    for package_dir in ("marm_mcp_server", "marm_graph"):
        assert not re.search(rf"^{package_dir}/?\s*$", DOCKERIGNORE, re.MULTILINE), (
            f"{package_dir} must not be excluded from the build context"
        )


def test_dockerfile_healthcheck_uses_localhost_not_0_0_0_0():
    """SERVER_HOST=0.0.0.0 is what the process binds to (all interfaces);
    the healthcheck runs *inside* the same container and must probe
    localhost/127.0.0.1, not the bind-all address, which curl/urllib may not
    treat as a connectable target the same way."""
    healthcheck_cmd = _dockerfile_healthcheck_cmd()
    assert "0.0.0.0" not in healthcheck_cmd
    assert "localhost" in healthcheck_cmd or "127.0.0.1" in healthcheck_cmd


# ── graph engine pin ────────────────────────────────────────────────

_ENGINE_PIN = re.compile(r"^codebase-memory-mcp==([^\s]+)", re.MULTILINE)


def _engine_pins() -> dict[str, str]:
    """Every file that decides which graph engine actually gets installed."""
    sources = {
        "pyproject.toml": PYPROJECT,
        "requirements.txt": (REPO_ROOT / "requirements.txt").read_text(),
        "requirements-glama.txt": (REPO_ROOT / "requirements-glama.txt").read_text(),
    }
    pins = {}
    for name, text in sources.items():
        match = re.search(r'codebase-memory-mcp==([^"\s]+)', text)
        assert match, f"{name} does not pin codebase-memory-mcp"
        pins[name] = match.group(1)
    return pins


def test_graph_engine_pin_agrees_across_every_install_path():
    """A stale requirements file silently installs a different engine than the pin.

    Not cosmetic duplication: `Dockerfile.glama` installs requirements-glama.txt
    and then the package with --no-deps, and both CI workflows install
    requirements.txt before `pip install -e . --no-deps`. In both cases
    pyproject's pin is never resolved, so a requirements file left behind decides
    the engine version for a published image and for the test run that is
    supposed to validate it.
    """
    pins = _engine_pins()
    assert len(set(pins.values())) == 1, f"graph engine pins disagree: {pins}"


def test_pinned_engine_version_matches_the_schema_contract_marker():
    """PINNED_CBM_VERSION documents the version the router was validated against."""
    from marm_graph.config.settings import PINNED_CBM_VERSION

    assert _engine_pins()["pyproject.toml"] == PINNED_CBM_VERSION
