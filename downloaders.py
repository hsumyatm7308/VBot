import asyncio
import glob
import json
import logging
import os
import re
import signal
import subprocess
import time
from pathlib import Path

from config import (
    INSTAGRAM_PROXY,
    MAX_DURATION_SECONDS,
    MAX_MB,
    TWITTER_PROXY,
)
from utils import (
    DownloadDurationLimitError,
    DownloadFileTooLargeError,
    DownloadedFileNotFoundError,
    DownloadCancelledError,
    DownloadFailedError,
    InstagramCarouselNotSupportedError,
    InstagramRateLimitError,
    PinterestUnsupportedMediaError,
    error_tail,
)


LOGGER = logging.getLogger(__name__)

ACTIVE_USERS: set[int] = set()
ACTIVE_PROCESSES: dict[int, asyncio.subprocess.Process] = {}
CANCEL_REQUESTS: set[int] = set()

YOUTUBE_1080_FORMAT = (
    "bv*[vcodec^=avc1][height<=1080]"
    "+ba[acodec^=mp4a]"
    "/b[ext=mp4][height<=1080]"
)
YOUTUBE_720_FORMAT = (
    "bv*[vcodec^=avc1][height<=720]"
    "+ba[acodec^=mp4a]"
    "/b[ext=mp4][height<=720]"
)
YOUTUBE_480_FORMAT = (
    "b[ext=mp4][height<=480]"
    "/best[height<=480]"
    "/best"
)
YOUTUBE_FORMATS = (
    YOUTUBE_1080_FORMAT,
    YOUTUBE_720_FORMAT,
    YOUTUBE_480_FORMAT,
)
YOUTUBE_QUALITY_HEIGHTS = {
    YOUTUBE_1080_FORMAT: 1080,
    YOUTUBE_720_FORMAT: 720,
    YOUTUBE_480_FORMAT: 480,
}
YOUTUBE_PLAYER_CLIENT_FALLBACKS = (
    (
        "--extractor-args",
        "youtube:player_client=default,-android_sdkless",
    ),
    (
        "--extractor-args",
        "youtube:player_client=android",
    ),
    (),
)
YOUTUBE_SIZE_SAFETY_RATIO = 0.9
PINTEREST_FORMAT = "bv[vcodec^=avc1]+ba/b[ext=mp4]/best"
PINTEREST_FORMAT_SORT = "res:1080,br"


