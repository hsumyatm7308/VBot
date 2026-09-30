import json
import os
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
    InstagramCarouselNotSupportedError,
    InstagramRateLimitError,
    PinterestUnsupportedMediaError,
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
    def setUp(self):
        metadata_patcher = patch.object(
            downloaders,
            "get_youtube_metadata",
            AsyncMock(return_value=None),
        )
        metadata_patcher.start()
        self.addCleanup(metadata_patcher.stop)

    def make_youtube_metadata(
        self,
        video_sizes=None,
        audio_size=None,
        duration=300,
        video_bitrates=None,
        audio_bitrate=None,
        progressive_sizes=None,
        size_key="filesize",
    ):
        video_sizes = video_sizes or {}
        video_bitrates = video_bitrates or {}
        progressive_sizes = progressive_sizes or {}
        formats = []

        for height in (1080, 720, 480):
            format_info = {
                "format_id": f"v{height}",
                "ext": "mp4",
                "height": height,
                "vcodec": "avc1.640028",
                "acodec": "none",
            }
            if height in video_sizes:
                format_info[size_key] = video_sizes[height]
            if height in video_bitrates:
                format_info["vbr"] = video_bitrates[height]
            formats.append(format_info)

        for height, size in progressive_sizes.items():
            formats.append({
                "format_id": f"p{height}",
                "ext": "mp4",
                "height": height,
                "vcodec": "avc1.640028",
                "acodec": "mp4a.40.2",
                size_key: size,
            })

        audio_format = {
            "format_id": "a1",
            "ext": "m4a",
            "vcodec": "none",
            "acodec": "mp4a.40.2",
        }
        if audio_size is not None:
            audio_format[size_key] = audio_size
        if audio_bitrate is not None:
            audio_format["abr"] = audio_bitrate
        formats.append(audio_format)

        return {
            "duration": duration,
            "formats": formats,
        }

    async def run_youtube_with_metadata(
        self,
        temp_dir,
        metadata,
        actual_sizes_by_format,
    ):
        attempted_formats = []
        video_path = Path(temp_dir, "video.mp4")

        async def run_command_side_effect(command, user_id, timeout):
            format_selector = downloaders.get_format_selector(command)
            attempted_formats.append(format_selector)
            with video_path.open("wb") as video:
                video.truncate(actual_sizes_by_format[format_selector])
            return command_result(0, stdout="download complete")

        with (
            patch.object(
                downloaders,
                "get_youtube_metadata",
                AsyncMock(return_value=metadata),
            ),
            patch.object(
                downloaders,
                "run_command",
                AsyncMock(side_effect=run_command_side_effect),
            ),
        ):
            result = await downloaders.download_video(
                "youtube",
                "https://example.com/video",
                temp_dir,
                user_id=123,
            )

        return result, attempted_formats

    async def run_youtube_quality_sizes(self, temp_dir, sizes_by_format):
        attempted_formats = []
        video_path = Path(temp_dir, "video.mp4")

        async def run_command_side_effect(command, user_id, timeout):
            format_selector = downloaders.get_format_selector(command)
            attempted_formats.append(format_selector)
            with video_path.open("wb") as video:
                video.truncate(sizes_by_format[format_selector])
            return command_result(0, stdout="download complete")

        run_command = AsyncMock(side_effect=run_command_side_effect)
        with patch.object(downloaders, "run_command", run_command):
            result = await downloaders.download_video(
                "youtube",
                "https://example.com/video",
                temp_dir,
                user_id=123,
            )

        return result, attempted_formats

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

    async def test_metadata_1080p_fits_downloads_only_1080p(self):
        megabyte = 1024 * 1024
        metadata = self.make_youtube_metadata(
            video_sizes={1080: 20 * megabyte, 720: 12 * megabyte},
            audio_size=2 * megabyte,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            _, attempted_formats = await self.run_youtube_with_metadata(
                temp_dir,
                metadata,
                {downloaders.YOUTUBE_1080_FORMAT: 22 * megabyte},
            )

        self.assertEqual(
            attempted_formats,
            [downloaders.YOUTUBE_1080_FORMAT],
        )

    async def test_download_logs_actual_properties_from_metadata(self):
        megabyte = 1024 * 1024
        metadata = {
            "duration": 300,
            "formats": [
                {
                    "format_id": "v720",
                    "filesize": 10 * megabyte,
                    "width": 1280,
                    "height": 720,
                    "resolution": "1280x720",
                    "vcodec": "avc1.4d401f",
                    "acodec": "none",
                },
                {
                    "format_id": "a1",
                    "filesize": 2 * megabyte,
                    "vcodec": "none",
                    "acodec": "mp4a.40.2",
                },
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir, "video.mp4")

            async def run_command_side_effect(command, user_id, timeout):
                video_path.write_bytes(b"video")
                return command_result(
                    0,
                    stdout=(
                        "[info] video: Downloading 1 format(s): "
                        "v720+a1"
                    ),
                )

            with (
                patch.object(
                    downloaders,
                    "get_youtube_metadata",
                    AsyncMock(return_value=metadata),
                ),
                patch.object(
                    downloaders,
                    "run_command",
                    AsyncMock(side_effect=run_command_side_effect),
                ),
                patch("builtins.print") as mock_print,
            ):
                result = await downloaders.download_video(
                    "youtube",
                    "https://example.com/video",
                    temp_dir,
                    user_id=123,
                )

        self.assertEqual(result, str(video_path))
        format_output = next(
            call.args[0]
            for call in mock_print.call_args_list
            if "selected_quality=" in call.args[0]
        )
        self.assertIn("selected_quality=1080p", format_output)
        self.assertIn("actual_width=1280", format_output)
        self.assertIn("actual_height=720", format_output)
        self.assertIn("actual_resolution=1280x720", format_output)
        self.assertIn("format_id=v720+a1", format_output)
        self.assertIn("vcodec=avc1.4d401f", format_output)
        self.assertIn("acodec=mp4a.40.2", format_output)

    async def test_metadata_skips_oversized_1080p_for_720p(self):
        megabyte = 1024 * 1024
        metadata = self.make_youtube_metadata(
            video_sizes={
                1080: 44 * megabyte,
                720: 20 * megabyte,
                480: 10 * megabyte,
            },
            audio_size=2 * megabyte,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            _, attempted_formats = await self.run_youtube_with_metadata(
                temp_dir,
                metadata,
                {downloaders.YOUTUBE_720_FORMAT: 22 * megabyte},
            )

        self.assertEqual(
            attempted_formats,
            [downloaders.YOUTUBE_720_FORMAT],
        )

    async def test_metadata_skips_1080p_and_720p_for_480p(self):
        megabyte = 1024 * 1024
        metadata = self.make_youtube_metadata(
            video_sizes={
                1080: 44 * megabyte,
                720: 43 * megabyte,
            },
            audio_size=2 * megabyte,
            progressive_sizes={480: 12 * megabyte},
            size_key="filesize_approx",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            _, attempted_formats = await self.run_youtube_with_metadata(
                temp_dir,
                metadata,
                {downloaders.YOUTUBE_480_FORMAT: 12 * megabyte},
            )

        self.assertEqual(
            attempted_formats,
            [downloaders.YOUTUBE_480_FORMAT],
        )

    async def test_metadata_uses_bitrate_estimate_when_sizes_are_missing(self):
        megabyte = 1024 * 1024
        metadata = self.make_youtube_metadata(
            duration=MAX_DURATION_SECONDS,
            video_bitrates={1080: 800, 720: 400, 480: 200},
            audio_bitrate=96,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            _, attempted_formats = await self.run_youtube_with_metadata(
                temp_dir,
                metadata,
                {downloaders.YOUTUBE_480_FORMAT: 34 * megabyte},
            )

        self.assertEqual(
            attempted_formats,
            [downloaders.YOUTUBE_480_FORMAT],
        )

    async def test_missing_metadata_estimates_uses_runtime_fallback(self):
        fits = MAX_MB * 1024 * 1024
        metadata = self.make_youtube_metadata()

        with tempfile.TemporaryDirectory() as temp_dir:
            _, attempted_formats = await self.run_youtube_with_metadata(
                temp_dir,
                metadata,
                {
                    downloaders.YOUTUBE_1080_FORMAT: fits + 1,
                    downloaders.YOUTUBE_720_FORMAT: fits,
                },
            )

        self.assertEqual(
            attempted_formats,
            [
                downloaders.YOUTUBE_1080_FORMAT,
                downloaders.YOUTUBE_720_FORMAT,
            ],
        )

    async def test_incorrect_fit_estimate_retries_one_lower_quality(self):
        megabyte = 1024 * 1024
        too_large = MAX_MB * megabyte + 1
        metadata = self.make_youtube_metadata(
            video_sizes={
                1080: 20 * megabyte,
                720: 12 * megabyte,
            },
            audio_size=2 * megabyte,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            _, attempted_formats = await self.run_youtube_with_metadata(
                temp_dir,
                metadata,
                {
                    downloaders.YOUTUBE_1080_FORMAT: too_large,
                    downloaders.YOUTUBE_720_FORMAT: 14 * megabyte,
                },
            )

        self.assertEqual(
            attempted_formats,
            [
                downloaders.YOUTUBE_1080_FORMAT,
                downloaders.YOUTUBE_720_FORMAT,
            ],
        )

    async def test_1080p_succeeds_and_fits(self):
        fits = MAX_MB * 1024 * 1024

        with tempfile.TemporaryDirectory() as temp_dir:
            result, attempted_formats = await self.run_youtube_quality_sizes(
                temp_dir,
                {downloaders.YOUTUBE_1080_FORMAT: fits},
            )

            self.assertEqual(os.path.getsize(result), fits)

        self.assertEqual(
            attempted_formats,
            [downloaders.YOUTUBE_1080_FORMAT],
        )

    async def test_1080p_too_large_then_720p_fits(self):
        fits = MAX_MB * 1024 * 1024
        too_large = fits + 1

        with tempfile.TemporaryDirectory() as temp_dir:
            result, attempted_formats = await self.run_youtube_quality_sizes(
                temp_dir,
                {
                    downloaders.YOUTUBE_1080_FORMAT: too_large,
                    downloaders.YOUTUBE_720_FORMAT: fits,
                },
            )

            self.assertEqual(os.path.getsize(result), fits)

        self.assertEqual(
            attempted_formats,
            [
                downloaders.YOUTUBE_1080_FORMAT,
                downloaders.YOUTUBE_720_FORMAT,
            ],
        )

    async def test_1080p_and_720p_too_large_then_480p_fits(self):
        fits = MAX_MB * 1024 * 1024
        too_large = fits + 1

        with tempfile.TemporaryDirectory() as temp_dir:
            result, attempted_formats = await self.run_youtube_quality_sizes(
                temp_dir,
                {
                    downloaders.YOUTUBE_1080_FORMAT: too_large,
                    downloaders.YOUTUBE_720_FORMAT: too_large,
                    downloaders.YOUTUBE_480_FORMAT: fits,
                },
            )

            self.assertEqual(os.path.getsize(result), fits)

        self.assertEqual(
            attempted_formats,
            list(downloaders.YOUTUBE_FORMATS),
        )

    async def test_all_youtube_qualities_too_large(self):
        too_large = MAX_MB * 1024 * 1024 + 1
        attempted_formats = []

        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir, "video.mp4")

            async def run_command_side_effect(command, user_id, timeout):
                format_selector = downloaders.get_format_selector(command)
                attempted_formats.append(format_selector)
                with video_path.open("wb") as video:
                    video.truncate(too_large)
                Path(temp_dir, "video.mp4.part").write_bytes(b"fragment")
                return command_result(0, stdout="download complete")

            with patch.object(
                downloaders,
                "run_command",
                AsyncMock(side_effect=run_command_side_effect),
            ):
                with self.assertRaises(DownloadFileTooLargeError):
                    await downloaders.download_video(
                        "youtube",
                        "https://example.com/video",
                        temp_dir,
                        user_id=123,
                    )

            self.assertEqual(list(Path(temp_dir).rglob("*")), [])

        self.assertEqual(
            attempted_formats,
            list(downloaders.YOUTUBE_FORMATS),
        )

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


class InstagramPhotoDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_photo_download_uses_configured_proxy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(
                temp_dir,
                "instagram_photo",
                "photo.jpg",
            )

            async def run_command_side_effect(command, user_id, timeout):
                image_path.write_bytes(b"photo")
                return command_result(0, stdout="download complete")

            run_command = AsyncMock(side_effect=run_command_side_effect)
            with (
                patch.object(
                    downloaders,
                    "INSTAGRAM_PROXY",
                    "http://proxy.example:8080",
                ),
                patch.object(downloaders, "run_command", run_command),
                patch("builtins.print"),
            ):
                result = await downloaders.download_instagram_photo(
                    "https://www.instagram.com/p/test/",
                    temp_dir,
                    user_id=123,
                )

        self.assertEqual(result, str(image_path))
        command = run_command.await_args.args[0]
        self.assertEqual(command[0], "gallery-dl")
        proxy_index = command.index("--proxy")
        self.assertEqual(
            command[proxy_index + 1],
            "http://proxy.example:8080",
        )
        timeout_index = command.index("--http-timeout")
        self.assertEqual(command[timeout_index + 1], "30")
        retry_index = command.index("-R")
        self.assertEqual(command[retry_index + 1], "0")

    async def test_429_output_raises_controlled_download_error(self):
        run_command = AsyncMock(
            return_value=command_result(
                1,
                stdout="HTTP Error 429: Too Many Requests",
                stderr="raw Instagram response",
            )
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(downloaders, "run_command", run_command),
                patch.object(downloaders.LOGGER, "warning") as warning,
                patch("builtins.print"),
            ):
                with self.assertRaises(InstagramRateLimitError) as context:
                    await downloaders.download_instagram_photo(
                        "https://www.instagram.com/p/test/",
                        temp_dir,
                        user_id=123,
                    )

        self.assertEqual(run_command.await_count, 1)
        command = run_command.await_args.args[0]
        timeout_index = command.index("--http-timeout")
        self.assertEqual(command[timeout_index + 1], "30")
        retry_index = command.index("-R")
        self.assertEqual(command[retry_index + 1], "0")
        self.assertEqual(
            context.exception.last_error,
            "Instagram photo download rate limited.",
        )
        self.assertNotIn(
            "raw Instagram response",
            context.exception.last_error,
        )
        warning.assert_called_once_with(
            "Instagram gallery-dl rate limited for user %s (HTTP 429)",
            123,
        )

    async def test_multiple_images_raise_carousel_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            gallery_dir = Path(temp_dir, "instagram_photo")

            async def run_command_side_effect(command, user_id, timeout):
                Path(gallery_dir, "one.jpg").write_bytes(b"one")
                Path(gallery_dir, "two.jpg").write_bytes(b"two")
                return command_result(0, stdout="download complete")

            with (
                patch.object(
                    downloaders,
                    "run_command",
                    AsyncMock(side_effect=run_command_side_effect),
                ),
                patch("builtins.print"),
            ):
                with self.assertRaises(
                    InstagramCarouselNotSupportedError
                ):
                    await downloaders.download_instagram_photo(
                        "https://www.instagram.com/p/test/",
                        temp_dir,
                        user_id=123,
                    )

    async def test_mixed_media_carousel_raises_carousel_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            gallery_dir = Path(temp_dir, "instagram_photo")

            async def run_command_side_effect(command, user_id, timeout):
                Path(gallery_dir, "one.jpg").write_bytes(b"one")
                Path(gallery_dir, "two.mp4").write_bytes(b"two")
                return command_result(0, stdout="download complete")

            with (
                patch.object(
                    downloaders,
                    "run_command",
                    AsyncMock(side_effect=run_command_side_effect),
                ),
                patch("builtins.print"),
            ):
                with self.assertRaises(
                    InstagramCarouselNotSupportedError
                ):
                    await downloaders.download_instagram_photo(
                        "https://www.instagram.com/p/test/",
                        temp_dir,
                        user_id=123,
                    )

    async def test_gallery_failure_raises_controlled_download_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(
                    downloaders,
                    "run_command",
                    AsyncMock(
                        return_value=command_result(
                            1,
                            stderr="private raw gallery error",
                        )
                    ),
                ),
                patch("builtins.print"),
            ):
                with self.assertRaises(DownloadFailedError) as context:
                    await downloaders.download_instagram_photo(
                        "https://www.instagram.com/p/test/",
                        temp_dir,
                        user_id=123,
                    )

        self.assertEqual(
            context.exception.last_error,
            "Instagram photo download failed.",
        )
        self.assertNotIn(
            "private raw gallery error",
            context.exception.last_error,
        )

    async def test_missing_image_raises_download_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(
                    downloaders,
                    "run_command",
                    AsyncMock(return_value=command_result(0)),
                ),
                patch("builtins.print"),
            ):
                with self.assertRaises(DownloadFailedError) as context:
                    await downloaders.download_instagram_photo(
                        "https://www.instagram.com/p/test/",
                        temp_dir,
                        user_id=123,
                    )

        self.assertEqual(
            context.exception.last_error,
            "Instagram photo not found.",
        )


class PinterestDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_video_download_uses_generic_flow_and_perf_logging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir, "pinterest-video.mp4")

            async def run_command_side_effect(command, user_id, timeout):
                video_path.write_bytes(b"video")
                return command_result(
                    0,
                    stdout=(
                        "[info] Pin: Downloading 1 format(s): "
                        "v720+a1"
                    ),
                )

            with (
                patch.object(
                    downloaders,
                    "run_command",
                    AsyncMock(side_effect=run_command_side_effect),
                ),
                patch("builtins.print") as mock_print,
            ):
                result = await downloaders.download_video(
                    "pinterest",
                    "https://pin.it/AbCd123",
                    temp_dir,
                    user_id=123,
                )

        self.assertEqual(result, str(video_path))
        output = [call.args[0] for call in mock_print.call_args_list]
        self.assertTrue(any(
            "platform=pinterest selected_format=" in line
            and "format_id=v720+a1" in line
            for line in output
        ))
        self.assertTrue(any(
            "platform=pinterest download=" in line
            for line in output
        ))

    async def test_image_only_pin_raises_controlled_error(self):
        raw_error = "ERROR: [Pinterest] Pin: No video formats found!"

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(
                    downloaders,
                    "run_command",
                    AsyncMock(
                        return_value=command_result(
                            1,
                            stderr=raw_error,
                        )
                    ),
                ),
                patch("builtins.print"),
            ):
                with self.assertRaises(
                    PinterestUnsupportedMediaError
                ) as context:
                    await downloaders.download_video(
                        "pinterest",
                        "https://www.pinterest.com/pin/123456789/",
                        temp_dir,
                        user_id=123,
                    )

        self.assertEqual(
            context.exception.last_error,
            "Pinterest Pin does not contain supported video media.",
        )
        self.assertNotIn(raw_error, context.exception.last_error)

    async def test_duration_and_file_size_errors_remain_classified(self):
        cases = (
            (
                "Pin does not pass filter "
                f"(duration <=? {MAX_DURATION_SECONDS}), skipping",
                DownloadDurationLimitError,
            ),
            (TOO_LARGE_OUTPUT, DownloadFileTooLargeError),
        )

        for command_output, expected_error in cases:
            with self.subTest(expected_error=expected_error.__name__):
                with tempfile.TemporaryDirectory() as temp_dir:
                    with (
                        patch.object(
                            downloaders,
                            "run_command",
                            AsyncMock(
                                return_value=command_result(
                                    1,
                                    stderr=command_output,
                                )
                            ),
                        ),
                        patch("builtins.print"),
                    ):
                        with self.assertRaises(expected_error):
                            await downloaders.download_video(
                                "pinterest",
                                "https://pin.it/AbCd123",
                                temp_dir,
                                user_id=123,
                            )


class DownloadConfigurationTests(unittest.TestCase):
    def test_duration_limit_is_fifteen_minutes(self):
        self.assertEqual(MAX_DURATION_SECONDS, 15 * 60)

    def test_performance_log_uses_dynamic_platform_and_stage(self):
        with (
            patch.object(downloaders.time, "perf_counter", return_value=12.5),
            patch("builtins.print") as mock_print,
        ):
            downloaders.log_performance(
                "instagram",
                "download",
                started_at=10.0,
            )

        mock_print.assert_called_once_with(
            "[PERF] platform=instagram download=2.50s",
            flush=True,
        )

    def test_selected_format_logs_are_server_side(self):
        metadata = {
            "formats": [
                {
                    "format_id": "v720",
                    "width": 1280,
                    "height": 720,
                    "vcodec": "avc1.4d401f",
                    "acodec": "none",
                },
                {
                    "format_id": "a1",
                    "vcodec": "none",
                    "acodec": "mp4a.40.2",
                },
            ],
        }
        with patch("builtins.print") as mock_print:
            downloaders.log_selected_format(
                "youtube",
                downloaders.YOUTUBE_1080_FORMAT,
                "[info] video: Downloading 1 format(s): v720+a1",
                metadata,
            )
            downloaders.log_selected_format(
                "twitter",
                "best[height<=480]",
                "[info] video: Downloading 1 format(s): http-123",
            )

        self.assertEqual(mock_print.call_count, 2)
        youtube_output = mock_print.call_args_list[0]
        twitter_output = mock_print.call_args_list[1]
        self.assertIn("platform=youtube", youtube_output.args[0])
        self.assertIn("selected_quality=1080p", youtube_output.args[0])
        self.assertIn("actual_width=1280", youtube_output.args[0])
        self.assertIn("actual_height=720", youtube_output.args[0])
        self.assertIn(
            "actual_resolution=1280x720",
            youtube_output.args[0],
        )
        self.assertIn("format_id=v720+a1", youtube_output.args[0])
        self.assertIn("vcodec=avc1.4d401f", youtube_output.args[0])
        self.assertIn("acodec=mp4a.40.2", youtube_output.args[0])
        self.assertIn("platform=twitter", twitter_output.args[0])
        self.assertIn("format_id=http-123", twitter_output.args[0])
        self.assertTrue(youtube_output.kwargs["flush"])
        self.assertTrue(twitter_output.kwargs["flush"])

    def test_pinterest_perf_logs_portrait_resolution_when_available(self):
        metadata = {
            "formats": [
                {
                    "format_id": "v720",
                    "width": 720,
                    "height": 1280,
                    "vcodec": "avc1.640028",
                    "acodec": "none",
                },
                {
                    "format_id": "a1",
                    "vcodec": "none",
                    "acodec": "mp4a.40.2",
                },
            ],
        }

        with patch("builtins.print") as mock_print:
            downloaders.log_selected_format(
                "pinterest",
                downloaders.PINTEREST_FORMAT,
                "[info] Pin: Downloading 1 format(s): v720+a1",
                metadata,
            )

        output = mock_print.call_args.args[0]
        self.assertIn("platform=pinterest", output)
        self.assertIn("actual_width=720", output)
        self.assertIn("actual_height=1280", output)
        self.assertIn("actual_resolution=720x1280", output)
        self.assertIn("vcodec=avc1.640028", output)
        self.assertIn("acodec=mp4a.40.2", output)

    def test_pinterest_video_command_preserves_portrait_quality(self):
        commands = downloaders.build_commands(
            "pinterest",
            "/tmp/%(title)s.%(ext)s",
            "https://pin.it/AbCd123",
        )

        self.assertEqual(len(commands), 1)
        command = commands[0]
        format_index = command.index("-f")
        self.assertEqual(
            command[format_index + 1],
            "bv[vcodec^=avc1]+ba/b[ext=mp4]/best",
        )
        sort_index = command.index("-S")
        self.assertEqual(command[sort_index + 1], "res:1080,br")
        self.assertNotIn("height<=1080", command[format_index + 1])
        self.assertIn("--merge-output-format", command)
        self.assertNotIn("--recode-video", command)

    def test_youtube_metadata_commands_do_not_download_media(self):
        commands = downloaders.build_youtube_metadata_commands(
            "https://example.com/video"
        )

        self.assertEqual(len(commands), 3)
        for command in commands:
            self.assertIn("--skip-download", command)
            self.assertIn("--dump-single-json", command)
            self.assertNotIn("--max-filesize", command)
            self.assertNotIn("-f", command)
            filter_index = command.index("--match-filter")
            self.assertEqual(
                command[filter_index + 1],
                f"duration <= {MAX_DURATION_SECONDS}",
            )

        self.assertIn(
            "youtube:player_client=default,-android_sdkless",
            commands[0],
        )
        self.assertIn("youtube:player_client=android", commands[1])
        self.assertNotIn("--extractor-args", commands[2])

    def test_format_size_estimation_priority(self):
        self.assertEqual(
            downloaders.estimate_format_size(
                {
                    "filesize": 100,
                    "filesize_approx": 200,
                    "tbr": 300,
                },
                duration=MAX_DURATION_SECONDS,
            ),
            100,
        )
        self.assertEqual(
            downloaders.estimate_format_size(
                {
                    "filesize_approx": 200,
                    "tbr": 300,
                },
                duration=MAX_DURATION_SECONDS,
            ),
            200,
        )

    def test_unknown_preferred_stream_size_is_not_underestimated(self):
        metadata = {
            "duration": 300,
            "formats": [
                {
                    "format_id": "v1080",
                    "height": 1080,
                    "vcodec": "avc1.640028",
                    "acodec": "none",
                },
                {
                    "format_id": "a1",
                    "vcodec": "none",
                    "acodec": "mp4a.40.2",
                },
                {
                    "format_id": "p1080",
                    "height": 1080,
                    "vcodec": "avc1.640028",
                    "acodec": "mp4a.40.2",
                    "filesize": 10 * 1024 * 1024,
                },
            ],
        }

        self.assertIsNone(
            downloaders.estimate_youtube_quality_size(
                metadata,
                max_height=1080,
                prefer_separate_streams=True,
            )
        )

    def test_youtube_quality_and_player_fallback_order(self):
        self.assertEqual(
            downloaders.YOUTUBE_1080_FORMAT,
            "bv*[vcodec^=avc1][height<=1080]"
            "+ba[acodec^=mp4a]"
            "/b[ext=mp4][height<=1080]",
        )
        self.assertEqual(
            downloaders.YOUTUBE_720_FORMAT,
            "bv*[vcodec^=avc1][height<=720]"
            "+ba[acodec^=mp4a]"
            "/b[ext=mp4][height<=720]",
        )
        self.assertEqual(
            downloaders.YOUTUBE_480_FORMAT,
            "b[ext=mp4][height<=480]"
            "/best[height<=480]"
            "/best",
        )

        commands = downloaders.build_commands(
            "youtube",
            "/tmp/%(title)s.%(ext)s",
            "https://example.com/video",
        )
        selectors = [
            downloaders.get_format_selector(command)
            for command in commands
        ]

        self.assertEqual(
            selectors,
            [
                downloaders.YOUTUBE_1080_FORMAT,
                downloaders.YOUTUBE_1080_FORMAT,
                downloaders.YOUTUBE_1080_FORMAT,
                downloaders.YOUTUBE_720_FORMAT,
                downloaders.YOUTUBE_720_FORMAT,
                downloaders.YOUTUBE_720_FORMAT,
                downloaders.YOUTUBE_480_FORMAT,
                downloaders.YOUTUBE_480_FORMAT,
                downloaders.YOUTUBE_480_FORMAT,
            ],
        )

        for quality_start in range(0, len(commands), 3):
            default_client, android_client, standard_client = commands[
                quality_start:quality_start + 3
            ]
            self.assertIn(
                "youtube:player_client=default,-android_sdkless",
                default_client,
            )
            self.assertIn(
                "youtube:player_client=android",
                android_client,
            )
            self.assertNotIn("--extractor-args", standard_client)

        for command in commands:
            self.assertNotIn("--recode-video", command)
            self.assertNotIn("--remux-video", command)

    def test_duration_limit_output_detection(self):
        self.assertTrue(
            downloaders.is_duration_limit_error(DURATION_LIMIT_OUTPUT)
        )
        self.assertTrue(
            downloaders.is_duration_limit_error(
                "[download] Reel does not pass filter "
                f"(duration <=? {MAX_DURATION_SECONDS}), skipping"
            )
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
        self.assertFalse(
            downloaders.is_duration_limit_error(
                "[instagram] duration is NA; continuing with filter "
                f"(duration <=? {MAX_DURATION_SECONDS})"
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
        for platform in (
            "youtube",
            "tiktok",
            "twitter",
            "instagram",
            "pinterest",
        ):
            commands = downloaders.build_commands(
                platform,
                "/tmp/%(title)s.%(ext)s",
                "https://example.com/video",
            )

            for command in commands:
                option_index = command.index("--max-filesize")
                self.assertEqual(command[option_index + 1], f"{MAX_MB}M")

    def test_all_commands_use_configured_duration_limit(self):
        expected_filters = {
            "youtube": f"duration <= {MAX_DURATION_SECONDS}",
            "tiktok": f"duration <= {MAX_DURATION_SECONDS}",
            "twitter": f"duration <= {MAX_DURATION_SECONDS}",
            "instagram": f"duration <=? {MAX_DURATION_SECONDS}",
            "pinterest": f"duration <=? {MAX_DURATION_SECONDS}",
        }

        for platform, expected_filter in expected_filters.items():
            commands = downloaders.build_commands(
                platform,
                "/tmp/%(title)s.%(ext)s",
                "https://example.com/video",
            )

            for command in commands:
                option_index = command.index("--match-filter")
                self.assertEqual(
                    command[option_index + 1],
                    expected_filter,
                )


class YoutubeMetadataExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def get_metadata_for_duration(self, duration):
        metadata = {
            "duration": duration,
            "formats": [],
        }

        with patch.object(
            downloaders,
            "run_command",
            AsyncMock(
                return_value=command_result(
                    0,
                    stdout=json.dumps(metadata),
                )
            ),
        ):
            return await downloaders.get_youtube_metadata(
                "https://example.com/video",
                user_id=123,
            )

    async def test_metadata_duration_14_59_is_accepted(self):
        metadata = await self.get_metadata_for_duration(14 * 60 + 59)

        self.assertEqual(metadata["duration"], 899)

    async def test_metadata_duration_15_00_is_accepted(self):
        metadata = await self.get_metadata_for_duration(15 * 60)

        self.assertEqual(metadata["duration"], MAX_DURATION_SECONDS)

    async def test_metadata_duration_15_01_is_rejected(self):
        with self.assertRaises(DownloadDurationLimitError):
            await self.get_metadata_for_duration(15 * 60 + 1)

    async def test_metadata_uses_player_client_fallback(self):
        metadata = {
            "duration": 120,
            "formats": [],
        }
        run_command = AsyncMock(side_effect=[
            command_result(1, stderr="first client failed"),
            command_result(0, stdout=json.dumps(metadata)),
        ])

        with patch.object(downloaders, "run_command", run_command):
            result = await downloaders.get_youtube_metadata(
                "https://example.com/video",
                user_id=123,
            )

        self.assertEqual(result, metadata)
        self.assertEqual(run_command.await_count, 2)

if __name__ == "__main__":
    unittest.main()
