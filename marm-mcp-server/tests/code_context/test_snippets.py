import pathlib

from marm_mcp_server.services.code_context.snippets import (
    MAX_LINE_CHARS,
    dedent_block,
    read,
)


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


def test_a_minified_single_line_file_is_not_read_whole(tmp_path: pathlib.Path):
    """One line of 5 MB must cost a bounded read, not 5 MB.

    This is the case the line-COUNT bound does not cover: a minified bundle is
    routinely a single physical line, so `start=1, end=1` asked for "one line"
    and got the entire file.
    """
    (tmp_path / "bundle.min.js").write_text("x" * 5_000_000)
    text, truncated = read(str(tmp_path), "bundle.min.js", 1, 1)
    assert len(text) <= MAX_LINE_CHARS
    assert truncated, "a clipped line must report itself as truncated"


def test_an_over_long_line_does_not_swallow_the_lines_after_it(
    tmp_path: pathlib.Path,
):
    """Draining the remainder must keep the line numbering correct.

    The bound discards the tail of a long line; if it discarded the newline too,
    every following line would shift up by one and the snippet would be taken
    from the wrong place.
    """
    (tmp_path / "m.py").write_text("a\n" + "y" * 9000 + "\nc\nd\n")
    text, truncated = read(str(tmp_path), "m.py", 3, 4)
    assert text == "c\nd"
    assert not truncated


def test_a_final_line_without_a_newline_is_not_called_truncated(
    tmp_path: pathlib.Path,
):
    """A short last line with no trailing newline looks like a clipped line.

    `readline(limit)` returns it without a newline in both cases, so only the
    drain tells them apart -- and reporting this one as truncated would be a
    false claim about the file.
    """
    (tmp_path / "s.py").write_text("a\nb")
    text, truncated = read(str(tmp_path), "s.py", 1, 2)
    assert text == "a\nb"
    assert not truncated


def test_dedent_strips_common_indent_only():
    src = "    def f():\n        return 1\n"
    assert dedent_block(src) == "def f():\n    return 1"


def test_dedent_ignores_blank_lines_when_measuring():
    assert dedent_block("    a\n\n    b") == "a\n\nb"
