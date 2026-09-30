import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import handlers
from i18n import get_text
from utils import DownloadDurationLimitError


class HandleUrlSizeTests(unittest.IsolatedAsyncioTestCase):
    async def test_duration_limit_uses_localized_message(self):
        user = SimpleNamespace(id=123, username="tester")
        status_message = SimpleNamespace(edit_text=AsyncMock())
        message = SimpleNamespace(
            text="https://www.youtube.com/watch?v=test",
            reply_text=AsyncMock(return_value=status_message),
            reply_video=AsyncMock(),
        )
        update = SimpleNamespace(effective_user=user, message=message)

        with (
            patch.object(handlers, "PUBLIC_ACCESS", True),
            patch.object(
                handlers,
                "get_user_language",
                return_value="en",
            ),
            patch.object(
                handlers,
                "has_accepted_terms",
                return_value=True,
            ),
            patch.object(handlers, "get_daily_usage", return_value=0),
            patch.object(handlers, "is_download_active", return_value=False),
            patch.object(handlers, "is_http_url", return_value=True),
            patch.object(handlers, "get_platform", return_value="youtube"),
            patch.object(handlers, "begin_download"),
            patch.object(handlers, "finish_download"),
            patch.object(
                handlers,
                "download_video",
                AsyncMock(
                    side_effect=DownloadDurationLimitError(
                        "does not pass filter "
                        f"(duration <= {handlers.MAX_DURATION_SECONDS})"
                    )
                ),
            ),
            patch.object(
                handlers,
                "keep_user_updated",
                AsyncMock(return_value=None),
            ),
            patch.object(
                handlers,
                "increment_daily_usage",
            ) as increment_usage,
        ):
            await handlers.handle_url(update, Mock())

        expected_message = get_text(
            "en",
            "video_too_long",
            max_duration_minutes=handlers.MAX_DURATION_SECONDS / 60,
        )
        edited_messages = [
            call.args[0]
            for call in status_message.edit_text.await_args_list
        ]

        self.assertIn(expected_message, edited_messages)
        message.reply_video.assert_not_awaited()
        increment_usage.assert_not_called()

    def test_duration_limit_messages_are_localized(self):
        minutes = handlers.MAX_DURATION_SECONDS / 60
        self.assertEqual(
            get_text(
                "en",
                "video_too_long",
                max_duration_minutes=minutes,
            ),
            "Video too long\n\n"
            "This video exceeds the current 10-minute limit.",
        )
        self.assertEqual(
            get_text(
                "my",
                "video_too_long",
                max_duration_minutes=minutes,
            ),
            "Video အချိန်ရှည်လွန်းပါတယ်\n\n"
            "ဒီ video က လက်ရှိ 10 မိနစ် limit ထက် ကျော်နေပါတယ်။",
        )

    async def test_downloaded_file_over_limit_uses_message_with_size(self):
        user = SimpleNamespace(id=123, username="tester")
        status_message = SimpleNamespace(edit_text=AsyncMock())
        message = SimpleNamespace(
            text="https://www.youtube.com/watch?v=test",
            reply_text=AsyncMock(return_value=status_message),
            reply_video=AsyncMock(),
        )
        update = SimpleNamespace(effective_user=user, message=message)

        with tempfile.TemporaryDirectory() as source_dir:
            video_path = Path(source_dir, "large-video.mp4")
            with video_path.open("wb") as video:
                video.truncate((handlers.MAX_MB + 1) * 1024 * 1024)

            with (
                patch.object(handlers, "PUBLIC_ACCESS", True),
                patch.object(
                    handlers,
                    "get_user_language",
                    return_value="en",
                ),
                patch.object(
                    handlers,
                    "has_accepted_terms",
                    return_value=True,
                ),
                patch.object(handlers, "get_daily_usage", return_value=0),
                patch.object(handlers, "is_download_active", return_value=False),
                patch.object(handlers, "is_http_url", return_value=True),
                patch.object(handlers, "get_platform", return_value="youtube"),
                patch.object(handlers, "begin_download"),
                patch.object(handlers, "finish_download"),
                patch.object(
                    handlers,
                    "download_video",
                    AsyncMock(return_value=str(video_path)),
                ),
                patch.object(
                    handlers,
                    "keep_user_updated",
                    AsyncMock(return_value=None),
                ),
                patch.object(
                    handlers,
                    "increment_daily_usage",
                ) as increment_usage,
            ):
                await handlers.handle_url(update, Mock())

        size_mb = handlers.MAX_MB + 1
        expected_message = get_text(
            "en",
            "file_too_large_with_size",
            size_mb=size_mb,
            max_mb=handlers.MAX_MB,
        )
        edited_messages = [
            call.args[0]
            for call in status_message.edit_text.await_args_list
        ]

        self.assertIn(expected_message, edited_messages)
        message.reply_video.assert_not_awaited()
        increment_usage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