def log_performance(platform: str, stage: str, started_at: float):
    elapsed = time.perf_counter() - started_at
    print(
        f"[PERF] platform={platform} {stage}={elapsed:.2f}s",
        flush=True,
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


def is_pinterest_unsupported_media_error(error_text: str) -> bool:
    normalized_error = " ".join(error_text.lower().split())
    unsupported_media_markers = (
        "no video formats found",
        "does not contain a video",
        "no video could be found",
        "not a video pin",
    )
    return any(
        marker in normalized_error
        for marker in unsupported_media_markers
    )


def begin_download(user_id: int):
    CANCEL_REQUESTS.discard(user_id)
    ACTIVE_USERS.add(user_id)


def finish_download(user_id: int):
    ACTIVE_USERS.discard(user_id)
    CANCEL_REQUESTS.discard(user_id)


def is_download_active(user_id: int) -> bool:
    return user_id in ACTIVE_USERS


def has_active_process(user_id: int) -> bool:
    process = ACTIVE_PROCESSES.get(user_id)
    return process is not None and process.returncode is None


def is_download_cancelled(user_id: int) -> bool:
    return user_id in CANCEL_REQUESTS


def raise_if_cancelled(user_id: int):
    if is_download_cancelled(user_id):
        raise DownloadCancelledError


def _signal_process(process: asyncio.subprocess.Process, sig: signal.Signals):
    if process.returncode is not None:
        return

    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass
    except OSError:
        try:
            process.send_signal(sig)
        except ProcessLookupError:
            pass


async def _stop_process(process: asyncio.subprocess.Process):
    if process.returncode is not None:
        return

    _signal_process(process, signal.SIGTERM)

    try:
        await asyncio.wait_for(process.wait(), timeout=3)
        return
    except asyncio.TimeoutError:
        pass

    _signal_process(process, signal.SIGKILL)

    try:
        await process.wait()
    except ProcessLookupError:
        pass


async def cancel_download(user_id: int) -> bool:
    process = ACTIVE_PROCESSES.get(user_id)
    was_active = user_id in ACTIVE_USERS or process is not None

    if not was_active:
        return False

    CANCEL_REQUESTS.add(user_id)

    if process is not None:
        await _stop_process(process)

        if ACTIVE_PROCESSES.get(user_id) is process:
            ACTIVE_PROCESSES.pop(user_id, None)

    return True


async def run_command(command, user_id: int, timeout: int):
    raise_if_cancelled(user_id)

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    ACTIVE_PROCESSES[user_id] = process

    try:
        if is_download_cancelled(user_id):
            await _stop_process(process)
            raise DownloadCancelledError

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError as error:
            await _stop_process(process)
            raise subprocess.TimeoutExpired(command[0], timeout) from error
        except asyncio.CancelledError:
            await _stop_process(process)

            if is_download_cancelled(user_id):
                raise DownloadCancelledError from None

            raise
    finally:
        if ACTIVE_PROCESSES.get(user_id) is process:
            ACTIVE_PROCESSES.pop(user_id, None)

    raise_if_cancelled(user_id)


    return subprocess.CompletedProcess(
        command,
        process.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


def build_youtube_metadata_commands(url: str):
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


def parse_youtube_metadata(output: str):
    candidates = [output, *reversed(output.splitlines())]

    for candidate in candidates:
        try:
            metadata = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue

        if isinstance(metadata, dict):
            return metadata

    return None


def positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if number <= 0:
        return None

    return number


def estimate_format_size(format_info: dict, duration):
    for size_key in ("filesize", "filesize_approx"):
        size = positive_number(format_info.get(size_key))
        if size is not None:
            return size

    media_duration = (
        positive_number(duration)
        or positive_number(format_info.get("duration"))
    )
    if media_duration is None:
        return None

    bitrate = positive_number(format_info.get("tbr"))
    if bitrate is None:
        if str(format_info.get("vcodec", "none")) == "none":
            bitrate = positive_number(format_info.get("abr"))
        elif str(format_info.get("acodec", "none")) == "none":
            bitrate = positive_number(format_info.get("vbr"))

    if bitrate is None:
        return None

    return bitrate * 1000 * media_duration / 8


def format_quality_key(format_info: dict):
    return (
        positive_number(format_info.get("height")) or 0,
        positive_number(format_info.get("fps")) or 0,
        positive_number(format_info.get("tbr"))
        or positive_number(format_info.get("vbr"))
        or positive_number(format_info.get("abr"))
        or 0,
    )


def estimate_youtube_quality_size(
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


def estimate_youtube_quality_sizes(metadata: dict):
    return {
        format_selector: estimate_youtube_quality_size(
            metadata,
            YOUTUBE_QUALITY_HEIGHTS[format_selector],
            prefer_separate_streams=(
                format_selector != YOUTUBE_480_FORMAT
            ),
        )
        for format_selector in YOUTUBE_FORMATS
    }


def select_youtube_start_format(metadata: dict):
    estimates = estimate_youtube_quality_sizes(metadata)
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


async def get_youtube_metadata(url: str, user_id: int):
    duration_limit_error = ""

    for command in build_youtube_metadata_commands(url):
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

        metadata = parse_youtube_metadata(result.stdout)
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


def find_tiktok_photo_files(tmpdir):
    all_files = [
        path
        for path in glob.glob(f"{tmpdir}/**/*", recursive=True)
        if os.path.isfile(path)
    ]

    image_exts = {".jpg", ".jpeg", ".png", ".webp"}
    audio_exts = {".mp3", ".m4a", ".aac", ".wav", ".ogg"}

    images = [
        path
        for path in all_files
        if Path(path).suffix.lower() in image_exts
    ]

    audios = [
        path
        for path in all_files
        if Path(path).suffix.lower() in audio_exts
    ]

    return images, audios


async def make_tiktok_photo_video(
    image_path,
    audio_path,
    output_path,
    user_id,
):
    command = [
        "ffmpeg",
        "-y",
        "-loop", "1",
        "-i", image_path,
        "-i", audio_path,
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "stillimage",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        output_path,
    ]

    postprocess_started_at = time.perf_counter()
    try:
        result = await run_command(
            command,
            user_id,
            timeout=300,
        )
    finally:
        log_performance(
            "tiktok",
            "postprocess",
            postprocess_started_at,
        )

    if result.returncode != 0:
        LOGGER.warning(
            "ffmpeg failed for user %s: %s",
            user_id,
            error_tail(result.stderr, 1000),
        )
        raise RuntimeError(error_tail(result.stderr, 1000))


async def download_tiktok_photo(url, tmpdir, user_id):
    gallery_dir = os.path.join(tmpdir, "tiktok_photo")
    os.makedirs(gallery_dir, exist_ok=True)

    command = [
        "gallery-dl",
        "-D", gallery_dir,
        url,
    ]

    download_started_at = time.perf_counter()
    try:
        result = await run_command(
            command,
            user_id,
            timeout=180,
        )
    finally:
        log_performance(
            "tiktok",
            "download",
            download_started_at,
        )

    if result.returncode != 0:
        LOGGER.warning(
            "gallery-dl failed for user %s: %s",
            user_id,
            error_tail(result.stderr, 800),
        )
        raise RuntimeError(
            "TikTok photo download မအောင်မြင်ပါ။\n"
            + error_tail(result.stderr, 800)
        )

    images, audios = find_tiktok_photo_files(gallery_dir)

    if not images:
        raise RuntimeError("TikTok photo မတွေ့ပါ။")

    if len(images) > 1:
        raise RuntimeError(
            "📸 TikTok Photo Slideshow ကို လက်ရှိ မထောက်ပံ့သေးပါဘူး။"
        )

    if not audios:
        raise RuntimeError(
            "🎵 ဒီ TikTok photo post ရဲ့ audio ကို မတွေ့ပါ။"
        )

    output_path = os.path.join(tmpdir, "tiktok-photo.mp4")

    await make_tiktok_photo_video(
        images[0],
        audios[0],
        output_path,
        user_id,
    )

    print(
        "[PERF] platform=tiktok selected_format=photo+audio "
        "vcodec=h264 acodec=aac",
        flush=True,
    )

    return output_path


async def download_instagram_photo(url, tmpdir, user_id):
    gallery_dir = os.path.join(tmpdir, "instagram_photo")
    os.makedirs(gallery_dir, exist_ok=True)

    proxy_args = (
        ["--proxy", INSTAGRAM_PROXY]
        if INSTAGRAM_PROXY
        else []
    )
    command = [
        "gallery-dl",
        *proxy_args,
        "--http-timeout", "30",
        "-R", "0",
        "-D", gallery_dir,
        url,
    ]

    download_started_at = time.perf_counter()

    try:
        result = await run_command(
            command,
            user_id,
            timeout=180,
        )
    finally:
        log_performance(
            "instagram",
            "photo_download",
            download_started_at,
        )

    command_output = "\n".join(
        output
        for output in (result.stdout, result.stderr)
        if output
    )
    normalized_output = " ".join(
        command_output.lower().replace(":", " ").split()
    )

    if "429 too many requests" in normalized_output:
        LOGGER.warning(
            "Instagram gallery-dl rate limited for user %s (HTTP 429)",
            user_id,
        )
        raise InstagramRateLimitError(
            "Instagram photo download rate limited."
        )

    if result.returncode != 0:
        LOGGER.warning(
            "Instagram gallery-dl failed for user %s: %s",
            user_id,
            error_tail(result.stderr, 800),
        )

        raise DownloadFailedError(
            "Instagram photo download failed."
        )

    all_files = [
        path
        for path in glob.glob(
            f"{gallery_dir}/**/*",
            recursive=True,
        )
        if os.path.isfile(path)
    ]

    image_exts = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    }
    media_exts = image_exts | {
        ".m4v",
        ".mov",
        ".mp4",
        ".webm",
    }

    images = [
        path
        for path in all_files
        if Path(path).suffix.lower() in image_exts
    ]
    media_files = [
        path
        for path in all_files
        if Path(path).suffix.lower() in media_exts
    ]

    if len(media_files) > 1:
        raise InstagramCarouselNotSupportedError(
            "Instagram carousel is not supported yet."
        )

    if not images:
        raise DownloadFailedError(
            "Instagram photo not found."
        )

    print(
        "[PERF] platform=instagram selected_format=single_photo",
        flush=True,
    )

    return images[0]


def build_commands(platform: str, output_template: str, url: str):
    duration_filter = (
        f"duration <=? {MAX_DURATION_SECONDS}"
        if platform in {"instagram", "pinterest"}
        else f"duration <= {MAX_DURATION_SECONDS}"
    )
    common_options = [
        "--no-playlist",
        "--max-filesize", f"{MAX_MB}M",
        "--match-filter", duration_filter,
    ]

    if platform == "youtube":
        return [
            [
                "yt-dlp",
                *common_options,
                *player_client_options,
                "-f",
                format_selector,
                "--merge-output-format",
                "mp4",
                "-o",
                output_template,
                url,
            ]
            for format_selector in YOUTUBE_FORMATS
            for player_client_options in YOUTUBE_PLAYER_CLIENT_FALLBACKS
        ]

    if platform == "tiktok":
        return [
            [
                "yt-dlp",
                *common_options,
                "-f",
                "b[ext=mp4][height<=720]/best[height<=720]/best",
                "--merge-output-format",
                "mp4",
                "-o",
                output_template,
                url,
            ],
            [
                "yt-dlp",
                *common_options,
                "--extractor-args",
                "tiktok:api_hostname=api-h2.tiktokv.com",
                "-f",
                "b[ext=mp4][height<=720]/best[height<=720]/best",
                "--merge-output-format",
                "mp4",
                "-o",
                output_template,
                url,
            ],
            [
                "yt-dlp",
                *common_options,
                "--extractor-args",
                "tiktok:api_hostname=api22-normal-c-useast2a.tiktokv.com",
                "-f",
                "b[ext=mp4][height<=720]/best[height<=720]/best",
                "--merge-output-format",
                "mp4",
                "-o",
                output_template,
                url,
            ],
        ]

    if platform == "twitter":
        proxy_args = (
            ["--proxy", TWITTER_PROXY]
            if TWITTER_PROXY
            else []
        )

        return [
            [
                "yt-dlp",
                *common_options,
                *proxy_args,
                "--retries", "3",
                "--extractor-args",
                "twitter:api=syndication",
                "-f",
                "b[ext=mp4][height<=480]/best[height<=480]/best",
                "--merge-output-format",
                "mp4",
                "-o",
                output_template,
                url,
            ],
            [
                "yt-dlp",
                *common_options,
                *proxy_args,
                "--retries", "3",
                "--extractor-args",
                "twitter:api=legacy",
                "-f",
                "b[ext=mp4][height<=480]/best[height<=480]/best",
                "--merge-output-format",
                "mp4",
                "-o",
                output_template,
                url,
            ],
            [
                "yt-dlp",
                *common_options,
                *proxy_args,
                "--retries", "3",
                "-f",
                "b[ext=mp4][height<=480]/best[height<=480]/best",
                "--merge-output-format",
                "mp4",
                "-o",
                output_template,
                url,
            ],
        ]
    if platform == "instagram":
        proxy_args = (
            ["--proxy", INSTAGRAM_PROXY]
            if INSTAGRAM_PROXY
            else []
        )

        return [
            [
                "yt-dlp",
                *common_options,
                *proxy_args,
                "--retries", "2",
                "--socket-timeout", "30",
                "-f",
                "b[ext=mp4][height<=720]/b[ext=mp4]/best",
                "--merge-output-format",
                "mp4",
                "-o",
                output_template,
                url,
            ],
            [
                "yt-dlp",
                *common_options,
                *proxy_args,
                "--retries", "2",
                "--socket-timeout", "45",
                "-f",
                "best",
                "--merge-output-format",
                "mp4",
                "-o",
                output_template,
                url,
            ],
        ]

    if platform == "pinterest":
        return [
            [
                "yt-dlp",
                *common_options,
                "-f", PINTEREST_FORMAT,
                "-S", PINTEREST_FORMAT_SORT,
                "--merge-output-format", "mp4",
                "-o", output_template,
                url,
            ],
        ]

    return []


def find_downloaded_file(tmpdir):
    files = glob.glob(f"{tmpdir}/*")

    if not files:
        raise DownloadedFileNotFoundError

    return max(files, key=os.path.getsize)


def get_format_selector(command) -> str:
    try:
        option_index = command.index("-f")
        return command[option_index + 1]
    except (ValueError, IndexError):
        return ""


def get_youtube_commands_from_format(commands, start_format):
    if start_format is None:
        return commands

    start_index = YOUTUBE_FORMATS.index(start_format)
    allowed_formats = set(YOUTUBE_FORMATS[start_index:])
    return [
        command
        for command in commands
        if get_format_selector(command) in allowed_formats
    ]


def cleanup_youtube_attempt_files(tmpdir: str):
    for path in Path(tmpdir).rglob("*"):
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)


def get_downloaded_format_ids(command_output: str) -> str:
    matches = re.findall(
        r"Downloading(?:\s+\d+)?\s+format(?:\(s\)|s)?:\s*([^\r\n]+)",
        command_output,
        flags=re.IGNORECASE,
    )
    return matches[-1].strip() if matches else ""


def get_actual_media_properties(
    metadata: dict | None,
    command_output: str,
):
    format_ids = get_downloaded_format_ids(command_output)
    properties = {}

    if format_ids:
        properties["format_id"] = format_ids

    if not metadata or not format_ids:
        return properties

    formats_by_id = {
        str(format_info.get("format_id")): format_info
        for format_info in metadata.get("formats") or []
        if format_info.get("format_id") is not None
    }
    selected_formats = [
        formats_by_id[format_id.strip()]
        for format_id in format_ids.split("+")
        if format_id.strip() in formats_by_id
    ]

    video_formats = [
        format_info
        for format_info in selected_formats
        if str(format_info.get("vcodec", "none")) != "none"
    ]
    audio_formats = [
        format_info
        for format_info in selected_formats
        if str(format_info.get("acodec", "none")) != "none"
    ]

    if video_formats:
        video_format = max(video_formats, key=format_quality_key)
        width = positive_number(video_format.get("width"))
        height = positive_number(video_format.get("height"))
        metadata_resolution = str(
            video_format.get("resolution", "")
        ).strip()
        resolution_match = re.fullmatch(
            r"(\d+)x(\d+)",
            metadata_resolution,
        )

        if resolution_match is not None:
            if width is None:
                width = float(resolution_match.group(1))
            if height is None:
                height = float(resolution_match.group(2))

        if width is not None:
            properties["actual_width"] = int(width)
        if height is not None:
            properties["actual_height"] = int(height)
        if width is not None and height is not None:
            properties["actual_resolution"] = f"{int(width)}x{int(height)}"
        elif metadata_resolution and metadata_resolution != "audio only":
            properties["actual_resolution"] = metadata_resolution

        video_codec = str(video_format.get("vcodec", ""))
        if video_codec and video_codec != "none":
            properties["vcodec"] = video_codec

    if audio_formats:
        audio_codec = str(audio_formats[-1].get("acodec", ""))
        if audio_codec and audio_codec != "none":
            properties["acodec"] = audio_codec

    return properties


def format_media_properties(properties: dict) -> str:
    return " ".join(
        f"{key}={value}"
        for key, value in properties.items()
    )


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
            and is_pinterest_unsupported_media_error(command_output)
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
                log_selected_format(
                    platform,
                    format_selector,
                    command_output,
                )
                return downloaded_file

            file_size_bytes = os.path.getsize(downloaded_file)
            if file_size_bytes <= max_size_bytes:
                log_selected_format(
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
            cleanup_youtube_attempt_files(tmpdir)
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

    LOGGER.warning(
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
