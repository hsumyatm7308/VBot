import asyncio
import os
import re
import shutil
from urllib.parse import urlsplit, urlunsplit

from config import MAX_MB
from i18n import get_text


class DownloadFailedError(RuntimeError):
    def __init__(self, last_error: str):
        super().__init__(last_error)
        self.last_error = last_error


class InstagramCarouselNotSupportedError(DownloadFailedError):
    pass


class InstagramRateLimitError(DownloadFailedError):
    pass


class PinterestUnsupportedMediaError(DownloadFailedError):
    pass


class DownloadFileTooLargeError(RuntimeError):
    def __init__(self, last_error: str):
        super().__init__(last_error)
        self.last_error = last_error


class DownloadDurationLimitError(RuntimeError):
    def __init__(self, last_error: str):
        super().__init__(last_error)
        self.last_error = last_error


class DownloadedFileNotFoundError(RuntimeError):
    pass


class DownloadCancelledError(RuntimeError):
    pass


class InsufficientDiskSpaceError(RuntimeError):
    pass


def error_tail(error_text: str, limit: int) -> str:
    return error_text[-limit:]


_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_AUTH_HEADER_PATTERN = re.compile(
    r"(?i)(\b(?:proxy-)?authorization\s*[:=]\s*)"
    r"(?:bearer|basic)\s+[^\s,;]+"
)
_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(\b(?:access[_-]?token|auth(?:orization)?|cookie|key|password|"
    r"secret|session|sig(?:nature)?|token)\s*[=:]\s*)"
    r"([^\s&,;]+)"
)


def _sanitize_url(match: re.Match) -> str:
    raw_url = match.group(0)
    suffix = ""
    while raw_url and raw_url[-1] in ".,);]}":
        suffix = raw_url[-1] + suffix
        raw_url = raw_url[:-1]

    try:
        parts = urlsplit(raw_url)
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        if parts.port:
            host = f"{host}:{parts.port}"
        sanitized = urlunsplit(
            (parts.scheme, host, parts.path, "[REDACTED]" if parts.query else "", "")
        )
        return sanitized + suffix
    except ValueError:
        return "[REDACTED_URL]" + suffix


def sanitize_log_text(value) -> str:
    """Remove credentials and signed query data from diagnostic text."""
    text = str(value)
    text = _URL_PATTERN.sub(_sanitize_url, text)
    text = _AUTH_HEADER_PATTERN.sub(r"\1[REDACTED]", text)
    return _SECRET_VALUE_PATTERN.sub(r"\1[REDACTED]", text)


def get_file_size_mb(file_path: str) -> float:
    return os.path.getsize(file_path) / (1024 * 1024)


def ensure_temporary_disk_space(directory: str):
    required_bytes = MAX_MB * 2 * 1024 * 1024
    available_bytes = shutil.disk_usage(directory).free
    if available_bytes < required_bytes:
        raise InsufficientDiskSpaceError


async def keep_user_updated(
    status_message,
    stop_event,
    language,
    reply_markup=None,
):
    seconds = 0

    while not stop_event.is_set():
        await asyncio.sleep(15)
        seconds += 15

        try:
            await status_message.edit_text(
                get_text(
                    language,
                    "downloading_elapsed",
                    seconds=seconds,
                ),
                reply_markup=reply_markup,
            )
        except Exception:
            pass
