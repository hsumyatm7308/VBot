import asyncio
import os


class DownloadFailedError(RuntimeError):
    def __init__(self, last_error: str):
        super().__init__(last_error)
        self.last_error = last_error


class DownloadedFileNotFoundError(RuntimeError):
    pass


def error_tail(error_text: str, limit: int) -> str:
    return error_text[-limit:]


def get_file_size_mb(file_path: str) -> float:
    return os.path.getsize(file_path) / (1024 * 1024)


async def keep_user_updated(status_message, stop_event):
    seconds = 0

    while not stop_event.is_set():
        await asyncio.sleep(15)
        seconds += 15

        if seconds == 15:
            text = "Downloading... 15 seconds ကြာနေပါပြီ။ ခဏစောင့်ပေးပါ။"
        elif seconds == 30:
            text = "Still downloading... video file ကြီးနိုင်ပါတယ်။"
        elif seconds == 60:
            text = "Still working... မပြီးသေးပါ။ ရနိုင်သေးရင် ဆက်လုပ်နေပါတယ်။"
        else:
            text = f"Still downloading... {seconds} seconds ကြာနေပါပြီ။"

        try:
            await status_message.edit_text(text)
        except Exception:
            pass
