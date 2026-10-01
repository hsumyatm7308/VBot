"""Compatibility façade for downloader functionality.

Implementation is split across :mod:`downloader_core`. Existing imports from
this module remain supported.
"""

import logging
import time

from config import (
    INSTAGRAM_PROXY,
    MAX_DURATION_SECONDS,
    MAX_MB,
    TWITTER_PROXY,
)
from downloader_core import commands as command_builder
from downloader_core import instagram, pinterest, process, runner, tiktok
from downloader_core import youtube
from downloader_core.formats import (
    PINTEREST_FORMAT,
    PINTEREST_FORMAT_SORT,
    TIKTOK_FORMAT_SORT,
    TIKTOK_VIDEO_FORMAT,
    YOUTUBE_1080_FORMAT,
    YOUTUBE_480_FORMAT,
    YOUTUBE_720_FORMAT,
    YOUTUBE_FORMATS,
    YOUTUBE_PLAYER_CLIENT_FALLBACKS,
    YOUTUBE_QUALITY_HEIGHTS,
    YOUTUBE_SIZE_SAFETY_RATIO,
    estimate_format_size,
    format_media_properties,
    format_quality_key,
    get_actual_media_properties,
    get_downloaded_format_ids,
    get_format_selector,
    positive_number,
)
from utils import (
    DownloadCancelledError,
    DownloadDurationLimitError,
    DownloadFailedError,
    DownloadFileTooLargeError,
    DownloadedFileNotFoundError,
    InstagramCarouselNotSupportedError,
    InstagramRateLimitError,
    PinterestUnsupportedMediaError,
    error_tail,
)


LOGGER = logging.getLogger(__name__)

ACTIVE_USERS = process.ACTIVE_USERS
ACTIVE_PROCESSES = process.ACTIVE_PROCESSES
CANCEL_REQUESTS = process.CANCEL_REQUESTS

begin_download = process.begin_download
finish_download = process.finish_download
is_download_active = process.is_download_active
has_active_process = process.has_active_process
is_download_cancelled = process.is_download_cancelled
raise_if_cancelled = process.raise_if_cancelled
_signal_process = process._signal_process
_stop_process = process._stop_process
cancel_download = process.cancel_download
run_command = process.run_command

is_file_too_large_error = runner.is_file_too_large_error
is_duration_limit_error = runner.is_duration_limit_error
is_pinterest_unsupported_media_error = pinterest.is_unsupported_media_error
find_downloaded_file = runner.find_downloaded_file
log_selected_format = runner.log_selected_format

build_youtube_metadata_commands = youtube.build_metadata_commands
parse_youtube_metadata = youtube.parse_metadata
estimate_youtube_quality_size = youtube.estimate_quality_size
estimate_youtube_quality_sizes = youtube.estimate_quality_sizes
select_youtube_start_format = youtube.select_start_format
get_youtube_commands_from_format = youtube.get_commands_from_format
cleanup_youtube_attempt_files = youtube.cleanup_attempt_files

find_tiktok_photo_files = tiktok.find_photo_files


def log_performance(platform: str, stage: str, started_at: float):
    elapsed = time.perf_counter() - started_at
    print(
        f"[PERF] platform={platform} {stage}={elapsed:.2f}s",
        flush=True,
    )


async def get_youtube_metadata(url: str, user_id: int):
    return await youtube.get_metadata(
        url,
        user_id,
        run_command=run_command,
        is_duration_limit_error=is_duration_limit_error,
    )


async def make_tiktok_photo_video(
    image_path,
    audio_path,
    output_path,
    user_id,
):
    return await tiktok.make_photo_video(
        image_path,
        audio_path,
        output_path,
        user_id,
        run_command=run_command,
        log_performance=log_performance,
        logger=LOGGER,
    )


async def download_tiktok_photo(url, tmpdir, user_id):
    return await tiktok.download_photo(
        url,
        tmpdir,
        user_id,
        run_command=run_command,
        log_performance=log_performance,
        logger=LOGGER,
    )


async def download_instagram_photo(url, tmpdir, user_id):
    return await instagram.download_photo(
        url,
        tmpdir,
        user_id,
        proxy=INSTAGRAM_PROXY,
        run_command=run_command,
        log_performance=log_performance,
        logger=LOGGER,
    )


def build_commands(platform: str, output_template: str, url: str):
    return command_builder.build_commands(
        platform,
        output_template,
        url,
        instagram_proxy=INSTAGRAM_PROXY,
        twitter_proxy=TWITTER_PROXY,
    )


async def run_download_commands(
    platform: str,
    commands,
    tmpdir: str,
    user_id: int,
    metadata: dict | None = None,
):
    return await runner.run_download_commands(
        platform,
        commands,
        tmpdir,
        user_id,
        metadata,
        run_command=run_command,
        logger=LOGGER,
        selected_format_logger=log_selected_format,
    )


async def download_video(
    platform: str,
    url: str,
    tmpdir: str,
    user_id: int,
):
    return await runner.download_video(
        platform,
        url,
        tmpdir,
        user_id,
        build_commands=build_commands,
        get_youtube_metadata=get_youtube_metadata,
        select_youtube_start_format=select_youtube_start_format,
        get_youtube_commands_from_format=get_youtube_commands_from_format,
        run_download_commands=run_download_commands,
        log_performance=log_performance,
    )
