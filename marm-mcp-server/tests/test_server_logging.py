import logging

from conftest import load_isolated_server


def _record(message, exc=None):
    exc_info = None
    if exc is not None:
        exc_info = (type(exc), exc, None)
    return logging.LogRecord(
        name="asyncio",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=exc_info,
    )


def test_proactor_filter_only_suppresses_known_windows_reset(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    filt = server._proactor_noise_filter

    reset = ConnectionResetError("connection reset")
    reset.winerror = 10054

    assert not filt.filter(
        _record(
            "Exception in callback _ProactorBasePipeTransport._call_connection_lost()",
            reset,
        )
    )


def test_proactor_filter_keeps_other_asyncio_errors(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    filt = server._proactor_noise_filter

    reset = ConnectionResetError("connection reset")
    reset.winerror = 10054

    assert filt.filter(_record("unrelated asyncio callback", reset))
    assert filt.filter(
        _record(
            "Exception in callback _ProactorBasePipeTransport._call_connection_lost()",
            RuntimeError("real transport bug"),
        )
    )

    other_reset = ConnectionResetError("different reset")
    other_reset.winerror = 12345
    assert filt.filter(
        _record(
            "Exception in callback _ProactorBasePipeTransport._call_connection_lost()",
            other_reset,
        )
    )
