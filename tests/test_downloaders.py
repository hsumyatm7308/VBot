import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import downloaders
from config import MAX_DURATION_SECONDS, MAX_MB
from utils import (
    DownloadDurationLimitError,
    DownloadFailedError,
    DownloadFileTooLargeError,
)


TOO_LARGE_OUTPUT = (
    "[download] File is larger than max-filesize "
    "(50000000 bytes > 49000000 bytes). Aborting."
)
DURATION_LIMIT_OUTPUT = (
    "[download] Example video does not pass filter "
    f"(duration <= {MAX_DURATION_SECONDS}), skipping"
)


def command_result(returncode, stdout="", stderr=""):
    return SimpleNamespace(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class DownloadVideoTests(unittest.IsolatedAsyncioTestCase):
    async def run_download_error(
        self,
        temp_dir,
        results,
        expected_error,
    ):
        commands = [["yt-dlp", str(index)] for index in range(len(results))]
        run_command = AsyncMock(side_effect=results)

        with (
            patch.object(downloaders, "build_commands", return_value=commands),
            patch.object(downloaders, "run_command", run_command),
        ):
            with self.assertRaises(expected_error) as context:
                await downloaders.download_video(
                    "youtube",
                    "https://example.com/video",
                    temp_dir,
                    user_id=123,
                )

        return context.exception, run_command

    async def test_duration_filter_rejection_raises_duration_error(self):
        results = [
            command_result(0, stdout=DURATION_LIMIT_OUTPUT),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            error, run_command = await self.run_download_error(
                temp_dir,
                results,
                DownloadDurationLimitError,
            )

        self.assertIn("does not pass filter", error.last_error)
        self.assertEqual(run_command.await_count, 1)

    async def test_later_success_wins_after_duration_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir, "video.mp4")

            async def run_command_side_effect(command, user_id, timeout):
                if command[-1] == "0":
                    return command_result(0, stdout=DURATION_LIMIT_OUTPUT)

                video_path.write_bytes(b"video")
                return command_result(0, stdout="download complete")

            run_command = AsyncMock(side_effect=run_command_side_effect)
            commands = [["yt-dlp", "0"], ["yt-dlp", "1"]]
            with (
                patch.object(
                    downloaders,
                    "build_commands",
                    return_value=commands,
                ),
                patch.object(downloaders, "run_command", run_command),
            ):
                result = await downloaders.download_video(
                    "youtube",
                    "https://example.com/video",
                    temp_dir,
                    user_id=123,
                )

        self.assertEqual(result, str(video_path))
        self.assertEqual(run_command.await_count, 2)

    async def test_earlier_duration_error_survives_later_failures(self):
        results = [
            command_result(0, stdout=DURATION_LIMIT_OUTPUT),
            command_result(1, stderr="HTTP Error 403: Forbidden"),
            command_result(1, stderr="Connection timed out"),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            _, run_command = await self.run_download_error(
                temp_dir,
                results,
                DownloadDurationLimitError,
            )

        self.assertEqual(run_command.await_count, 3)

    async def test_duration_error_has_priority_over_file_size_error(self):
        results = [
            command_result(0, stdout=TOO_LARGE_OUTPUT),
            command_result(0, stdout=DURATION_LIMIT_OUTPUT),
            command_result(1, stderr="Connection timed out"),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            _, run_command = await self.run_download_error(
                temp_dir,
                results,
                DownloadDurationLimitError,
            )

        self.assertEqual(run_command.await_count, 3)

    async def test_earlier_too_large_error_survives_later_failures(self):
        results = [
            command_result(1, stderr=TOO_LARGE_OUTPUT),
            command_result(1, stderr="HTTP Error 403: Forbidden"),
            command_result(1, stderr="Connection timed out"),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            error, run_command = await self.run_download_error(
                temp_dir,
                results,
                DownloadFileTooLargeError,
            )

        self.assertIn("max-filesize", error.last_error)
        self.assertEqual(run_command.await_count, 3)

    async def test_later_success_wins_after_earlier_too_large_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir, "video.mp4")

            async def run_command_side_effect(command, user_id, timeout):
                if command[-1] == "0":
                    return command_result(1, stdout=TOO_LARGE_OUTPUT)

                video_path.write_bytes(b"video")
                return command_result(0, stdout="download complete")

            run_command = AsyncMock(side_effect=run_command_side_effect)
            commands = [["yt-dlp", "0"], ["yt-dlp", "1"]]
            with (
                patch.object(
                    downloaders,
                    "build_commands",
                    return_value=commands,
                ),
                patch.object(downloaders, "run_command", run_command),
            ):
                result = await downloaders.download_video(
                    "youtube",
                    "https://example.com/video",
                    temp_dir,
                    user_id=123,
                )

        self.assertEqual(result, str(video_path))
        self.assertEqual(run_command.await_count, 2)

    async def test_zero_exit_without_file_keeps_trying_and_classifies_size(self):
        results = [
            command_result(0, stdout=TOO_LARGE_OUTPUT),
            command_result(1, stderr="HTTP Error 403: Forbidden"),
            command_result(1, stderr="Connection timed out"),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            _, run_command = await self.run_download_error(
                temp_dir,
                results,
                DownloadFileTooLargeError,
            )

        self.assertEqual(run_command.await_count, 3)

    async def test_all_non_size_failures_raise_download_failed(self):
        results = [
            command_result(1, stderr="HTTP Error 403: Forbidden"),
            command_result(1, stderr="Connection reset by peer"),
            command_result(1, stderr="Connection timed out"),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            error, run_command = await self.run_download_error(
                temp_dir,
                results,
                DownloadFailedError,
            )

        self.assertIn("Connection timed out", error.last_error)
        self.assertEqual(run_command.await_count, 3)

    async def test_zero_exit_without_file_or_size_keeps_trying(self):
        results = [
            command_result(0, stdout="download completed without output"),
            command_result(1, stderr="HTTP Error 403: Forbidden"),
            command_result(1, stderr="Connection timed out"),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            _, run_command = await self.run_download_error(
                temp_dir,
                results,
                DownloadFailedError,
            )

        self.assertEqual(run_command.await_count, 3)


class DownloadConfigurationTests(unittest.TestCase):
    def test_duration_limit_output_detection(self):
        self.assertTrue(
            downloaders.is_duration_limit_error(DURATION_LIMIT_OUTPUT)
        )
        self.assertFalse(
            downloaders.is_duration_limit_error(
                "Video does not pass filter (view_count >= 1000), skipping"
            )
        )
        self.assertFalse(
            downloaders.is_duration_limit_error(
                f"duration <= {MAX_DURATION_SECONDS}"
            )
        )

    def test_file_too_large_output_variants(self):
        size_errors = (
            "larger than max-filesize",
            "max-filesize",
            "File is larger than the configured limit",
        )

        for error_text in size_errors:
            with self.subTest(error_text=error_text):
                self.assertTrue(
                    downloaders.is_file_too_large_error(error_text)
                )

        self.assertFalse(
            downloaders.is_file_too_large_error(
                "HTTP Error 403: File is unavailable"
            )
        )
        self.assertFalse(
            downloaders.is_file_too_large_error(
                "ERROR: no such option: --max-filesize"
            )
        )

    def test_all_commands_use_configured_max_size(self):
        for platform in ("youtube", "tiktok", "twitter", "instagram"):
            commands = downloaders.build_commands(
                platform,
                "/tmp/%(title)s.%(ext)s",
                "https://example.com/video",
            )

            for command in commands:
                option_index = command.index("--max-filesize")
                self.assertEqual(command[option_index + 1], f"{MAX_MB}M")

    def test_all_commands_use_configured_duration_limit(self):
        for platform in ("youtube", "tiktok", "twitter", "instagram"):
            commands = downloaders.build_commands(
                platform,
                "/tmp/%(title)s.%(ext)s",
                "https://example.com/video",
            )

            for command in commands:
                option_index = command.index("--match-filter")
                self.assertEqual(
                    command[option_index + 1],
                    f"duration <= {MAX_DURATION_SECONDS}",
                )


if __name__ == "__main__":
    unittest.main()
