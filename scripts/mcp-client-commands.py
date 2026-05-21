from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import argparse
import json
import os
import sys
import tomllib
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
MCP_DIR = ROOT / "marm-mcp-server"


@dataclass(frozen=True)
class ProjectInfo:
    package_name: str
    http_module: str
    stdio_module: str
    http_script: Optional[str]
    stdio_script: Optional[str]
    docker_image: str
    http_url: str = "http://localhost:8001/mcp"


def read_project_info() -> ProjectInfo:
    pyproject_path = MCP_DIR / "pyproject.toml"
    data = {}
    if pyproject_path.exists():
        try:
            data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    project = data.get("project", {})
    scripts = project.get("scripts", {})

    package_name = project.get("name", "marm-mcp-server")
    http_script = scripts.get("marm-mcp-server")
    stdio_script = scripts.get("marm-mcp-stdio")

    # Best-effort docker image (fallback): try Dockerfile label or default
    docker_image = "lyellr88/marm-mcp-server:latest"
    dockerfile = MCP_DIR / "Dockerfile"
    if dockerfile.exists():
        text = dockerfile.read_text(encoding="utf-8")
        # naive extraction of image name from an example RUN/push or comment
        for line in text.splitlines():
            if "image:" in line or "FROM" in line:
                # keep default; do not over-interpret
                break

    return ProjectInfo(
        package_name=package_name,
        http_module="marm_mcp_server",
        stdio_module="marm_mcp_server.server_stdio",
        http_script=("marm-mcp-server" if http_script else None),
        stdio_script=("marm-mcp-stdio" if stdio_script else None),
        docker_image=docker_image,
    )


