import asyncio
import glob
import os
import subprocess
from pathlib import Path

from config import TWITTER_PROXY
from utils import (
    DownloadedFileNotFoundError,
    DownloadFailedError,
    error_tail,
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


def make_tiktok_photo_video(image_path, audio_path, output_path):
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

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        raise RuntimeError(error_tail(result.stderr, 1000))


async def download_tiktok_photo(url, tmpdir):
    gallery_dir = os.path.join(tmpdir, "tiktok_photo")
    os.makedirs(gallery_dir, exist_ok=True)

    command = [
        "gallery-dl",
        "-D", gallery_dir,
        url,
    ]

    result = await asyncio.to_thread(
        subprocess.run,
        command,
        capture_output=True,
        text=True,
        timeout=180,
    )

    if result.returncode != 0:
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

    await asyncio.to_thread(
        make_tiktok_photo_video,
        images[0],
        audios[0],
        output_path,
    )

    return output_path


def build_commands(platform: str, output_template: str, url: str):
    common_options = [
        "--no-playlist",
        "--max-filesize", "45M",
        "--match-filter", "duration <= 600",
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

    return []


def find_downloaded_file(tmpdir):
    files = glob.glob(f"{tmpdir}/*")

    if not files:
        raise DownloadedFileNotFoundError

    return max(files, key=os.path.getsize)


async def download_video(platform: str, url: str, tmpdir: str):
    output_template = f"{tmpdir}/%(title).80s [%(id)s].%(ext)s"
    commands = build_commands(platform, output_template, url)

    result = None
    last_error = ""

    for command in commands:
        result = await asyncio.to_thread(
            subprocess.run,
            command,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode == 0:
            break

        last_error = error_tail(result.stderr, 1000)

    if result is None or result.returncode != 0:
        raise DownloadFailedError(last_error)

    return find_downloaded_file(tmpdir)
