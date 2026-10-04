from __future__ import annotations

import json
import re
from collections.abc import Callable

SERVER_NAME = "marm-memory"


class _Unreadable(Exception):
    """A client file exists but is not in a shape MARM will edit."""


def _strip_jsonc(text: str) -> str:
    """Drop comments and trailing commas outside strings so OpenCode's JSONC files parse."""
    chunks: list[str] = []
    plain: list[str] = []

    def flush() -> None:
        chunks.append(re.sub(r",(\s*[}\]])", r"\1", "".join(plain)))
        plain.clear()

    i, n = 0, len(text)
    while i < n:
        if text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            flush()
            chunks.append(text[i : j + 1])
            i = j + 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        else:
            plain.append(text[i])
            i += 1
    flush()
    return "".join(chunks)


_MCP_HEADER = re.compile(
    r"^((?:mcp_servers|\"mcp_servers\"|'mcp_servers')[ \t]*):(.*)$"
)
_TRAILING_COMMENT = re.compile(r"\s+#.*$")
_LINES = re.compile(r"[^\n]*\n|[^\n]+")


def _yaml_emit(entry: dict, indent: int) -> list[str]:
    pad = " " * indent
    lines: list[str] = []
    for key, value in entry.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.extend(_yaml_emit(value, indent + 2))
        else:
            lines.append(f"{pad}{key}: {json.dumps(value)}")
    return lines


def _yaml_block(entry: dict, indent: int) -> list[str]:
    return [f"{' ' * indent}{SERVER_NAME}:", *_yaml_emit(entry, indent + 2)]


