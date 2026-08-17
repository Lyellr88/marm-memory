"""Resolve MARM_API_KEY at server startup: env var, then ~/.marm/.env, then
auto-generate and persist one when the server is bound to 0.0.0.0 with no key
set anywhere. Kept as a single function taking server_host as a parameter
(rather than importing SERVER_HOST back from config.settings) so settings.py
can call it without a circular import.
"""

import os
import sys
from pathlib import Path

from ..utils.security import generate_api_key, restrict_windows_file_to_current_user

_MARM_ENV_PATH = Path.home() / ".marm" / ".env"


def _file_link(path: Path) -> str:
    try:
        uri = path.as_uri()
        return f"\033]8;;{uri}\033\\{path}\033]8;;\033\\"
    except Exception:
        return str(path)


def _load_key_from_file() -> str:
    """Read MARM_API_KEY from ~/.marm/.env if present."""
    try:
        for raw_line in _MARM_ENV_PATH.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("MARM_API_KEY="):
                value = line.split("=", 1)[1].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                    value = value[1:-1]
                else:
                    value = value.split("#", 1)[0].strip()
                return value
    except Exception:
        pass
    return ""


def resolve_marm_api_key(server_host: str) -> str:
    """Resolve MARM_API_KEY: env var, then ~/.marm/.env, then auto-generate
    and persist one when server_host is 0.0.0.0 and no key was found."""
    marm_api_key = os.environ.get("MARM_API_KEY", "")

    if server_host == "0.0.0.0" and not marm_api_key:
        file_key = _load_key_from_file()
        if file_key:
            marm_api_key = file_key

    is_generate_key_cmd = "--generate-key" in sys.argv or sys.argv[1:3] == [
        "key",
        "generate",
    ]

    if server_host == "0.0.0.0" and not marm_api_key and not is_generate_key_cmd:
        marm_api_key = generate_api_key()
        try:
            _MARM_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
            _MARM_ENV_PATH.write_text(f"MARM_API_KEY={marm_api_key}\n")
            try:
                _MARM_ENV_PATH.chmod(0o600)
            except OSError:
                pass
            if sys.platform == "win32" and not restrict_windows_file_to_current_user(
                _MARM_ENV_PATH
            ):
                print(
                    f"WARNING: Could not restrict API key file: {_MARM_ENV_PATH}",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"WARNING: Could not save API key to {_MARM_ENV_PATH}: {e}")

        print()
        print(
            "MARM: SERVER_HOST=0.0.0.0 detected — API key auto-generated (first start)."
        )
        print(f"Saved to: {_file_link(_MARM_ENV_PATH)}")
        print()
        print(
            "Add this to your MCP client (replace YOUR_KEY with the key from the file above):"
        )
        print(
            '  claude mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer YOUR_KEY"'
        )
        print()
        print("On subsequent starts the key loads silently from the file above.")
        print()

    return marm_api_key
