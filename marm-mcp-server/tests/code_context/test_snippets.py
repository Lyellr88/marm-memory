import pathlib

from marm_mcp_server.services.code_context.snippets import dedent_block, read


def test_reads_inclusive_line_range(tmp_path: pathlib.Path):
    f = tmp_path / "m.py"
    f.write_text("a\nb\nc\nd\n")
    text, truncated = read(str(tmp_path), "m.py", 2, 3)
    assert text == "b\nc" and not truncated


def test_truncates_at_max_lines(tmp_path: pathlib.Path):
    (tmp_path / "big.py").write_text("\n".join(str(i) for i in range(200)))
    text, truncated = read(str(tmp_path), "big.py", 1, 200, max_lines=10)
    assert truncated and len(text.splitlines()) == 10


def test_end_past_eof_is_clamped(tmp_path: pathlib.Path):
    (tmp_path / "s.py").write_text("x\ny\n")
    text, _ = read(str(tmp_path), "s.py", 1, 999)
    assert text == "x\ny"


def test_missing_file_is_empty_not_an_exception(tmp_path: pathlib.Path):
    assert read(str(tmp_path), "nope.py", 1, 5) == ("", False)


def test_dedent_strips_common_indent_only():
    src = "    def f():\n        return 1\n"
    assert dedent_block(src) == "def f():\n    return 1"


def test_dedent_ignores_blank_lines_when_measuring():
    assert dedent_block("    a\n\n    b") == "a\n\nb"
