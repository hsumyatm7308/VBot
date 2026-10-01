import glob
import os
import re
import time

from config import MAX_DURATION_SECONDS, MAX_MB
from downloader_core.formats import (
    YOUTUBE_QUALITY_HEIGHTS,
    format_media_properties,
    get_actual_media_properties,
    get_format_selector,
)
from downloader_core.pinterest import is_unsupported_media_error
from downloader_core.youtube import cleanup_attempt_files
from utils import (
    DownloadDurationLimitError,
    DownloadFileTooLargeError,
    DownloadedFileNotFoundError,
    DownloadFailedError,
    PinterestUnsupportedMediaError,
    error_tail,
)


def is_file_too_large_error(error_text: str) -> bool:
    normalized_error = error_text.lower()
    unsupported_option_errors = (
        "no such option",
        "unknown option",
        "unrecognized option",
    )

    if (
        "max-filesize" in normalized_error
        and any(
            marker in normalized_error
            for marker in unsupported_option_errors
        )
    ):
        return False

    return (
        "max-filesize" in normalized_error
        or "file is larger than" in normalized_error
    )


def is_duration_limit_error(error_text: str) -> bool:
    normalized_error = " ".join(error_text.lower().split())
    duration_filter = re.compile(
        rf"\bduration\s*<=\s*\??\s*{MAX_DURATION_SECONDS}\b"
    )
    return (
        "does not pass filter" in normalized_error
        and duration_filter.search(normalized_error) is not None
    )


def find_downloaded_file(tmpdir):
    files = glob.glob(f"{tmpdir}/*")

    if not files:
        raise DownloadedFileNotFoundError

    return max(files, key=os.path.getsize)


def log_selected_format(
    platform: str,
    format_selector: str,
    command_output: str = "",
    metadata: dict | None = None,
):
    if not format_selector:
        return

    actual_properties = get_actual_media_properties(
        metadata,
        command_output,
    )
    actual_details = format_media_properties(actual_properties)

    if platform == "youtube":
        quality = YOUTUBE_QUALITY_HEIGHTS.get(format_selector)
        details = (
            f"[PERF] platform=youtube selected_quality={quality}p "
            f"selected_format={format_selector}"
        )
        if actual_details:
            details = f"{details} {actual_details}"
        print(details, flush=True)
        return

    details = (
        f"[PERF] platform={platform} selected_format={format_selector}"
    )
    if actual_details:
        details = f"{details} {actual_details}"
    print(details, flush=True)


async def run_download_commands(
    platform: str,
    commands,
    tmpdir: str,
    user_id: int,
    metadata: dict | None = None,
    *,
    run_command,
    logger,
    selected_format_logger=log_selected_format,
):
    last_error = ""
    too_large_error = ""
    duration_limit_error = ""
    unsupported_media_error = ""
    oversized_youtube_format = ""
    max_size_bytes = MAX_MB * 1024 * 1024

    for command in commands:
        format_selector = get_format_selector(command)
        if (
            platform == "youtube"
            and oversized_youtube_format
            and format_selector == oversized_youtube_format
        ):
            continue

        result = await run_command(
            command,
            user_id,
            timeout=300,
        )
        command_output = "\n".join(
            output
            for output in (result.stdout, result.stderr)
            if output
        )
        output_tail = error_tail(command_output, 1000)
        duration_limited = is_duration_limit_error(command_output)
        file_too_large = is_file_too_large_error(command_output)
        unsupported_media = (
            platform == "pinterest"
            and is_unsupported_media_error(command_output)
        )

        if duration_limited:
            duration_limit_error = output_tail

        if file_too_large:
            too_large_error = output_tail

        if unsupported_media:
            unsupported_media_error = output_tail

        if result.returncode == 0:
            try:
                downloaded_file = find_downloaded_file(tmpdir)
            except DownloadedFileNotFoundError:
                if (
                    not duration_limited
                    and not file_too_large
                    and not unsupported_media
                ):
                    last_error = (
                        output_tail
                        or "yt-dlp completed without creating a file."
                    )

                continue

            if platform != "youtube":
                selected_format_logger(
                    platform,
                    format_selector,
                    command_output,
                )
                return downloaded_file

            file_size_bytes = os.path.getsize(downloaded_file)
            if file_size_bytes <= max_size_bytes:
                selected_format_logger(
                    platform,
                    format_selector,
                    command_output,
                    metadata,
                )
                return downloaded_file

            too_large_error = (
                "Downloaded YouTube file is larger than max-filesize "
                f"({file_size_bytes} bytes > {max_size_bytes} bytes)."
            )
            cleanup_attempt_files(tmpdir)
            oversized_youtube_format = format_selector
            continue

        last_error = (
            output_tail
            or f"yt-dlp exited with code {result.returncode}."
        )

    if duration_limit_error:
        raise DownloadDurationLimitError(duration_limit_error)

    if too_large_error:
        raise DownloadFileTooLargeError(too_large_error)

    if unsupported_media_error:
        raise PinterestUnsupportedMediaError(
            "Pinterest Pin does not contain supported video media."
        )

    logger.warning(
        "All yt-dlp attempts failed for user %s on %s: %s",
        user_id,
        platform,
        last_error,
    )
    raise DownloadFailedError(last_error)


async def download_video(
    platform: str,
    url: str,
    tmpdir: str,
    user_id: int,
    *,
    build_commands,
    get_youtube_metadata,
    select_youtube_start_format,
    get_youtube_commands_from_format,
    run_download_commands,
    log_performance,
):
    output_template = f"{tmpdir}/%(title).80s [%(id)s].%(ext)s"
    commands = build_commands(platform, output_template, url)
    metadata = None

    if platform == "youtube":
        preflight_started_at = time.perf_counter()
        try:
            metadata = await get_youtube_metadata(url, user_id)
        finally:
            log_performance(
                platform,
                "preflight",
                preflight_started_at,
            )

        if metadata is not None:
            start_format = select_youtube_start_format(metadata)
            commands = get_youtube_commands_from_format(
                commands,
                start_format,
            )

    download_started_at = time.perf_counter()
    try:
        return await run_download_commands(
            platform,
            commands,
            tmpdir,
            user_id,
            metadata,
        )
    finally:
        log_performance(
            platform,
            "download",
            download_started_at,
        )
