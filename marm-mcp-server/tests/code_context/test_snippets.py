import builtins
import pathlib
from unittest import mock

from marm_mcp_server.services.code_context.snippets import (
    MAX_LINE_CHARS,
    MAX_SCAN_CHARS,
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


def test_a_huge_line_before_the_range_does_not_scan_the_whole_file(
    tmp_path: pathlib.Path,
):
    """Draining an over-long line must not cost the whole file.

    The per-line bound caps what is KEPT, not what is WALKED: skipping past a
    minified line to reach line 2 still read every byte of it. `read()` runs
    synchronously inside an async request, so that walk is the event loop's.
    """
    (tmp_path / "m.py").write_text("z" * (MAX_SCAN_CHARS * 4) + "\nwanted\n")
    text, truncated = read(str(tmp_path), "m.py", 2, 2)
    assert truncated, "giving up on the scan must be reported"
    assert text == "", (
        "line 2 was never reached: the newline ending line 1 was never read, so "
        "anything returned here would be a fragment of line 1 mislabelled as "
        "line 2 -- empty is the only honest answer"
    )


def test_an_unfinished_line_never_yields_lines_numbered_from_the_wrong_place(
    tmp_path: pathlib.Path,
):
    """Stopping is the only honest option once the newline was never reached.

    If the read gave up mid-line and then carried on counting, the next line it
    saw would be numbered one too low and the snippet would come from the wrong
    part of the file -- worse than returning nothing, because it looks right.
    """
    huge = "a" * (MAX_SCAN_CHARS * 2)
    (tmp_path / "m.py").write_text(f"{huge}\nsecond\nthird\nfourth\n")
    text, truncated = read(str(tmp_path), "m.py", 1, 4)
    assert truncated
    assert "second" not in text and "third" not in text and "fourth" not in text
    assert len(text) <= MAX_LINE_CHARS, "only the bounded first line may come back"


def test_a_selected_clipped_line_is_not_walked_to_its_end(tmp_path: pathlib.Path):
    """Once nothing after a line is wanted, the line must not be walked.

    Returning `MAX_LINE_CHARS` of a huge minified line only needs those
    characters plus one more to tell a clipped line from the file's last line.
    Draining to the next newline is pure cost on the event loop, and the scan
    budget caps it rather than removing it.

    Measured by counting characters actually read, which is the only way to see
    the difference -- the returned value is identical either way.
    """
    size = 5_000_000
    (tmp_path / "bundle.min.js").write_text("x" * size)
    read_chars = 0
    real_open = builtins.open

    def counting_open(*args, **kwargs):
        handle = real_open(*args, **kwargs)
        real_readline, real_read = handle.readline, handle.read

        def readline(*a, **k):
            nonlocal read_chars
            out = real_readline(*a, **k)
            read_chars += len(out)
            return out

        def rd(*a, **k):
            nonlocal read_chars
            out = real_read(*a, **k)
            read_chars += len(out)
            return out

        handle.readline, handle.read = readline, rd
        return handle

    with mock.patch.object(builtins, "open", counting_open):
        text, truncated = read(str(tmp_path), "bundle.min.js", 1, 1)

    assert truncated and len(text) <= MAX_LINE_CHARS
    assert read_chars <= MAX_LINE_CHARS + 1, (
        f"read {read_chars} characters to return {len(text)}: the line was "
        f"walked although nothing after it was wanted"
    )


def test_dedent_strips_common_indent_only():
    src = "    def f():\n        return 1\n"
    assert dedent_block(src) == "def f():\n    return 1"


def test_dedent_ignores_blank_lines_when_measuring():
    assert dedent_block("    a\n\n    b") == "a\n\nb"
