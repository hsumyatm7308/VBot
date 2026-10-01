import json
import subprocess
from pathlib import Path

from config import MAX_DURATION_SECONDS, MAX_MB
from downloader_core.formats import (
    YOUTUBE_480_FORMAT,
    YOUTUBE_FORMATS,
    YOUTUBE_PLAYER_CLIENT_FALLBACKS,
    YOUTUBE_QUALITY_HEIGHTS,
    YOUTUBE_SIZE_SAFETY_RATIO,
    estimate_format_size,
    format_quality_key,
    get_format_selector,
    positive_number,
)
from utils import (
    DownloadDurationLimitError,
    DownloadFileTooLargeError,
    error_tail,
)


def build_video_commands(common_options, output_template, url):
    return [
        [
            "yt-dlp",
            *common_options,
            *player_client_options,
            "-f", format_selector,
            "--merge-output-format", "mp4",
            "-o", output_template,
            url,
        ]
        for format_selector in YOUTUBE_FORMATS
        for player_client_options in YOUTUBE_PLAYER_CLIENT_FALLBACKS
    ]


def build_metadata_commands(url: str):
    common_options = [
        "--no-playlist",
        "--skip-download",
        "--dump-single-json",
        "--match-filter", f"duration <= {MAX_DURATION_SECONDS}",
    ]

    return [
        [
            "yt-dlp",
            *common_options,
            *player_client_options,
            url,
        ]
        for player_client_options in YOUTUBE_PLAYER_CLIENT_FALLBACKS
    ]


def parse_metadata(output: str):
    candidates = [output, *reversed(output.splitlines())]

    for candidate in candidates:
        try:
            metadata = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue

        if isinstance(metadata, dict):
            return metadata

    return None


def estimate_quality_size(
    metadata: dict,
    max_height: int,
    prefer_separate_streams: bool,
):
    formats = metadata.get("formats") or []
    duration = metadata.get("duration")

    video_formats = [
        format_info
        for format_info in formats
        if str(format_info.get("vcodec", "none")).startswith("avc1")
        and str(format_info.get("acodec", "none")) == "none"
        and (positive_number(format_info.get("height")) or 0) <= max_height
    ]
    audio_formats = [
        format_info
        for format_info in formats
        if str(format_info.get("vcodec", "none")) == "none"
        and str(format_info.get("acodec", "none")).startswith("mp4a")
    ]

    if prefer_separate_streams and video_formats and audio_formats:
        video_format = max(video_formats, key=format_quality_key)
        audio_format = max(audio_formats, key=format_quality_key)
        video_size = estimate_format_size(video_format, duration)
        audio_size = estimate_format_size(audio_format, duration)

        if video_size is not None and audio_size is not None:
            return video_size + audio_size

        return None

    progressive_formats = [
        format_info
        for format_info in formats
        if str(format_info.get("vcodec", "none")) != "none"
        and str(format_info.get("acodec", "none")) != "none"
        and (positive_number(format_info.get("height")) or 0) <= max_height
    ]

    if not progressive_formats:
        return None

    def progressive_quality_key(format_info):
        preferred_codecs = (
            str(format_info.get("vcodec", "")).startswith("avc1")
            and str(format_info.get("acodec", "")).startswith("mp4a")
        )
        return (
            preferred_codecs,
            format_info.get("ext") == "mp4",
            *format_quality_key(format_info),
        )

    progressive_format = max(
        progressive_formats,
        key=progressive_quality_key,
    )
    return estimate_format_size(progressive_format, duration)


def estimate_quality_sizes(metadata: dict):
    return {
        format_selector: estimate_quality_size(
            metadata,
            YOUTUBE_QUALITY_HEIGHTS[format_selector],
            prefer_separate_streams=(
                format_selector != YOUTUBE_480_FORMAT
            ),
        )
        for format_selector in YOUTUBE_FORMATS
    }


def select_start_format(metadata: dict):
    estimates = estimate_quality_sizes(metadata)
    reliable_estimates = {
        format_selector: size
        for format_selector, size in estimates.items()
        if size is not None
    }

    if not reliable_estimates:
        return None

    safe_size_bytes = MAX_MB * 1024 * 1024 * YOUTUBE_SIZE_SAFETY_RATIO

    for format_selector in YOUTUBE_FORMATS:
        estimated_size = estimates[format_selector]
        if (
            estimated_size is not None
            and estimated_size <= safe_size_bytes
        ):
            return format_selector

    for format_selector in YOUTUBE_FORMATS:
        if estimates[format_selector] is None:
            return format_selector

    raise DownloadFileTooLargeError(
        "Estimated YouTube formats are larger than max-filesize "
        f"safety limit ({safe_size_bytes:.0f} bytes)."
    )


async def get_metadata(
    url: str,
    user_id: int,
    *,
    run_command,
    is_duration_limit_error,
):
    duration_limit_error = ""

    for command in build_metadata_commands(url):
        try:
            result = await run_command(
                command,
                user_id,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return None

        command_output = "\n".join(
            output
            for output in (result.stdout, result.stderr)
            if output
        )

        if is_duration_limit_error(command_output):
            duration_limit_error = error_tail(command_output, 1000)

        if result.returncode != 0:
            continue

        metadata = parse_metadata(result.stdout)
        if metadata is None:
            continue

        duration = positive_number(metadata.get("duration"))
        if duration is not None and duration > MAX_DURATION_SECONDS:
            raise DownloadDurationLimitError(
                "YouTube video does not pass filter "
                f"(duration <= {MAX_DURATION_SECONDS})."
            )

        return metadata

    if duration_limit_error:
        raise DownloadDurationLimitError(duration_limit_error)

    return None


def get_commands_from_format(commands, start_format):
    if start_format is None:
        return commands

    start_index = YOUTUBE_FORMATS.index(start_format)
    allowed_formats = set(YOUTUBE_FORMATS[start_index:])
    return [
        command
        for command in commands
        if get_format_selector(command) in allowed_formats
    ]


def cleanup_attempt_files(tmpdir: str):
    for path in Path(tmpdir).rglob("*"):
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
