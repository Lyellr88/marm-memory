import json
import tempfile
from pathlib import Path

from ..mcp_client_commands import parse_block, docker_stdio_cmds, main


def test_parse_block_basic():
    text = "\n=== Title ===\nWARNING: Check this\nline1\nline2"
    parsed = parse_block(text)
    assert parsed["title"] == "Title"
    assert parsed["warning"] == "Check this"
    assert "line1" in parsed["body"]


def test_docker_stdio_cmds_contains_both():
    class Info:
        docker_image = "img:latest"
        stdio_module = "marm_mcp_server.server_stdio"

    info = Info()
    out = docker_stdio_cmds(info)
    assert "Linux/macOS:" in out
    assert "Windows PowerShell:" in out
    assert "img:latest" in out
    assert "marm_mcp_server.server_stdio" in out


def test_output_file_written(tmp_path):
    # Run main to produce json and write to file
    out_file = tmp_path / "out.json"
    rc = main(["--mode-index", "2", "--client-index", "1", "--format", "json", "--output-file", str(out_file)])
    assert rc == 0
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["selected"]["client"] == "Codex"
