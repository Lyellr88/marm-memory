import os
import sys
from pathlib import Path

from ..utils.security import generate_api_key, restrict_windows_file_to_current_user

_MARM_ENV_PATH = Path.home() / ".marm" / ".env"

# OS keychain service/username pair (keyring abstracts across Windows
# Credential Manager, macOS Keychain, and Linux Secret Service).
_KEYRING_SERVICE = "marm-mcp"
_KEYRING_USERNAME = "api-key"


def _file_link(path: Path) -> str:
    try:
        uri = path.as_uri()
        return f"\033]8;;{uri}\033\\{path}\033]8;;\033\\"
    except Exception:
        return str(path)


def _load_key_from_keyring() -> str:
    """Read MARM_API_KEY from the OS keychain if a keyring backend exists."""
    try:
        import keyring

        value = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        return value or ""
    except Exception:
        # NoKeyringError (headless Linux), missing dependency, or backend failure:
        # fall back to the existing .env behaviour.
        return ""


def _save_key_to_keyring(api_key: str) -> bool:
    """Persist the API key to the OS keychain. Returns False on failure."""
    try:
        import keyring

        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, api_key)
        return True
    except Exception:
        return False


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
    """Resolve MARM_API_KEY: env var, then OS keychain, then ~/.marm/.env,
    then auto-generate and persist one when server_host is 0.0.0.0 and no key
    was found. Keychain is attempted first for the persisted lookup; the
    plaintext .env file remains the backward-compatible fallback."""
    marm_api_key = os.environ.get("MARM_API_KEY", "")

    if server_host == "0.0.0.0" and not marm_api_key:
        marm_api_key = _load_key_from_keyring()
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
        keychain_ok = False
        try:
            keychain_ok = _save_key_to_keyring(marm_api_key)
        except Exception as e:
            print(f"WARNING: Could not save API key to OS keychain: {e}")

        if not keychain_ok:
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
        if keychain_ok:
            print("Saved to: OS keychain (Windows Credential Manager / macOS Keychain / Secret Service)")
            print("The key is not written to any plaintext file.")
        else:
            print(f"Saved to: {_file_link(_MARM_ENV_PATH)}")
        print()
        print(
            "Add this to your MCP client (replace YOUR_KEY with the key from the file above):"
        )
        print(
            '  claude mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer YOUR_KEY"'
        )
        print()
        if keychain_ok:
            print("On subsequent starts the key loads silently from the OS keychain.")
        else:
            print("On subsequent starts the key loads silently from the file above.")
        print()

    return marm_api_key
