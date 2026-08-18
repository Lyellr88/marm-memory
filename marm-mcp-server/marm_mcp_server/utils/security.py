"""Cryptographic utilities — no imports from settings, no side effects."""

import ctypes
import secrets
import string
import sys
from pathlib import Path


def generate_api_key(length: int = 40) -> str:
    """Generate a cryptographically strong API key with mixed character classes.

    "#" is deliberately excluded. The key is persisted unquoted to a
    .env-style file (config/api_key_bootstrap.py, services/key_management.py)
    and read back by parsers that treat an unquoted value's trailing "#..."
    as a comment -- including docker run --env-file, which has no quoting
    or escaping mechanism at all, so quoting the write is not an option
    either. A "#" in the alphabet meant roughly 2 in 5 generated keys came
    back truncated on the very next read.
    """
    symbols = "-_+=.~@%^&*"
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


def _set_windows_owner_only_dacl(path: Path) -> bool:
    """Replace a file DACL with one full-control entry for the process user.

    Guards its own platform rather than trusting the caller: everything below
    dereferences ctypes.WinDLL, which does not exist off Windows, so a direct
    call elsewhere would raise AttributeError instead of returning False.
    """
    if sys.platform != "win32":
        return False

    from ctypes import wintypes

    token_query = 0x0008
    token_user_class = 1
    set_access = 2
    trustee_is_sid = 0
    trustee_is_unknown = 0
    generic_all = 0x10000000
    no_inheritance = 0
    se_file_object = 1
    owner_security_information = 0x00000001
    dacl_security_information = 0x00000004
    protected_dacl_security_information = 0x80000000

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", wintypes.LPVOID), ("attributes", wintypes.DWORD)]

    class TokenUser(ctypes.Structure):
        _fields_ = [("user", SidAndAttributes)]

    class Trustee(ctypes.Structure):
        _fields_ = [
            ("multiple_trustee", wintypes.LPVOID),
            ("multiple_trustee_operation", wintypes.DWORD),
            ("trustee_form", wintypes.DWORD),
            ("trustee_type", wintypes.DWORD),
            ("name", wintypes.LPWSTR),
        ]

    class ExplicitAccess(ctypes.Structure):
        _fields_ = [
            ("access_permissions", wintypes.DWORD),
            ("access_mode", wintypes.DWORD),
            ("inheritance", wintypes.DWORD),
            ("trustee", Trustee),
        ]

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [wintypes.LPVOID]
        kernel32.LocalFree.restype = wintypes.LPVOID
        advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        advapi32.GetTokenInformation.restype = wintypes.BOOL
        advapi32.SetEntriesInAclW.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(ExplicitAccess),
            wintypes.LPVOID,
            ctypes.POINTER(wintypes.LPVOID),
        ]
        advapi32.SetEntriesInAclW.restype = wintypes.DWORD
        advapi32.SetNamedSecurityInfoW.argtypes = [
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.LPVOID,
        ]
        advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), token_query, ctypes.byref(token)
        ):
            return False
        try:
            size = wintypes.DWORD()
            advapi32.GetTokenInformation(
                token, token_user_class, None, 0, ctypes.byref(size)
            )
            if not size.value:
                return False
            buffer = ctypes.create_string_buffer(size.value)
            if not advapi32.GetTokenInformation(
                token, token_user_class, buffer, size, ctypes.byref(size)
            ):
                return False
            token_user = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents
            access = ExplicitAccess(
                generic_all,
                set_access,
                no_inheritance,
                Trustee(
                    None,
                    0,
                    trustee_is_sid,
                    trustee_is_unknown,
                    ctypes.cast(token_user.user.sid, wintypes.LPWSTR),
                ),
            )
            dacl = wintypes.LPVOID()
            if advapi32.SetEntriesInAclW(
                1, ctypes.byref(access), None, ctypes.byref(dacl)
            ):
                return False
            try:
                # restype is DWORD, so ctypes hands back an int; naming it keeps
                # that contract visible instead of leaking ctypes' untyped call.
                status: int = advapi32.SetNamedSecurityInfoW(
                    str(path),
                    se_file_object,
                    owner_security_information
                    | dacl_security_information
                    | protected_dacl_security_information,
                    token_user.user.sid,
                    None,
                    dacl,
                    None,
                )
                return status == 0
            finally:
                kernel32.LocalFree(dacl)
        finally:
            kernel32.CloseHandle(token)
    except (AttributeError, OSError):
        return False


def restrict_windows_file_to_current_user(path: Path) -> bool:
    """Grant the executing Windows identity exclusive access to a sensitive file."""
    if sys.platform != "win32":
        return True
    return _set_windows_owner_only_dacl(path)
