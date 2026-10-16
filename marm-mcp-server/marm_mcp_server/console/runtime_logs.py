from __future__ import annotations

import base64
import codecs
import hashlib
import json
from typing import Any

from ..core import runtime_manager

READ_LIMIT = 65536
HEAD_LIMIT = 256


def tail(cursor: str | None = None, lines: int = 200) -> dict[str, Any]:
    previous = None
    if cursor:
        try:
            if len(cursor) > 1024:
                raise ValueError
            previous = json.loads(base64.urlsafe_b64decode(cursor))
            if (
                not isinstance(previous, dict)
                or type(previous.get("offset")) is not int
                or previous["offset"] < 0
                or type(previous.get("head_size")) is not int
                or not 0 <= previous["head_size"] <= HEAD_LIMIT
                or not isinstance(previous.get("head"), str)
                or not isinstance(previous.get("identity"), list)
            ):
                raise ValueError
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("Invalid log cursor.") from exc
    lines = max(1, min(lines, 500))
    try:
        with runtime_manager.log_path().open("rb") as stream:
            import os

            stat = os.fstat(stream.fileno())
            size = stat.st_size
            head = stream.read(HEAD_LIMIT)
            identity = [stat.st_dev, stat.st_ino]
            rotated = bool(
                previous
                and (
                    previous["offset"] > size
                    or previous["identity"] != identity
                    or hashlib.sha256(head[: previous["head_size"]]).hexdigest()
                    != previous["head"]
                )
            )
            initial = previous is None or rotated
            start = (
                max(0, size - (READ_LIMIT - HEAD_LIMIT))
                if previous is None or rotated
                else previous["offset"]
            )
            stream.seek(start)
            raw = stream.read(READ_LIMIT - HEAD_LIMIT)
    except FileNotFoundError:
        return {"lines": [], "cursor": None, "rotated": False, "exists": False}
    full_read = len(raw) == READ_LIMIT - HEAD_LIMIT
    if initial and start and b"\n" in raw:
        skipped = raw.index(b"\n") + 1
        start += skipped
        raw = raw[skipped:]
    elif initial and start:
        while raw and raw[0] & 0xC0 == 0x80:
            raw = raw[1:]
            start += 1
    end = raw.rfind(b"\n") + 1
    truncated = not end and full_read
    if truncated:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        text = decoder.decode(raw, final=False)
        end = len(raw) - len(decoder.getstate()[0])
        output = [text[:3988] + " [truncated]"]
    else:
        complete = raw[:end].splitlines(keepends=True)
        if initial:
            chosen = complete[-lines:]
        else:
            chosen = complete[:lines]
            end = sum(len(line) for line in chosen)
        output = [
            line.decode("utf-8", errors="replace").rstrip("\r\n")[:4000]
            for line in chosen
        ]
    token = base64.urlsafe_b64encode(
        json.dumps(
            {
                "offset": start + end,
                "head": hashlib.sha256(head).hexdigest(),
                "head_size": len(head),
                "identity": identity,
            }
        ).encode()
    ).decode()
    return {"lines": output, "cursor": token, "rotated": rotated, "exists": True}
