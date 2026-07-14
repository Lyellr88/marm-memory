"""Logging filters for MARM MCP Server."""

import logging


class _SuppressProactorWindowsNoise(logging.Filter):
    """Suppress benign WinError 10054 noise from ProactorEventLoop disconnect cleanup.

    The asyncio log record has '_ProactorBasePipeTransport' in the message text
    and the actual ConnectionResetError in record.exc_info — not in getMessage().
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if "_ProactorBasePipeTransport" not in record.getMessage():
            return True
        if not record.exc_info:
            return True

        exc = record.exc_info[1]
        if not isinstance(exc, ConnectionResetError):
            return True

        winerror = getattr(exc, "winerror", None)
        errno = getattr(exc, "errno", None)
        return not (winerror == 10054 or errno == 10054)


_proactor_noise_filter = _SuppressProactorWindowsNoise()
logging.getLogger("asyncio").addFilter(_proactor_noise_filter)
