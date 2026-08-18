import string

from marm_mcp_server.utils.security import generate_api_key


def test_generated_api_keys_are_strong_shell_safe_and_unique():
    symbols = "-_+=.~@%^&*"
    alphabet = set(string.ascii_letters + string.digits + symbols)
    unsafe_shell_chars = set("$!`'\"\\<>")

    keys = {generate_api_key() for _ in range(50)}

    assert len(keys) == 50
    for key in keys:
        assert len(key) == 40
        assert set(key) <= alphabet
        assert not (set(key) & unsafe_shell_chars)
        assert any(char in string.ascii_uppercase for char in key)
        assert any(char in string.ascii_lowercase for char in key)
        assert any(char in string.digits for char in key)
        assert any(char in symbols for char in key)


def test_generated_api_keys_never_contain_a_hash():
    """A key is persisted unquoted to a .env-style file (config/api_key_
    bootstrap.py, services/key_management.py) and read back by parsers --
    including docker run --env-file, which has no quoting mechanism at all
    -- that treat an unquoted value's trailing "#..." as a comment. "#" was
    in the symbol alphabet until this was found: roughly 2 in 5 generated
    keys came back truncated on the very next read. Excluding it from the
    alphabet fixes every consumer of the persisted file at once, rather than
    requiring each writer to quote (which isn't safe for docker run
    --env-file, which does not strip quotes)."""
    keys = [generate_api_key() for _ in range(500)]
    assert all("#" not in key for key in keys)
