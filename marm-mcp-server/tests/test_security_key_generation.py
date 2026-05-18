import string

from marm_mcp_server.utils.security import generate_api_key


def test_generated_api_keys_are_strong_shell_safe_and_unique():
    symbols = "-_+=.~@#%^&*"
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
