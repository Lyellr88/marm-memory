"""Import the synthetic Console demo memories into a loopback MARM runtime."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
PACK_ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--api-key-env", default="MARM_API_KEY")
    return parser.parse_args()


def loopback_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
        raise ValueError(
            "Demo imports are restricted to a local http:// loopback runtime."
        )
    return raw_url.rstrip("/")


def post_memory(base_url: str, payload: dict, api_key: str | None) -> None:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        f"{base_url}/internal/memories",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        if response.status != 201:
            raise RuntimeError(f"Unexpected response status: {response.status}")


def main() -> int:
    args = parse_args()
    try:
        base_url = loopback_url(args.base_url)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    api_key = os.environ.get(args.api_key_env)
    memories = json.loads((PACK_ROOT / "seed" / "memories.json").read_text("utf-8"))
    try:
        for memory in memories:
            post_memory(base_url, memory, api_key)
    except HTTPError as error:
        print(
            f"Import failed: HTTP {error.code}. Check that MARM is running and the local API key is available.",
            file=sys.stderr,
        )
        return 1
    except (OSError, URLError, RuntimeError) as error:
        print(f"Import failed: {error}", file=sys.stderr)
        return 1

    print(f"Imported {len(memories)} synthetic memories into the console-demo session.")
    print(
        "Next: index demo-project, then build concepts for console-demo in MARM Console."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
