from __future__ import annotations

import argparse
import sys
from typing import Callable

from . import key_management


def dispatch_key(
    args: argparse.Namespace, *, write_generated_key: Callable[[], None]
) -> int:
    """Run one `key` subcommand; the caller owns how a generated key is shown."""
    if args.key_command == "generate":
        write_generated_key()
        return 0

    if args.key_command == "init":
        if args.remove_plaintext and not args.keychain:
            print(
                "--remove-plaintext only applies together with --keychain: the key "
                "has to be stored somewhere before the file can go.",
                file=sys.stderr,
            )
            return 2
        if args.keychain:
            keychain_key, keychain_problem = key_management.keychain_lookup()
            if keychain_problem:
                print(
                    f"Could not use the OS keychain: {keychain_problem}",
                    file=sys.stderr,
                )
                return 1
            if keychain_key and not key_management.read_managed_key_from_file(
                key_management.managed_key_path()
            ):
                print(
                    "Using existing MARM API key in the OS keychain "
                    f"({key_management.KEYRING_SERVICE}/"
                    f"{key_management.KEYRING_USERNAME})."
                )
                return 0
        path, created = key_management.initialize_managed_key()
        state = "Created" if created else "Using existing"
        print(f"{state} MARM API key file: {path}")
        if not args.keychain:
            return 0
        try:
            _key, removed = key_management.migrate_managed_key_to_keychain(
                path, remove_plaintext=args.remove_plaintext
            )
        except key_management.KeychainUnavailable as exc:
            print(
                f"Could not store the key in the OS keychain: {exc}",
                file=sys.stderr,
            )
            return 1
        print(
            "Stored the MARM API key in the OS keychain "
            f"({key_management.KEYRING_SERVICE}/{key_management.KEYRING_USERNAME})."
        )
        if removed:
            print(f"Removed the plaintext key file: {path}")
        else:
            print(f"Kept {path} as the backward-compatible fallback.")
        return 0
    if args.key_command == "path":
        print(key_management.managed_key_path())
        return 0
    keychain_key, keychain_problem = key_management.keychain_lookup()
    if keychain_problem:
        print(
            f"Could not read the MARM API key from the OS keychain: {keychain_problem}",
            file=sys.stderr,
        )
        return 1
    key = keychain_key or key_management.read_managed_key_from_file()
    if not key:
        print(
            "No managed MARM API key exists. Run `marm-memory key init` first.",
            file=sys.stderr,
        )
        return 1
    print(
        "Warning: terminal capture and shell history may retain this key.",
        file=sys.stderr,
    )
    print(key)
    return 0
