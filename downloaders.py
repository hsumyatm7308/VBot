import asyncio
import glob
import logging
import os
import re
import signal
import subprocess
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
    error_tail,
)


LOGGER = logging.getLogger(__name__)

ACTIVE_USERS: set[int] = set()
ACTIVE_PROCESSES: dict[int, asyncio.subprocess.Process] = {}
CANCEL_REQUESTS: set[int] = set()


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
        rf"\bduration\s*<=\s*{MAX_DURATION_SECONDS}\b"
    )
    return (
        "does not pass filter" in normalized_error
        and duration_filter.search(normalized_error) is not None
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

    result = await run_command(
        command,
        user_id,
        timeout=300,
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

    result = await run_command(
        command,
        user_id,
        timeout=180,
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

    return output_path


def build_commands(platform: str, output_template: str, url: str):
    common_options = [
        "--no-playlist",
        "--max-filesize", f"{MAX_MB}M",
        "--match-filter", f"duration <= {MAX_DURATION_SECONDS}",
    ]

    if platform == "youtube":
        return [
            [
                "yt-dlp",
                *common_options,
                "--extractor-args",
                "youtube:player_client=default,-android_sdkless",
                "-f",
                "bv*[vcodec^=avc1][height<=480]+ba[acodec^=mp4a]/b[ext=mp4][height<=480]/b",
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
                "youtube:player_client=android",
                "-f",
                "bv*[vcodec^=avc1][height<=480]+ba[acodec^=mp4a]/b[ext=mp4][height<=480]/b",
                "--merge-output-format",
                "mp4",
                "-o",
                output_template,
                url,
            ],
            [
                "yt-dlp",
                *common_options,
                "-f",
                "b[ext=mp4][height<=480]/best[height<=480]/best",
                "--merge-output-format",
                "mp4",
                "-o",
                output_template,
                url,
            ],
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

    return []


def find_downloaded_file(tmpdir):
    files = glob.glob(f"{tmpdir}/*")

    if not files:
        raise DownloadedFileNotFoundError

    return max(files, key=os.path.getsize)


async def download_video(
    platform: str,
    url: str,
    tmpdir: str,
    user_id: int,
):
    output_template = f"{tmpdir}/%(title).80s [%(id)s].%(ext)s"
    commands = build_commands(platform, output_template, url)

    last_error = ""
    too_large_error = ""
    duration_limit_error = ""

    for command in commands:
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

        if duration_limited:
            duration_limit_error = output_tail

        if file_too_large:
            too_large_error = output_tail

        if result.returncode == 0:
            try:
                return find_downloaded_file(tmpdir)
            except DownloadedFileNotFoundError:
                if not duration_limited and not file_too_large:
                    last_error = (
                        output_tail
                        or "yt-dlp completed without creating a file."
                    )

                continue

        last_error = (
            output_tail
            or f"yt-dlp exited with code {result.returncode}."
        )

    if duration_limit_error:
        raise DownloadDurationLimitError(duration_limit_error)

    if too_large_error:
        raise DownloadFileTooLargeError(too_large_error)

    LOGGER.warning(
        "All yt-dlp attempts failed for user %s on %s: %s",
        user_id,
        platform,
        last_error,
    )
    raise DownloadFailedError(last_error)
