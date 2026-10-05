import sqlite3
import tempfile
import unittest
import warnings
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import config
import database
import downloaders
import handlers
from downloader_core import process
from i18n import get_text
from telegram_handlers import commands
from utils import (
    DownloadCancelledError,
    DownloadDurationLimitError,
    DownloadFailedError,
    DownloadFileTooLargeError,
)


class AdminConfigTests(unittest.TestCase):
    def test_missing_admin_ids_is_safe(self):
        self.assertEqual(config.parse_admin_user_ids(None), set())
        self.assertEqual(config.parse_admin_user_ids(""), set())

    def test_multiple_admin_ids_parse_with_whitespace(self):
        self.assertEqual(
            config.parse_admin_user_ids(
                "123456789, 987654321,123456789"
            ),
            {123456789, 987654321},
        )

    def test_invalid_admin_ids_are_skipped_with_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            parsed = config.parse_admin_user_ids("123,invalid,-9")

        self.assertEqual(parsed, {123})
        self.assertEqual(len(caught), 1)
        self.assertIn("invalid", str(caught[0].message))
        self.assertIn("-9", str(caught[0].message))


class StatsDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name, "stats.db"))
        self.db_path_patcher = patch.object(
            database,
            "DB_PATH",
            self.db_path,
        )
        self.db_path_patcher.start()
        database.init_legal_db()

    def tearDown(self):
        self.db_path_patcher.stop()
        self.temp_dir.cleanup()

    def test_repeated_downloads_count_user_once(self):
        database.increment_daily_usage(1001)
        database.increment_daily_usage(1001)

        self.assertEqual(database.get_total_successful_users(), 1)
        self.assertEqual(database.get_active_users_today(), 1)
        self.assertEqual(database.get_successful_downloads_today(), 2)

    def test_two_successful_users_count_separately(self):
        database.increment_daily_usage(1001)
        database.increment_daily_usage(2002)

        self.assertEqual(database.get_total_successful_users(), 2)
        self.assertEqual(database.get_active_users_today(), 2)
        self.assertEqual(database.get_successful_downloads_today(), 2)

    def test_stats_share_daily_limit_day_boundary(self):
        with patch.object(
            database,
            "get_today_utc",
            return_value="2026-10-01",
        ):
            database.increment_daily_usage(1001)
            self.assertEqual(database.get_daily_usage(1001), 1)
            self.assertEqual(database.get_active_users_today(), 1)
            self.assertEqual(database.get_successful_downloads_today(), 1)

        with patch.object(
            database,
            "get_today_utc",
            return_value="2026-10-02",
        ):
            self.assertEqual(database.get_daily_usage(1001), 0)
            self.assertEqual(database.get_active_users_today(), 0)
            self.assertEqual(database.get_successful_downloads_today(), 0)
            self.assertEqual(database.get_total_successful_users(), 1)

    def test_database_initialization_preserves_existing_data(self):
        database.set_user_language(1001, "en")
        database.save_terms_acceptance(1001)
        database.increment_daily_usage(1001)

        database.init_legal_db()

        self.assertEqual(database.get_user_language(1001), "en")
        self.assertTrue(database.has_accepted_terms(1001))
        self.assertEqual(database.get_daily_usage(1001), 1)
        self.assertEqual(database.get_total_successful_users(), 1)

    def test_existing_daily_usage_schema_supports_stats(self):
        legacy_path = str(Path(self.temp_dir.name, "legacy.db"))
        with sqlite3.connect(legacy_path) as conn:
            conn.execute(
                """
                CREATE TABLE daily_usage (
                    user_id INTEGER NOT NULL,
                    usage_date TEXT NOT NULL,
                    download_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, usage_date)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO daily_usage (
                    user_id,
                    usage_date,
                    download_count
                ) VALUES (?, ?, ?)
                """,
                (1001, database.get_today_utc(), 3),
            )
            conn.commit()

        with patch.object(database, "DB_PATH", legacy_path):
            database.init_legal_db()
            self.assertEqual(database.get_total_successful_users(), 1)
            self.assertEqual(database.get_active_users_today(), 1)
            self.assertEqual(database.get_successful_downloads_today(), 3)

    @unittest.skipUnless(os.name == "posix", "POSIX file modes only")
    def test_database_file_is_created_owner_only(self):
        mode = Path(self.db_path).stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)


class StatsCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_configured_admin_can_access_stats(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=123),
            message=message,
        )

        with (
            patch.object(commands, "ADMIN_USER_IDS", {123, 456}),
            patch.object(
                commands,
                "get_total_successful_users",
                return_value=128,
            ),
            patch.object(
                commands,
                "get_active_users_today",
                return_value=34,
            ),
            patch.object(
                commands,
                "get_successful_downloads_today",
                return_value=91,
            ),
            patch.object(
                commands,
                "get_active_download_count",
                return_value=2,
            ),
        ):
            await commands.stats_command(update, Mock())

        message.reply_text.assert_awaited_once_with(
            "📊 VDlp Bot Stats\n\n"
            "Total users: 128\n"
            "Active today: 34\n"
            "Downloads today: 91\n"
            "Currently downloading: 2"
        )

    async def test_non_admin_cannot_see_stats(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=999),
            message=message,
        )

        with (
            patch.object(commands, "ADMIN_USER_IDS", {123}),
            patch.object(commands, "get_language", return_value="en"),
            patch.object(
                commands,
                "get_total_successful_users",
            ) as total_users,
        ):
            await commands.stats_command(update, Mock())

        message.reply_text.assert_awaited_once_with(
            get_text("en", "private_access")
        )
        total_users.assert_not_called()

    async def test_empty_admin_config_denies_access_safely(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=123),
            message=message,
        )

        with (
            patch.object(commands, "ADMIN_USER_IDS", set()),
            patch.object(commands, "get_language", return_value="my"),
        ):
            await commands.stats_command(update, Mock())

        message.reply_text.assert_awaited_once_with(
            get_text("my", "private_access")
        )


