import os
import sys
from pathlib import Path

from ..services.key_management import _protect_key_file
from ..utils.security import generate_api_key

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
        key_persisted = False
        try:
            _MARM_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
            _MARM_ENV_PATH.write_text(f"MARM_API_KEY={marm_api_key}\n")
            try:
                key_protected = _protect_key_file(_MARM_ENV_PATH)
            except Exception:
                key_protected = False
            if key_protected:
                key_persisted = True
            else:
                try:
                    _MARM_ENV_PATH.unlink(missing_ok=True)
                except OSError as e:
                    print(
                        "WARNING: API key file protection failed and the insecure "
                        f"file could not be removed: {_MARM_ENV_PATH}: {e}. Remove "
                        "it immediately. The generated API key remains active in "
                        "memory for this process only; do not rely on the insecure "
                        "file surviving a restart. Set MARM_API_KEY explicitly in "
                        "the environment.",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "WARNING: API key file protection failed. The API key is being "
                        "kept in memory only and will not survive a restart. Set "
                        "MARM_API_KEY explicitly in the environment.",
                        file=sys.stderr,
                    )
        except Exception as e:
            print(f"WARNING: Could not save API key to {_MARM_ENV_PATH}: {e}")

        print()
        print(
            "MARM: SERVER_HOST=0.0.0.0 detected — API key auto-generated (first start)."
        )
        if key_persisted:
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
        else:
            print("Set MARM_API_KEY explicitly and restart to connect.")
        print()

    return marm_api_key
