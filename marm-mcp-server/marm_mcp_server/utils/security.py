"""Cryptographic utilities — no imports from settings, no side effects."""

import secrets
import string


def generate_api_key(length: int = 40) -> str:
    """Generate a cryptographically strong API key with mixed character classes."""
    symbols = "-_+=.~@#%^&*"
    alphabet = string.ascii_letters + string.digits + symbols
    key = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(symbols),
    ]
    key += [secrets.choice(alphabet) for _ in range(length - 4)]
    secrets.SystemRandom().shuffle(key)
    return "".join(key)
