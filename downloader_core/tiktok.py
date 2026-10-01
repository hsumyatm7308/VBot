import glob
import os
import time
from pathlib import Path

from downloader_core.formats import (
    TIKTOK_FORMAT_SORT,
    TIKTOK_VIDEO_FORMAT,
)
from utils import error_tail


def build_video_commands(common_options, output_template, url):
    extractor_fallbacks = (
        (),
        (
            "--extractor-args",
            "tiktok:api_hostname=api-h2.tiktokv.com",
        ),
        (
            "--extractor-args",
            "tiktok:api_hostname=api22-normal-c-useast2a.tiktokv.com",
        ),
    )
    return [
        [
            "yt-dlp",
            *common_options,
            *extractor_args,
            "-f", TIKTOK_VIDEO_FORMAT,
            "-S", TIKTOK_FORMAT_SORT,
            "--merge-output-format", "mp4",
            "-o", output_template,
            url,
        ]
        for extractor_args in extractor_fallbacks
    ]


def find_photo_files(tmpdir):
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


async def make_photo_video(
    image_path,
    audio_path,
    output_path,
    user_id,
    *,
    run_command,
    log_performance,
    logger,
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
        logger.warning(
            "ffmpeg failed for user %s: %s",
            user_id,
            error_tail(result.stderr, 1000),
        )
        raise RuntimeError(error_tail(result.stderr, 1000))


async def download_photo(
    url,
    tmpdir,
    user_id,
    *,
    run_command,
    log_performance,
    logger,
):
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
        logger.warning(
            "gallery-dl failed for user %s: %s",
            user_id,
            error_tail(result.stderr, 800),
        )
        raise RuntimeError(
            "TikTok photo download မအောင်မြင်ပါ။\n"
            + error_tail(result.stderr, 800)
        )

    images, audios = find_photo_files(gallery_dir)

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

    await make_photo_video(
        images[0],
        audios[0],
        output_path,
        user_id,
        run_command=run_command,
        log_performance=log_performance,
        logger=logger,
    )

    print(
        "[PERF] platform=tiktok selected_format=photo+audio "
        "vcodec=h264 acodec=aac",
        flush=True,
    )

    return output_path
