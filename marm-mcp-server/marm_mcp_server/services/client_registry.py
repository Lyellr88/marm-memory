from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .client_paths import (
    _antigravity_markers,
    _antigravity_path,
    _claude_desktop_markers,
    _claude_desktop_path,
    _cline_markers,
    _devin_markers,
    _devin_path,
    _markers,
    _opencode_path,
    _under_home,
    _vscode_config_path,
    _zed_path,
    cline_mcp_settings_path,
    hermes_home,
    opencode_home,
    zed_home,
)


@dataclass(frozen=True)
class ClientSpec:
    id: str
    label: str
    binary: str | None
    format: str  # "cli" | "json" | "toml" | "yaml"
    container_key: str | None
    user_path: Callable[[], Path | None]
    project_path: str | None
    markers: Callable[[], list[Path]]
    typed: bool = False
    http_key: str = "url"
    http_type: str = "http"
    stdio_type: str = "stdio"
    auth_ref: str | None = None


REGISTRY: dict[str, ClientSpec] = {
    spec.id: spec
    for spec in [
        ClientSpec(
            "claude",
            "Claude Code",
            "claude",
            "cli",
            "mcpServers",
            _under_home(".claude.json"),
            ".mcp.json",
            _markers(".claude"),
            typed=True,
            auth_ref="${MARM_API_KEY}",
        ),
        ClientSpec(
            "claude-desktop",
            "Claude Desktop",
            None,
            "json",
            "mcpServers",
            _claude_desktop_path,
            None,
            _claude_desktop_markers,
        ),
        ClientSpec(
            "cursor",
            "Cursor",
            "cursor",
            "json",
            "mcpServers",
            _under_home(".cursor", "mcp.json"),
            ".cursor/mcp.json",
            _markers(".cursor"),
            auth_ref="${env:MARM_API_KEY}",
        ),
        ClientSpec(
            "vscode",
            "VS Code",
            "code",
            "json",
            "servers",
            _vscode_config_path,
            ".vscode/mcp.json",
            lambda: [_vscode_config_path().parent],
            typed=True,
            auth_ref="${input:marm-api-key}",
        ),
        ClientSpec(
            "codex",
            "Codex CLI",
            "codex",
            "toml",
            None,
            _under_home(".codex", "config.toml"),
            ".codex/config.toml",
            _markers(".codex"),
        ),
        ClientSpec(
            "grok",
            "Grok Build",
            "grok",
            "toml",
            None,
            _under_home(".grok", "config.toml"),
            ".grok/config.toml",
            _markers(".grok"),
        ),
        ClientSpec(
            "hermes",
            "Hermes Agent",
            "hermes",
            "yaml",
            "mcp_servers",
            lambda: hermes_home() / "config.yaml",
            None,
            lambda: [hermes_home()],
            auth_ref="${MARM_API_KEY}",
        ),
        ClientSpec(
            "opencode",
            "OpenCode",
            "opencode",
            "json",
            "mcp",
            _opencode_path,
            "opencode.json",
            lambda: [opencode_home()],
            typed=True,
            http_type="remote",
            stdio_type="local",
            auth_ref="{env:MARM_API_KEY}",
        ),
        ClientSpec(
            "cline",
            "Cline",
            "cline",
            "json",
            "mcpServers",
            cline_mcp_settings_path,
            None,
            _cline_markers,
            typed=True,
            http_type="streamableHttp",
        ),
        ClientSpec(
            "antigravity",
            "Antigravity",
            "agy",
            "json",
            "mcpServers",
            _antigravity_path,
            ".agents/mcp_config.json",
            _antigravity_markers,
            http_key="serverUrl",
        ),
        ClientSpec(
            "qwen",
            "Qwen Code",
            "qwen",
            "json",
            "mcpServers",
            _under_home(".qwen", "settings.json"),
            ".qwen/settings.json",
            _markers(".qwen"),
            http_key="httpUrl",
        ),
        ClientSpec(
            "devin",
            "Devin",
            "devin",
            "json",
            "mcpServers",
            _devin_path,
            None,
            _devin_markers,
        ),
        ClientSpec(
            "kiro",
            "Kiro",
            "kiro",
            "json",
            "mcpServers",
            _under_home(".kiro", "settings", "mcp.json"),
            ".kiro/settings/mcp.json",
            _markers(".kiro"),
            auth_ref="${MARM_API_KEY}",
        ),
        ClientSpec(
            "zed",
            "Zed",
            "zed",
            "jsonc",
            "context_servers",
            _zed_path,
            None,
            lambda: [zed_home()],
        ),
    ]
}