def choose(prompt: str, options: list[str]) -> int:
    while True:
        print(prompt)
        for i, option in enumerate(options, start=1):
            print(f"{i}. {option}")
        raw = input("> ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print("Invalid choice. Try again.\n")


def block(title: str, body: str, warning: Optional[str] = None) -> str:
    lines = [f"\n=== {title} ==="]
    if warning:
        lines.append(f"WARNING: {warning}")
    lines.append(body.strip())
    return "\n".join(lines)


def docker_stdio_cmds(info: ProjectInfo) -> str:
    linux = f"docker run --rm -i -v ~/.marm:/home/marm/.marm {info.docker_image} python -m {info.stdio_module}"
    windows = f"docker run --rm -i -v %USERPROFILE%\\.marm:/home/marm/.marm {info.docker_image} python -m {info.stdio_module}"
    return "Linux/macOS:\n" + linux + "\n\nWindows PowerShell:\n" + windows


def parse_block(text: str) -> dict:
    lines = [l.rstrip() for l in text.splitlines()]
    title = None
    warning = None
    body_lines: list[str] = []
    i = 0
    # find title line like === Title ===
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("===") and line.endswith("==="):
            title = line.strip("=").strip()
            i += 1
            break
        i += 1
    # optional WARNING line
    if i < len(lines) and lines[i].strip().startswith("WARNING:"):
        warning = lines[i].strip()[len("WARNING:"):].strip()
        i += 1
    # rest is body
    while i < len(lines):
        body_lines.append(lines[i])
        i += 1
    body = "\n".join(body_lines).strip()
    return {"title": title or "", "warning": warning, "body": body}


def render_codex(mode: str, info: ProjectInfo) -> str:
    if "HTTP" in mode:
        body = []
        body.append("PowerShell:")
        if "Docker HTTP" in mode:
            body.append("$env:MARM_API_KEY = \"your-generated-key\"")
            body.append(
                f"codex mcp add marm-memory --url {info.http_url} --bearer-token-env-var MARM_API_KEY"
            )
            body.append("")
            body.append("TOML:")
            body.append("[mcp_servers.marm-memory]")
            body.append(f"url = \"{info.http_url}\"")
            body.append("enabled = true")
            body.append('bearer_token_env_var = "MARM_API_KEY"')
        else:
            body.append(f"codex mcp add marm-memory --url {info.http_url}")
            body.append("")
            body.append("TOML:")
            body.append("[mcp_servers.marm-memory]")
            body.append(f"url = \"{info.http_url}\"")
            body.append("enabled = true")
        return block("Codex - HTTP", "\n".join(body))

    # STDIO modes
    if "STDIO" in mode:
        if "Docker STDIO" in mode:
            docker_cmd = f"docker run --rm -i -v ~/.marm:/home/marm/.marm {info.docker_image} python -m {info.stdio_module}"
            return block("Codex - Docker STDIO", docker_cmd)

        if info.stdio_script:
            cmd = f"codex mcp add marm-memory-stdio -- {info.stdio_script}"
        else:
            cmd = f"codex mcp add marm-memory-stdio -- python -m {info.stdio_module}"
        return block("Codex - STDIO", cmd)

    return block("Codex", "Unsupported mode")


def render_claude(mode: str, info: ProjectInfo) -> str:
    if "HTTP" in mode:
        body = ["PowerShell:"]
        if "Docker HTTP" in mode:
            body.append("$env:MARM_API_KEY = \"your-generated-key\"")
            body.append(
                f"claude mcp add --transport http marm-memory {info.http_url} --header \"Authorization: Bearer $env:MARM_API_KEY\""
            )
        else:
            body.append(f"claude mcp add --transport http marm-memory {info.http_url}")
        body.append("")
        body.append("NOTE: Confirm `claude` CLI flags are unchanged in your client version.")
        return block("Claude Code - HTTP", "\n".join(body), warning=None)

    if "STDIO" in mode:
        if "Docker STDIO" in mode:
            docker_cmd = f"docker run --rm -i -v ~/.marm:/home/marm/.marm {info.docker_image} python -m {info.stdio_module}"
            return block("Claude Code - Docker STDIO", docker_cmd)

        if info.stdio_script:
            cmd = f"claude mcp add marm-memory-stdio -- {info.stdio_script}"
        else:
            cmd = f"claude mcp add marm-memory-stdio -- python -m {info.stdio_module}"
        return block("Claude Code - STDIO", cmd)

    return block("Claude Code", "Unsupported mode")


def render_gemini(mode: str, info: ProjectInfo) -> str:
    # Gemini CLI syntax varies; include a verification warning
    if "HTTP" in mode:
        # Use documented style: --transport http <name> <url>
        lines = [
            "PowerShell:",
        ]
        if "Docker HTTP" in mode:
            lines.append("$env:MARM_API_KEY = \"your-generated-key\"")
            lines.append(
                f"gemini mcp add --transport http marm-memory {info.http_url} --header \"Authorization: Bearer $env:MARM_API_KEY\""
            )
        else:
            lines.append(f"gemini mcp add --transport http marm-memory {info.http_url}")
        return block(
            "Gemini CLI - HTTP",
            "\n".join(lines),
            warning="VERIFY BEFORE PUBLISHING: Confirm Gemini CLI `mcp add` flags match your client version.",
        )

    # STDIO
    if "STDIO" in mode:
        # Local STDIO uses installed script or module; Docker STDIO uses docker run snippet
        if "Docker STDIO" in mode:
            docker_cmd = (
                f"docker run --rm -i -v ~/.marm:/home/marm/.marm {info.docker_image} python -m {info.stdio_module}"
            )
            return block("Gemini CLI - Docker STDIO", docker_cmd, warning="VERIFY BEFORE PUBLISHING: Confirm Docker image and entrypoint.")

        if info.stdio_script:
            cmd = f"gemini mcp add marm-memory-stdio -- {info.stdio_script}"
        else:
            cmd = f"gemini mcp add marm-memory-stdio -- python -m {info.stdio_module}"
        return block("Gemini CLI - STDIO", cmd, warning="VERIFY BEFORE PUBLISHING: Confirm Gemini STDIO syntax.")

    return block("Gemini CLI", "Unsupported mode")


def render_qwen(mode: str, info: ProjectInfo) -> str:
    if "HTTP" in mode:
        lines = ["PowerShell:"]
        if "Docker HTTP" in mode:
            lines.append("$env:MARM_API_KEY = \"your-generated-key\"")
            lines.append(
                f"qwen mcp add --transport http marm-memory {info.http_url} --header \"Authorization: Bearer $env:MARM_API_KEY\""
            )
        else:
            lines.append(f"qwen mcp add --transport http marm-memory {info.http_url}")
        return block("Qwen Code - HTTP", "\n".join(lines), warning="VERIFY BEFORE PUBLISHING: Confirm Qwen CLI flags.")

    if "STDIO" in mode:
        if "Docker STDIO" in mode:
            docker_cmd = f"docker run --rm -i -v ~/.marm:/home/marm/.marm {info.docker_image} python -m {info.stdio_module}"
            return block("Qwen Code - Docker STDIO", docker_cmd, warning="VERIFY BEFORE PUBLISHING: Confirm Docker image and entrypoint.")

        if info.stdio_script:
            cmd = f"qwen mcp add marm-memory-stdio -- {info.stdio_script}"
        else:
            cmd = f"qwen mcp add marm-memory-stdio -- python -m {info.stdio_module}"
        return block("Qwen Code - STDIO", cmd, warning="VERIFY BEFORE PUBLISHING: Confirm Qwen STDIO syntax.")

    return block("Qwen Code", "Unsupported mode")


def render_vscode(mode: str, info: ProjectInfo) -> str:
    cfg_path = ROOT / ".vscode" / "mcp.json"
    # Try to find matching entries in existing file
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            matches = {}

            def entry_has_auth(v: dict) -> bool:
                if not isinstance(v, dict):
                    return False
                if v.get("bearer_token_env_var") or v.get("token_env") or v.get("authorization") or v.get("Authorization"):
                    return True
                hdrs = v.get("headers") or v.get("header")
                if isinstance(hdrs, dict) and ("Authorization" in hdrs or "authorization" in hdrs):
                    return True
                return False

            # common places — prefer explicit mcp_servers then servers then root
            containers = [data.get("mcp_servers") or {}, data.get("servers") or {}, data]
            candidates = {}
            for container in containers:
                if not isinstance(container, dict):
                    continue
                for k, v in container.items():
                    if isinstance(v, dict):
                        url = v.get("url") or v.get("endpoint")
                        cmd = v.get("command") or v.get("stdio") or v.get("run")
                        if ("HTTP" in mode and url == info.http_url) or ("STDIO" in mode and cmd):
                            candidates[k] = v

            # If Docker HTTP, prefer entries that include auth headers/token
            if candidates:
                if "Docker HTTP" in mode:
                    auth_matches = {k: v for k, v in candidates.items() if entry_has_auth(v)}
                    if auth_matches:
                        return block("VS Code - Matching mcp.json entries (docker auth)", json.dumps(auth_matches, indent=2))
                else:
                    noauth = {k: v for k, v in candidates.items() if not entry_has_auth(v)}
                    if noauth:
                        return block("VS Code - Matching mcp.json entries", json.dumps(noauth, indent=2))
                return block("VS Code - Matching mcp.json entries", json.dumps(candidates, indent=2))
        except Exception:
            return block("VS Code", "Found .vscode/mcp.json but failed to parse JSON.")

    # Mode-specific example snippets
    if "HTTP" in mode:
        snippet = {
            "mcp_servers": {
                "marm-memory": {"url": info.http_url, "enabled": True}
            }
        }
        if "Docker HTTP" in mode:
            snippet["mcp_servers"]["marm-memory"]["bearer_token_env_var"] = "MARM_API_KEY"
        return block("VS Code - Example mcp.json", json.dumps(snippet, indent=2), warning="VERIFY BEFORE PUBLISHING: Adjust keys to match your extension version.")

    if "STDIO" in mode:
        cmd = info.stdio_script or f"python -m {info.stdio_module}"
        snippet = {"mcp_servers": {"marm-memory-stdio": {"command": cmd}}}
        if "Docker STDIO" in mode:
            docker_cmd = f"docker run --rm -i -v ~/.marm:/home/marm/.marm {info.docker_image} python -m {info.stdio_module}"
            return block("VS Code - Docker STDIO Example", docker_cmd, warning="VERIFY BEFORE PUBLISHING: Adjust docker run mounts as needed.")
        return block("VS Code - Example mcp.json (STDIO)", json.dumps(snippet, indent=2), warning="VERIFY BEFORE PUBLISHING: Adjust keys to match your extension version.")

    return block("VS Code", "Unsupported mode")


def render_cursor(mode: str, info: ProjectInfo) -> str:
    cfg_path = ROOT / ".cursor" / "mcp.json"
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            matches = {}
            # support Cursor's `mcpServers` top-level key
            containers = [data.get("mcpServers") or {}, data.get("servers") or {}, data]

            def entry_has_auth(v: dict) -> bool:
                if not isinstance(v, dict):
                    return False
                if v.get("token_env") or v.get("bearer_token_env_var") or v.get("authorization") or v.get("Authorization"):
                    return True
                hdrs = v.get("headers") or v.get("header")
                if isinstance(hdrs, dict) and ("Authorization" in hdrs or "authorization" in hdrs):
                    return True
                return False

            candidates = {}
            for container in containers:
                if not isinstance(container, dict):
                    continue
                for k, v in container.items():
                    if isinstance(v, dict):
                        url = v.get("url")
                        cmd = v.get("command") or v.get("stdio")
                        if ("HTTP" in mode and url == info.http_url) or ("STDIO" in mode and cmd):
                            candidates[k] = v

            if candidates:
                # Docker HTTP: prefer entries with auth headers/token
                if "Docker HTTP" in mode:
                    auth_matches = {k: v for k, v in candidates.items() if entry_has_auth(v)}
                    if auth_matches:
                        return block("Cursor - Matching .cursor/mcp.json entries (docker auth)", json.dumps(auth_matches, indent=2))
                else:
                    noauth = {k: v for k, v in candidates.items() if not entry_has_auth(v)}
                    if noauth:
                        return block("Cursor - Matching .cursor/mcp.json entries", json.dumps(noauth, indent=2))
                return block("Cursor - Matching .cursor/mcp.json entries", json.dumps(candidates, indent=2))
        except Exception:
            return block("Cursor", "Found .cursor/mcp.json but failed to parse JSON.")

    # Example shape uses Cursor's `mcpServers` key by default
    if "HTTP" in mode:
        body = {"mcpServers": {"marm-memory": {"url": info.http_url, "token_env": "MARM_API_KEY"}}}
        if "Docker HTTP" in mode:
            body["mcpServers"]["marm-memory"]["token_env"] = "MARM_API_KEY"
        return block("Cursor - Example mcp.json", json.dumps(body, indent=2), warning="VERIFY BEFORE PUBLISHING: Confirm Cursor config shape.")

    if "STDIO" in mode:
        if "Docker STDIO" in mode:
            docker_cmd = f"docker run --rm -i -v ~/.marm:/home/marm/.marm {info.docker_image} python -m {info.stdio_module}"
            return block("Cursor - Docker STDIO Example", docker_cmd, warning="VERIFY BEFORE PUBLISHING: Adjust docker run mounts as needed.")
        cmd = info.stdio_script or f"python -m {info.stdio_module}"
        body = {"mcpServers": {"marm-memory-stdio": {"command": cmd}}}
        return block("Cursor - Example mcp.json (STDIO)", json.dumps(body, indent=2), warning="VERIFY BEFORE PUBLISHING: Confirm Cursor config shape.")

    return block("Cursor", "Unsupported mode")


RENDERERS = {
    "Claude Code": render_claude,
    "Codex": render_codex,
    "Gemini CLI": render_gemini,
    "Qwen Code": render_qwen,
    "VS Code": render_vscode,
    "Cursor": render_cursor,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MARM MCP Client Command Generator")
    parser.add_argument("--mode-index", type=int, help="0-based mode index for non-interactive runs")
    parser.add_argument("--client-index", type=int, help="0-based client index for non-interactive runs")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format")
    parser.add_argument("--output-file", "-o", type=Path, help="Write output to this file")
    args = parser.parse_args(argv)

    info = read_project_info()
    modes = ["Local pip HTTP", "Local pip STDIO", "Docker HTTP with key", "Docker STDIO"]
    clients = ["Claude Code", "Codex", "Gemini CLI", "Qwen Code", "VS Code", "Cursor", "All"]

    if args.mode_index is not None and args.client_index is not None:
        if not (0 <= args.mode_index < len(modes)) or not (0 <= args.client_index < len(clients)):
            print("Invalid indices provided.")
            return 2
        mode = modes[args.mode_index]
        client = clients[args.client_index]
    else:
        mode = modes[choose("Choose deployment mode:", modes)]
        client = clients[choose("Choose client:", clients)]

    out_blocks: list[str] = []
    if client == "All":
        for c in clients[:-1]:
            renderer = RENDERERS.get(c)
            if renderer:
                out_blocks.append(renderer(mode, info))
            else:
                out_blocks.append(block(c, "No renderer implemented", warning=None))
    else:
        renderer = RENDERERS.get(client)
        if renderer:
            out_blocks.append(renderer(mode, info))
        else:
            out_blocks.append(block(client, "No renderer implemented", warning=None))

    print(f"Selected: {client} - {mode}")
    if args.format == "text":
        text_out = "\n".join(out_blocks)
        if args.output_file:
            args.output_file.write_text(text_out, encoding="utf-8")
            print(f"Wrote output to {args.output_file}")
        print(text_out)
    else:
        entries = [parse_block(b) for b in out_blocks]
        payload = {"selected": {"client": client, "mode": mode}, "entries": entries}
        json_out = json.dumps(payload, indent=2)
        if args.output_file:
            args.output_file.write_text(json_out, encoding="utf-8")
            print(f"Wrote JSON output to {args.output_file}")
        print(json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