def _is_content(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _split_yaml(text: str) -> tuple[list[str], str]:
    return _LINES.findall(text), ("\r\n" if "\r\n" in text else "\n")


def _yaml_header(lines: list[str]) -> tuple[int, str, str, str] | None:
    """Line index, inline value, trailing comment, and the key text exactly as written."""
    for index, line in enumerate(lines):
        match = _MCP_HEADER.match(line.rstrip("\r\n"))
        if match:
            body = match.group(2)
            found = _TRAILING_COMMENT.search(body)
            comment = found.group(0) if found else ""
            rest = (body[: found.start()] if found else body).strip()
            return index, rest, comment, match.group(1)
    return None


def _region_end(lines: list[str], header: int) -> int:
    for index in range(header + 1, len(lines)):
        if _is_content(lines[index]) and _indent_of(lines[index]) == 0:
            return index
    return len(lines)


def _child_indent(lines: list[str], header: int, end: int) -> int:
    for index in range(header + 1, end):
        if _is_content(lines[index]):
            return _indent_of(lines[index]) or 2
    return 2


def _yaml_insert(text: str, entry: dict) -> str:
    lines, newline = _split_yaml(text)
    found = _yaml_header(lines)
    if found is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += newline
        head = [newline] if lines and lines[-1].strip() else []
        new = ["mcp_servers:", *_yaml_block(entry, 2)]
        return "".join([*lines, *head, *(line + newline for line in new)])
    header, rest, comment, key_text = found
    if rest and rest not in {"{}", "null", "~"}:
        raise _Unreadable("The mcp_servers section uses a layout MARM will not edit.")
    if not lines[header].endswith("\n"):
        lines[header] += newline
    indent = 2 if rest else _child_indent(lines, header, _region_end(lines, header))
    if rest:
        lines[header] = f"{key_text}:{comment}{newline}"
    block = [line + newline for line in _yaml_block(entry, indent)]
    return "".join([*lines[: header + 1], *block, *lines[header + 1 :]])


def _yaml_remove(text: str) -> str:
    lines, newline = _split_yaml(text)
    found = _yaml_header(lines)
    if found is None or found[1]:
        raise _Unreadable("The mcp_servers section uses a layout MARM will not edit.")
    header, _rest, comment, key_text = found
    end = _region_end(lines, header)
    indent = _child_indent(lines, header, end)
    name = re.escape(SERVER_NAME)
    key = re.compile(rf"^ {{{indent}}}(?:{name}|\"{name}\"|'{name}')[ \t]*:")
    start = next((i for i in range(header + 1, end) if key.match(lines[i])), None)
    if start is None:
        raise _Unreadable("The mcp_servers section uses a layout MARM will not edit.")
    stop = start + 1
    while stop < end and (
        not _is_content(lines[stop]) or _indent_of(lines[stop]) > indent
    ):
        stop += 1
    while stop > start + 1 and not _is_content(lines[stop - 1]):
        stop -= 1
    del lines[start:stop]
    end -= stop - start
    if not any(_is_content(line) for line in lines[header + 1 : end]):
        lines[header] = f"{key_text}: {{}}{comment}{newline}"
    return "".join(lines)


def _expected_yaml_doc(before: dict, entry: dict | None) -> dict:
    """The whole document as it should read after the edit: only MARM's entry differs."""
    servers = before.get("mcp_servers")
    servers = dict(servers) if isinstance(servers, dict) else {}
    if entry is None:
        servers.pop(SERVER_NAME, None)
    else:
        servers[SERVER_NAME] = entry
    return {**before, "mcp_servers": servers}


def _skip_ws(text: str, i: int) -> int:
    n = len(text)
    while i < n:
        if text[i] in " \t\r\n\ufeff":
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end == -1:
                raise _Unreadable("The file has an unterminated comment.")
            i = end + 2
        else:
            break
    return i


def _string_end(text: str, i: int) -> int:
    j = i + 1
    while j < len(text) and text[j] != '"':
        j += 2 if text[j] == "\\" else 1
    if j >= len(text):
        raise _Unreadable("The file has an unterminated string.")
    return j + 1


def _value_end(text: str, i: int) -> int:
    i = _skip_ws(text, i)
    if i >= len(text):
        raise _Unreadable("The file ends where a value was expected.")
    if text[i] == '"':
        return _string_end(text, i)
    if text[i] == "{":
        return _object_members(text, i)[1] + 1
    if text[i] == "[":
        i += 1
        while True:
            i = _skip_ws(text, i)
            if i >= len(text):
                raise _Unreadable("The file ends inside a list.")
            if text[i] == "]":
                return i + 1
            i = _skip_ws(text, _value_end(text, i))
            if i < len(text) and text[i] == ",":
                i += 1
    start = i
    while (
        i < len(text)
        and text[i] not in " \t\r\n,}]"
        and not text.startswith(("//", "/*"), i)
    ):
        i += 1
    if i == start:
        raise _Unreadable("The file has an unexpected token.")
    return i


def _object_members(
    text: str, start: int
) -> tuple[list[tuple[str, int, int, int]], int]:
    """Members as (key, key start, value start, value end), plus the closing brace index."""
    members: list[tuple[str, int, int, int]] = []
    i = start + 1
    while True:
        i = _skip_ws(text, i)
        if i >= len(text):
            raise _Unreadable("The file ends inside an object.")
        if text[i] == "}":
            return members, i
        if text[i] != '"':
            raise _Unreadable("The file has an unexpected token.")
        key_end = _string_end(text, i)
        try:
            key = json.loads(text[i:key_end])
        except json.JSONDecodeError as exc:
            raise _Unreadable("The file has an invalid key.") from exc
        colon = _skip_ws(text, key_end)
        if colon >= len(text) or text[colon] != ":":
            raise _Unreadable("The file has a key with no value.")
        value_start = _skip_ws(text, colon + 1)
        value_end = _value_end(text, value_start)
        members.append((key, i, value_start, value_end))
        i = _skip_ws(text, value_end)
        if i < len(text) and text[i] == ",":
            i += 1
        elif i >= len(text) or text[i] != "}":
            raise _Unreadable("The file has a missing comma.")


def _root_object(text: str) -> tuple[int, list[tuple[str, int, int, int]], int]:
    start = _skip_ws(text, 0)
    if start >= len(text) or text[start] != "{":
        raise _Unreadable("The file is not a JSON object.")
    members, close = _object_members(text, start)
    if _skip_ws(text, close + 1) != len(text):
        raise _Unreadable("The file has content after its object.")
    return start, members, close


def _line_start(text: str, i: int) -> int:
    return text.rfind("\n", 0, i) + 1


def _first_on_line(text: str, i: int) -> bool:
    return not text[_line_start(text, i) : i].strip()


def _line_indent(text: str, i: int) -> str:
    start = _line_start(text, i)
    end = text.find("\n", start)
    line = text[start : len(text) if end == -1 else end]
    return line[: len(line) - len(line.lstrip(" \t"))]


def _indents(text: str, obj_start: int, members: list) -> tuple[str, str, str]:
    """Indent of the object's line, of its members, and one indent step."""
    parent = _line_indent(text, obj_start)
    if members and _first_on_line(text, members[0][1]):
        member = _line_indent(text, members[0][1])
    else:
        member = parent + "  "
    unit = (
        member[len(parent) :]
        if member.startswith(parent) and len(member) > len(parent)
        else "  "
    )
    return parent, member, unit


def _entry_block(entry: dict, indent: str, unit: str, newline: str) -> str:
    lines = json.dumps(entry, indent=unit, ensure_ascii=False).split("\n")
    return f'"{SERVER_NAME}": ' + (newline + indent).join(lines)


def _add_member(
    text: str,
    obj_start: int,
    members: list,
    close: int,
    render: Callable[[str, str, str], str],
) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    parent, member, unit = _indents(text, obj_start, members)
    body = render(member, unit, newline)
    edits: list[tuple[int, str]] = []
    if _first_on_line(text, close):
        edits.append((_line_start(text, close), member + body + newline))
    else:
        edits.append((close, newline + member + body + newline + parent))
    if members and text[_skip_ws(text, members[-1][3])] != ",":
        edits.append((members[-1][3], ","))
    for pos, inserted in sorted(edits, key=lambda edit: edit[0], reverse=True):
        text = text[:pos] + inserted + text[pos:]
    return text


def _jsonc_put(text: str, key: str, entry: dict) -> str:
    if not text.strip():
        content = {key: {SERVER_NAME: entry}}
        return json.dumps(content, indent=2, ensure_ascii=False) + "\n"
    root_start, members, root_close = _root_object(text)
    servers = next((m for m in members if m[0] == key), None)
    if servers is None:

        def render_root(member: str, unit: str, newline: str) -> str:
            inner = member + unit
            block = _entry_block(entry, inner, unit, newline)
            return f'"{key}": {{' + newline + inner + block + newline + member + "}"

        return _add_member(text, root_start, members, root_close, render_root)
    if text[servers[2]] != "{":
        raise _Unreadable(f"The {key} setting is not an object.")
    inner_members, close = _object_members(text, servers[2])
    existing = next((m for m in inner_members if m[0] == SERVER_NAME), None)
    if existing is not None:
        newline = "\r\n" if "\r\n" in text else "\n"
        _parent, member, unit = _indents(text, servers[2], inner_members)
        block = _entry_block(entry, member, unit, newline)
        return text[: existing[2]] + block.split(": ", 1)[1] + text[existing[3] :]
    return _add_member(
        text,
        servers[2],
        inner_members,
        close,
        lambda member, unit, newline: _entry_block(entry, member, unit, newline),
    )


def _jsonc_remove(text: str, key: str) -> str:
    _root_start, members, _root_close = _root_object(text)
    servers = next((m for m in members if m[0] == key), None)
    if servers is None or text[servers[2]] != "{":
        raise _Unreadable(f"There is no {key} object to remove from.")
    inner, close = _object_members(text, servers[2])
    index = next((i for i, m in enumerate(inner) if m[0] == SERVER_NAME), None)
    if index is None:
        raise _Unreadable("MARM is not in this file.")
    _name, start, _value_start, end = inner[index]
    if (
        len(inner) == 1
        and not text[servers[2] + 1 : start].strip()
        and text[end:close].strip() in {"", ","}
    ):
        return text[: servers[2] + 1] + text[close:]
    edits: list[tuple[int, int]] = []
    after = _skip_ws(text, end)
    if after < len(text) and text[after] == ",":
        span_end = after + 1
    else:
        span_end = end
        if index > 0:
            comma = _skip_ws(text, inner[index - 1][3])
            edits.append((comma, comma + 1))
    line_end = text.find("\n", span_end)
    line_end = len(text) if line_end == -1 else line_end + 1
    if _first_on_line(text, start) and not text[span_end:line_end].strip():
        edits.append((_line_start(text, start), line_end))
    else:
        edits.append((start, span_end))
    for first, last in sorted(edits, reverse=True):
        text = text[:first] + text[last:]
    return text


def _jsonc_doc(text: str) -> dict:
    if not text.strip():
        return {}
    data = json.loads(_strip_jsonc(text.lstrip("\ufeff")))
    return data if isinstance(data, dict) else {}


def _expected_jsonc_doc(before: dict, key: str, entry: dict | None) -> dict:
    servers = before.get(key)
    servers = dict(servers) if isinstance(servers, dict) else {}
    if entry is None:
        servers.pop(SERVER_NAME, None)
    else:
        servers[SERVER_NAME] = entry
    return {**before, key: servers}