class ActiveDownloadStatsTests(unittest.TestCase):
    def setUp(self):
        process.ACTIVE_USERS.clear()
        process.DOWNLOAD_ATTEMPTS.clear()

    def tearDown(self):
        process.ACTIVE_USERS.clear()
        process.DOWNLOAD_ATTEMPTS.clear()

    def test_active_count_uses_existing_download_state(self):
        process.begin_download(1001)
        process.begin_download(2002)

        self.assertEqual(downloaders.get_active_download_count(), 2)

        process.finish_download(1001)
        self.assertEqual(downloaders.get_active_download_count(), 1)

    def test_try_begin_download_reserves_user_atomically(self):
        self.assertTrue(process.try_begin_download(1001))
        self.assertFalse(process.try_begin_download(1001))
        self.assertTrue(process.try_begin_download(2002))

        process.finish_download(1001)
        process.finish_download(2002)

    def test_failed_attempt_limiter_uses_cooldown_and_rolling_cap(self):
        with patch("downloader_core.process.time.monotonic") as monotonic:
            monotonic.return_value = 100.0
            self.assertTrue(process.try_record_download_attempt(1001))
            self.assertFalse(process.try_record_download_attempt(1001))

            for timestamp in (116.0, 132.0, 148.0, 164.0):
                monotonic.return_value = timestamp
                self.assertTrue(process.try_record_download_attempt(1001))

            monotonic.return_value = 180.0
            self.assertFalse(process.try_record_download_attempt(1001))

            monotonic.return_value = 701.0
            self.assertTrue(process.try_record_download_attempt(1001))


class SuccessfulDownloadRecordingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path_patcher = patch.object(
            database,
            "DB_PATH",
            str(Path(self.temp_dir.name, "downloads.db")),
        )
        self.db_path_patcher.start()
        database.init_legal_db()

    def tearDown(self):
        self.db_path_patcher.stop()
        self.temp_dir.cleanup()

    async def run_download(
        self,
        *,
        download_result,
        upload_error=None,
    ):
        user = SimpleNamespace(id=1001, username="tester")
        status_message = SimpleNamespace(edit_text=AsyncMock())
        reply_video = AsyncMock(side_effect=upload_error)
        message = SimpleNamespace(
            text="https://www.youtube.com/watch?v=test",
            reply_text=AsyncMock(return_value=status_message),
            reply_video=reply_video,
        )
        update = SimpleNamespace(effective_user=user, message=message)
        if isinstance(download_result, BaseException):
            video_download = AsyncMock(side_effect=download_result)
        else:
            video_download = AsyncMock(return_value=download_result)

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
            patch.object(handlers, "is_download_active", return_value=False),
            patch.object(handlers, "is_http_url", return_value=True),
            patch.object(
                handlers,
                "is_instagram_story_url",
                return_value=False,
            ),
            patch.object(handlers, "get_platform", return_value="youtube"),
            patch.object(handlers, "try_begin_download", return_value=True),
            patch.object(handlers, "try_record_download_attempt", return_value=True),
            patch.object(handlers, "finish_download"),
            patch.object(
                handlers,
                "download_video",
                video_download,
            ),
            patch.object(
                handlers,
                "keep_user_updated",
                AsyncMock(return_value=None),
            ),
            patch("builtins.print"),
            patch.object(handlers.LOGGER, "exception"),
        ):
            await handlers.handle_url(update, Mock())

        return reply_video

    async def test_successful_upload_updates_persistent_stats(self):
        media_path = Path(self.temp_dir.name, "video.mp4")
        media_path.write_bytes(b"video")

        await self.run_download(download_result=str(media_path))

        self.assertEqual(database.get_total_successful_users(), 1)
        self.assertEqual(database.get_active_users_today(), 1)
        self.assertEqual(database.get_successful_downloads_today(), 1)

    async def test_failed_download_does_not_update_stats(self):
        await self.run_download(
            download_result=DownloadFailedError("download failed")
        )

        self.assertEqual(database.get_total_successful_users(), 0)
        self.assertEqual(database.get_successful_downloads_today(), 0)

    async def test_cancelled_download_does_not_update_stats(self):
        await self.run_download(
            download_result=DownloadCancelledError()
        )

        self.assertEqual(database.get_total_successful_users(), 0)
        self.assertEqual(database.get_successful_downloads_today(), 0)

    async def test_duration_rejection_does_not_update_stats(self):
        await self.run_download(
            download_result=DownloadDurationLimitError("too long")
        )

        self.assertEqual(database.get_total_successful_users(), 0)
        self.assertEqual(database.get_successful_downloads_today(), 0)

    async def test_size_rejection_does_not_update_stats(self):
        await self.run_download(
            download_result=DownloadFileTooLargeError("too large")
        )

        self.assertEqual(database.get_total_successful_users(), 0)
        self.assertEqual(database.get_successful_downloads_today(), 0)

    async def test_upload_failure_does_not_update_stats(self):
        media_path = Path(self.temp_dir.name, "video.mp4")
        media_path.write_bytes(b"video")

        await self.run_download(
            download_result=str(media_path),
            upload_error=RuntimeError("upload failed"),
        )

        self.assertEqual(database.get_total_successful_users(), 0)
        self.assertEqual(database.get_successful_downloads_today(), 0)


if __name__ == "__main__":
    unittest.main()
