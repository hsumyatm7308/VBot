import glob
import os
import time
from pathlib import Path

from utils import (
    DownloadFailedError,
    InstagramCarouselNotSupportedError,
    InstagramRateLimitError,
    error_tail,
)


def build_video_commands(
    common_options,
    output_template,
    url,
    proxy,
):
    proxy_args = ["--proxy", proxy] if proxy else []

    return [
        [
            "yt-dlp",
            *common_options,
            *proxy_args,
            "--retries", "2",
            "--socket-timeout", "30",
            "-f", "b[ext=mp4][height<=720]/b[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", output_template,
            url,
        ],
        [
            "yt-dlp",
            *common_options,
            *proxy_args,
            "--retries", "2",
            "--socket-timeout", "45",
            "-f", "best",
            "--merge-output-format", "mp4",
            "-o", output_template,
            url,
        ],
    ]


async def download_photo(
    url,
    tmpdir,
    user_id,
    *,
    proxy,
    run_command,
    log_performance,
    logger,
):
    gallery_dir = os.path.join(tmpdir, "instagram_photo")
    os.makedirs(gallery_dir, exist_ok=True)

    proxy_args = ["--proxy", proxy] if proxy else []
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
        logger.warning(
            "Instagram gallery-dl rate limited for user %s (HTTP 429)",
            user_id,
        )
        raise InstagramRateLimitError(
            "Instagram photo download rate limited."
        )

    if result.returncode != 0:
        logger.warning(
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
