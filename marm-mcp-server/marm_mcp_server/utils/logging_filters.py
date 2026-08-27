import logging
import time

_THROTTLE_SECONDS = 300.0
_last_logged: dict[str, float] = {}


def log_warning_throttled(logger: logging.Logger, key: str, message: str) -> None:
    """The console polls the status endpoints every 5s, so an unreadable database
    would otherwise write a traceback every cycle for as long as it stays broken."""
    now = time.monotonic()
    last = _last_logged.get(key)
    if last is not None and now - last < _THROTTLE_SECONDS:
        return
    _last_logged[key] = now
    logger.warning(message, exc_info=True)


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
