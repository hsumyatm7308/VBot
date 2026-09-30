import asyncio
import os

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


def error_tail(error_text: str, limit: int) -> str:
    return error_text[-limit:]


def get_file_size_mb(file_path: str) -> float:
    return os.path.getsize(file_path) / (1024 * 1024)


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
