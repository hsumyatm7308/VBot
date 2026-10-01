import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import handlers
from i18n import get_text
from utils import (
    DownloadDurationLimitError,
    DownloadFailedError,
    InstagramCarouselNotSupportedError,
    InstagramRateLimitError,
    PinterestUnsupportedMediaError,
)


class HandleUrlSizeTests(unittest.IsolatedAsyncioTestCase):
    async def run_pinterest_handler(self, video_download):
        user = SimpleNamespace(id=123, username="tester")
        status_message = SimpleNamespace(edit_text=AsyncMock())
        message = SimpleNamespace(
            text="https://pin.it/AbCd123",
            reply_text=AsyncMock(return_value=status_message),
            reply_video=AsyncMock(),
        )
        update = SimpleNamespace(effective_user=user, message=message)
        increment_usage = Mock()

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
            patch.object(handlers, "get_platform", return_value="pinterest"),
            patch.object(handlers, "begin_download"),
            patch.object(handlers, "finish_download"),
            patch.object(handlers, "download_video", video_download),
            patch.object(
                handlers,
                "keep_user_updated",
                AsyncMock(return_value=None),
            ),
            patch.object(
                handlers,
                "increment_daily_usage",
                increment_usage,
            ),
            patch.object(
                handlers,
                "get_remaining_downloads",
                return_value=handlers.DAILY_LIMIT - 1,
            ),
            patch.object(
                handlers.time,
                "perf_counter",
                side_effect=[10.0, 12.0, 14.0, 16.0],
            ),
            patch("builtins.print") as mock_print,
        ):
            await handlers.handle_url(update, Mock())

        return message, status_message, increment_usage, mock_print

    async def run_instagram_post_handler(
        self,
        video_download,
        photo_download,
        reply_document=None,
        url="https://www.instagram.com/p/test/",
        language="en",
    ):
        user = SimpleNamespace(id=123, username="tester")
        status_message = SimpleNamespace(edit_text=AsyncMock())
        message = SimpleNamespace(
            text=url,
            reply_text=AsyncMock(return_value=status_message),
            reply_video=AsyncMock(),
            reply_document=reply_document or AsyncMock(),
        )
        update = SimpleNamespace(effective_user=user, message=message)
        increment_usage = Mock()

        with (
            patch.object(handlers, "PUBLIC_ACCESS", True),
            patch.object(
                handlers,
                "get_user_language",
                return_value=language,
            ),
            patch.object(
                handlers,
                "has_accepted_terms",
                return_value=True,
            ),
            patch.object(handlers, "get_daily_usage", return_value=0),
            patch.object(handlers, "is_download_active", return_value=False),
            patch.object(handlers, "is_http_url", return_value=True),
            patch.object(handlers, "get_platform", return_value="instagram"),
            patch.object(handlers, "begin_download"),
            patch.object(handlers, "finish_download"),
            patch.object(handlers, "download_video", video_download),
            patch.object(
                handlers,
                "download_instagram_photo",
                photo_download,
            ),
            patch.object(
                handlers,
                "keep_user_updated",
                AsyncMock(return_value=None),
            ),
            patch.object(
                handlers,
                "increment_daily_usage",
                increment_usage,
            ),
            patch.object(
                handlers,
                "get_remaining_downloads",
                return_value=handlers.DAILY_LIMIT - 1,
            ),
            patch("builtins.print"),
        ):
            await handlers.handle_url(update, Mock())

        return message, status_message, increment_usage

    async def test_instagram_post_keeps_successful_video_flow(self):
        with tempfile.TemporaryDirectory() as source_dir:
            video_path = Path(source_dir, "instagram-video.mp4")
            video_path.write_bytes(b"video")
            video_download = AsyncMock(return_value=str(video_path))
            photo_download = AsyncMock()

            message, _, increment_usage = (
                await self.run_instagram_post_handler(
                    video_download,
                    photo_download,
                )
            )

        video_download.assert_awaited_once()
        photo_download.assert_not_awaited()
        message.reply_video.assert_awaited_once()
        message.reply_document.assert_not_awaited()
        increment_usage.assert_called_once_with(123)

    async def test_instagram_reel_failure_does_not_use_photo_fallback(self):
        video_download = AsyncMock(
            side_effect=DownloadFailedError("video unavailable")
        )
        photo_download = AsyncMock()

        message, status_message, increment_usage = (
            await self.run_instagram_post_handler(
                video_download,
                photo_download,
                url="https://www.instagram.com/reel/test/",
            )
        )

        video_download.assert_awaited_once()
        photo_download.assert_not_awaited()
        edited_messages = [
            call.args[0]
            for call in status_message.edit_text.await_args_list
        ]
        self.assertIn(get_text("en", "download_failed"), edited_messages)
        message.reply_video.assert_not_awaited()
        message.reply_document.assert_not_awaited()
        increment_usage.assert_not_called()

    async def test_instagram_post_falls_back_to_document_photo(self):
        with tempfile.TemporaryDirectory() as source_dir:
            photo_path = Path(source_dir, "instagram-photo.jpg")
            photo_path.write_bytes(b"photo")
            video_download = AsyncMock(
                side_effect=DownloadFailedError("video unavailable")
            )
            photo_download = AsyncMock(return_value=str(photo_path))

            message, _, increment_usage = (
                await self.run_instagram_post_handler(
                    video_download,
                    photo_download,
                )
            )

        video_download.assert_awaited_once()
        photo_download.assert_awaited_once()
        message.reply_video.assert_not_awaited()
        message.reply_document.assert_awaited_once()
        upload_options = message.reply_document.await_args.kwargs
        self.assertEqual(upload_options["read_timeout"], 120)
        self.assertEqual(upload_options["write_timeout"], 120)
        self.assertEqual(upload_options["connect_timeout"], 30)
        self.assertEqual(upload_options["pool_timeout"], 30)
        increment_usage.assert_called_once_with(123)

    async def test_instagram_photo_upload_failure_does_not_increment_usage(self):
        with tempfile.TemporaryDirectory() as source_dir:
            photo_path = Path(source_dir, "instagram-photo.jpg")
            photo_path.write_bytes(b"photo")
            reply_document = AsyncMock(
                side_effect=RuntimeError("upload failed")
            )

            with patch.object(handlers.LOGGER, "exception"):
                message, _, increment_usage = (
                    await self.run_instagram_post_handler(
                        AsyncMock(
                            side_effect=DownloadFailedError(
                                "video unavailable"
                            )
                        ),
                        AsyncMock(return_value=str(photo_path)),
                        reply_document=reply_document,
                    )
                )

        message.reply_document.assert_awaited_once()
        increment_usage.assert_not_called()

    async def test_instagram_carousel_shows_clear_error(self):
        message, status_message, increment_usage = (
            await self.run_instagram_post_handler(
                AsyncMock(
                    side_effect=DownloadFailedError("video unavailable")
                ),
                AsyncMock(
                    side_effect=InstagramCarouselNotSupportedError(
                        "Instagram carousel is not supported yet."
                    )
                ),
            )
        )

        edited_messages = [
            call.args[0]
            for call in status_message.edit_text.await_args_list
        ]
        self.assertIn(
            get_text("en", "instagram_carousel_not_supported"),
            edited_messages,
        )
        message.reply_video.assert_not_awaited()
        message.reply_document.assert_not_awaited()
        increment_usage.assert_not_called()

    async def test_instagram_rate_limit_shows_localized_error(self):
        message, status_message, increment_usage = (
            await self.run_instagram_post_handler(
                AsyncMock(
                    side_effect=DownloadFailedError("video unavailable")
                ),
                AsyncMock(
                    side_effect=InstagramRateLimitError(
                        "Instagram photo download rate limited."
                    )
                ),
            )
        )

        edited_messages = [
            call.args[0]
            for call in status_message.edit_text.await_args_list
        ]
        self.assertIn(
            get_text(
                "en",
                "instagram_photo_temporarily_unavailable",
            ),
            edited_messages,
        )
        message.reply_video.assert_not_awaited()
        message.reply_document.assert_not_awaited()
        increment_usage.assert_not_called()

    async def test_instagram_rate_limit_shows_myanmar_photo_message(self):
        message, status_message, increment_usage = (
            await self.run_instagram_post_handler(
                AsyncMock(
                    side_effect=DownloadFailedError("video unavailable")
                ),
                AsyncMock(
                    side_effect=InstagramRateLimitError(
                        "Instagram photo download rate limited."
                    )
                ),
                language="my",
            )
        )

        edited_messages = [
            call.args[0]
            for call in status_message.edit_text.await_args_list
        ]
        self.assertIn(
            get_text(
                "my",
                "instagram_photo_temporarily_unavailable",
            ),
            edited_messages,
        )
        message.reply_video.assert_not_awaited()
        message.reply_document.assert_not_awaited()
        increment_usage.assert_not_called()

    def test_instagram_photo_temporary_messages_are_localized(self):
        self.assertEqual(
            get_text(
                "en",
                "instagram_photo_temporarily_unavailable",
            ),
            "This Instagram photo can’t be downloaded right now.\n\n"
            "Please try again later.",
        )
        self.assertEqual(
            get_text(
                "my",
                "instagram_photo_temporarily_unavailable",
            ),
            "ဒီ Instagram photo ကို အခုချိန်မှာ download မလုပ်နိုင်သေးပါ။\n\n"
            "ခဏနောက်မှ ပြန်စမ်းပါ။",
        )

    async def test_instagram_story_remains_unsupported_with_specific_message(
        self,
    ):
        user = SimpleNamespace(id=123, username="tester")
        message = SimpleNamespace(
            text="https://www.instagram.com/stories/tester/123456/",
            reply_text=AsyncMock(),
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
            patch.object(
                handlers,
                "is_instagram_story_url",
                return_value=True,
            ),
            patch.object(handlers, "get_platform") as get_platform,
            patch.object(handlers, "begin_download") as begin_download,
            patch.object(handlers, "download_video") as download_video,
        ):
            await handlers.handle_url(update, Mock())

        message.reply_text.assert_awaited_once_with(
            get_text("en", "instagram_story_not_supported")
        )
        get_platform.assert_not_called()
        begin_download.assert_not_called()
        download_video.assert_not_called()

    def test_instagram_story_messages_are_localized(self):
        self.assertEqual(
            get_text("en", "instagram_story_not_supported"),
            "Instagram Story links are not supported yet.",
        )
        self.assertEqual(
            get_text("my", "instagram_story_not_supported"),
            "ဤ Instagram Story link ကို လက်ရှိ support မလုပ်သေးပါ။",
        )

    async def test_instagram_logs_file_size_and_upload_time(self):
        user = SimpleNamespace(id=123, username="tester")
        status_message = SimpleNamespace(edit_text=AsyncMock())
        message = SimpleNamespace(
            text="https://www.instagram.com/reel/test/",
            reply_text=AsyncMock(return_value=status_message),
            reply_video=AsyncMock(),
        )
        update = SimpleNamespace(effective_user=user, message=message)

        with tempfile.TemporaryDirectory() as source_dir:
            video_path = Path(source_dir, "instagram-video.mp4")
            video_path.write_bytes(b"video")

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
                patch.object(handlers, "get_platform", return_value="instagram"),
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
                patch.object(handlers, "increment_daily_usage"),
                patch.object(
                    handlers,
                    "get_remaining_downloads",
                    return_value=handlers.DAILY_LIMIT - 1,
                ),
                patch.object(
                    handlers.time,
                    "perf_counter",
                    side_effect=[10.0, 12.0, 14.0, 16.0],
                ),
                patch("builtins.print") as mock_print,
            ):
                await handlers.handle_url(update, Mock())

        output = [call.args[0] for call in mock_print.call_args_list]
        self.assertIn(
            "[PERF] platform=instagram file_size=0.00MB",
            output,
        )
        self.assertIn(
            "[PERF] platform=instagram upload=2.00s",
            output,
        )
        self.assertIn(
            "[PERF] platform=instagram total=6.00s",
            output,
        )
        message.reply_video.assert_awaited_once()

    async def test_pinterest_video_uses_generic_upload_and_perf_flow(self):
        with tempfile.TemporaryDirectory() as source_dir:
            video_path = Path(source_dir, "pinterest-video.mp4")
            video_path.write_bytes(b"video")

            message, _, increment_usage, mock_print = (
                await self.run_pinterest_handler(
                    AsyncMock(return_value=str(video_path))
                )
            )

        output = [call.args[0] for call in mock_print.call_args_list]
        self.assertIn(
            "[PERF] platform=pinterest file_size=0.00MB",
            output,
        )
        self.assertIn(
            "[PERF] platform=pinterest upload=2.00s",
            output,
        )
        self.assertIn(
            "[PERF] platform=pinterest total=6.00s",
            output,
        )
        message.reply_video.assert_awaited_once()
        increment_usage.assert_called_once_with(123)

    async def test_pinterest_image_pin_shows_controlled_message(self):
        message, status_message, increment_usage, _ = (
            await self.run_pinterest_handler(
                AsyncMock(
                    side_effect=PinterestUnsupportedMediaError(
                        "Pinterest Pin does not contain supported video media."
                    )
                )
            )
        )

        edited_messages = [
            call.args[0]
            for call in status_message.edit_text.await_args_list
        ]
        self.assertIn(
            get_text("en", "pinterest_video_only"),
            edited_messages,
        )
        message.reply_video.assert_not_awaited()
        increment_usage.assert_not_called()

    def test_pinterest_unsupported_messages_are_localized(self):
        self.assertEqual(
            get_text("en", "pinterest_video_only"),
            "Unsupported Pinterest media\n\n"
            "Only public Pinterest video Pins are supported.",
        )
        self.assertEqual(
            get_text("my", "pinterest_video_only"),
            "Pinterest media ကို မထောက်ပံ့ပါ\n\n"
            "Public Pinterest video Pin များကိုသာ support လုပ်ထားပါတယ်။",
        )

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
            "This video exceeds the current 15-minute limit.",
        )
        self.assertEqual(
            get_text(
                "my",
                "video_too_long",
                max_duration_minutes=minutes,
            ),
            "Video အချိန်ရှည်လွန်းပါတယ်\n\n"
            "ဒီ video က လက်ရှိ 15 မိနစ် limit ထက် ကျော်နေပါတယ်။",
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
