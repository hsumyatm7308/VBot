import asyncio
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from utils import (
    DownloadCancelledError,
    DownloadDurationLimitError,
    DownloadFileTooLargeError,
    DownloadedFileNotFoundError,
    DownloadFailedError,
    InstagramCarouselNotSupportedError,
    InstagramRateLimitError,
    PinterestUnsupportedMediaError,
)


@dataclass(frozen=True)
class DownloadRequest:
    user_id: int
    language: str
    url: str
    platform: str
    is_tiktok_photo: bool
    is_instagram_post: bool


async def prepare_request(update, deps, request_started_at):
    user_id = update.effective_user.id
    language = deps.get_language(user_id)

    if not deps.public_access and user_id not in deps.allowed_users:
        await update.message.reply_text(
            deps.get_text(language, "private_access")
        )
        return None

    deps.logger.info(
        "Download request from user %s (%s)",
        user_id,
        update.effective_user.username,
    )

    stored_language = deps.get_user_language(user_id)
    if stored_language is None:
        await deps.send_language_prompt(update.message)
        return None

    language = stored_language

    if not deps.has_accepted_terms(user_id):
        await deps.send_terms(update.message, language)
        return None

    used_today = deps.get_daily_usage(user_id)
    if used_today >= deps.daily_limit:
        await update.message.reply_text(
            deps.get_text(
                language,
                "daily_limit_reached",
                daily_limit=deps.daily_limit,
            ),
            reply_markup=deps.get_home_keyboard(language),
        )
        return None

    if deps.is_download_active(user_id):
        await update.message.reply_text(
            deps.get_text(language, "active_download")
        )
        return None

    url = update.message.text.strip()
    if not deps.is_http_url(url):
        await update.message.reply_text(
            deps.get_text(language, "invalid_url")
        )
        return None

    if deps.is_instagram_story_url(url):
        await update.message.reply_text(
            deps.get_text(language, "instagram_story_not_supported")
        )
        return None

    platform = deps.get_platform(url)
    if platform is None:
        await update.message.reply_text(
            deps.get_text(language, "unsupported_url")
        )
        return None

    if platform == "tiktok":
        resolve_started_at = time.perf_counter()
        resolve_succeeded = False
        try:
            url = await deps.resolve_tiktok_url(url)
            resolve_succeeded = True
        finally:
            deps.log_performance(
                platform,
                "resolve",
                resolve_started_at,
            )
            if not resolve_succeeded:
                deps.log_performance(
                    platform,
                    "total",
                    request_started_at,
                )

        platform = deps.get_platform(url)

        if platform is None:
            deps.log_performance(
                "tiktok",
                "total",
                request_started_at,
            )
            await update.message.reply_text(
                deps.get_text(language, "tiktok_resolve_failed")
            )
            return None

    return DownloadRequest(
        user_id=user_id,
        language=language,
        url=url,
        platform=platform,
        is_tiktok_photo=(
            platform == "tiktok"
            and deps.is_tiktok_photo_url(url)
        ),
        is_instagram_post=(
            platform == "instagram"
            and deps.is_instagram_post_url(url)
        ),
    )


async def acquire_media(request, tmpdir, status_message, cancel_keyboard, deps):
    media_kind = "video"

    if request.is_tiktok_photo:
        await status_message.edit_text(
            deps.get_text(request.language, "preparing_media"),
            reply_markup=cancel_keyboard,
        )
        media_path = await deps.download_tiktok_photo(
            request.url,
            tmpdir,
            request.user_id,
        )
        return media_path, media_kind

    try:
        media_path = await deps.download_video(
            request.platform,
            request.url,
            tmpdir,
            request.user_id,
        )
    except DownloadFailedError:
        if not request.is_instagram_post:
            raise

        await status_message.edit_text(
            deps.get_text(request.language, "preparing_media"),
            reply_markup=cancel_keyboard,
        )
        media_path = await deps.download_instagram_photo(
            request.url,
            tmpdir,
            request.user_id,
        )
        media_kind = "photo"

    return media_path, media_kind


async def stop_progress_updates(status_task, stop_event):
    stop_event.set()
    if status_task is None:
        return None

    status_task.cancel()
    try:
        await status_task
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise

    return None


async def upload_media(update, request, media_path, media_kind, deps):
    upload_started_at = time.perf_counter()
    try:
        with open(media_path, "rb") as media:
            upload_options = {
                "caption": Path(media_path).name,
                "read_timeout": 120,
                "write_timeout": 120,
                "connect_timeout": 30,
                "pool_timeout": 30,
            }
            if media_kind == "photo":
                await update.message.reply_document(
                    document=media,
                    **upload_options,
                )
            else:
                await update.message.reply_video(
                    video=media,
                    supports_streaming=True,
                    **upload_options,
                )
    finally:
        deps.log_performance(
            request.platform,
            "upload",
            upload_started_at,
        )


async def handle_url(update, context, deps):
    request_started_at = time.perf_counter()
    request = await prepare_request(update, deps, request_started_at)
    if request is None:
        return

    user_id = request.user_id
    language = request.language
    platform = request.platform

    deps.begin_download(user_id)
    current_task = asyncio.current_task()
    if current_task is not None:
        deps.active_download_tasks[user_id] = current_task

    status_message = None
    stop_event = asyncio.Event()
    status_task = None
    cancel_keyboard = deps.get_cancel_keyboard(language)
    download_finished = False

    try:
        status_message = await update.message.reply_text(
            deps.get_text(language, "checking"),
            reply_markup=cancel_keyboard,
        )
        deps.active_status_messages[user_id] = status_message

        await status_message.edit_text(
            deps.get_text(language, "downloading"),
            reply_markup=cancel_keyboard,
        )
        status_task = asyncio.create_task(
            deps.keep_user_updated(
                status_message,
                stop_event,
                language,
                reply_markup=cancel_keyboard,
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            media_path, media_kind = await acquire_media(
                request,
                tmpdir,
                status_message,
                cancel_keyboard,
                deps,
            )

            deps.raise_if_cancelled(user_id)
            status_task = await stop_progress_updates(
                status_task,
                stop_event,
            )
            deps.raise_if_cancelled(user_id)

            size_mb = deps.get_file_size_mb(media_path)
            print(
                f"[PERF] platform={platform} file_size={size_mb:.2f}MB",
                flush=True,
            )

            if size_mb > deps.max_mb:
                await status_message.edit_text(
                    deps.get_text(
                        language,
                        "file_too_large_with_size",
                        size_mb=size_mb,
                        max_mb=deps.max_mb,
                    ),
                    reply_markup=deps.get_home_keyboard(language),
                )
                return

            await status_message.edit_text(
                deps.get_text(language, "uploading"),
                reply_markup=cancel_keyboard,
            )

            await upload_media(
                update,
                request,
                media_path,
                media_kind,
                deps,
            )

            deps.increment_daily_usage(user_id)
            deps.finish_download(user_id)
            download_finished = True

            used = deps.get_daily_usage(user_id)
            remaining = deps.get_remaining_downloads(user_id)

            await deps.safe_edit_status_message(
                status_message,
                deps.get_text(
                    language,
                    "done",
                    used=used,
                    daily_limit=deps.daily_limit,
                    remaining=remaining,
                ),
                reply_markup=deps.get_home_keyboard(language),
            )

    except DownloadCancelledError:
        await deps.safe_edit_status_message(
            status_message,
            deps.get_text(language, "cancelled"),
            reply_markup=deps.get_home_keyboard(language),
        )

    except DownloadDurationLimitError:
        await deps.safe_edit_status_message(
            status_message,
            deps.get_text(
                language,
                "video_too_long",
                max_duration_minutes=deps.max_duration_seconds / 60,
            ),
            reply_markup=deps.get_home_keyboard(language),
        )

    except DownloadFileTooLargeError:
        await deps.safe_edit_status_message(
            status_message,
            deps.get_text(language, "file_too_large"),
            reply_markup=deps.get_home_keyboard(language),
        )

    except InstagramCarouselNotSupportedError:
        await deps.safe_edit_status_message(
            status_message,
            deps.get_text(language, "instagram_carousel_not_supported"),
            reply_markup=deps.get_home_keyboard(language),
        )

    except InstagramRateLimitError:
        await deps.safe_edit_status_message(
            status_message,
            deps.get_text(
                language,
                "instagram_photo_temporarily_unavailable",
            ),
            reply_markup=deps.get_home_keyboard(language),
        )

    except PinterestUnsupportedMediaError:
        await deps.safe_edit_status_message(
            status_message,
            deps.get_text(language, "pinterest_video_only"),
            reply_markup=deps.get_home_keyboard(language),
        )

    except DownloadFailedError:
        await deps.safe_edit_status_message(
            status_message,
            deps.get_text(language, "download_failed"),
            reply_markup=deps.get_home_keyboard(language),
        )

    except DownloadedFileNotFoundError:
        deps.logger.warning("Downloaded file missing for user %s", user_id)
        await deps.safe_edit_status_message(
            status_message,
            deps.get_text(language, "download_failed"),
            reply_markup=deps.get_home_keyboard(language),
        )

    except subprocess.TimeoutExpired:
        deps.logger.warning("Download timed out for user %s", user_id)
        await deps.safe_edit_status_message(
            status_message,
            deps.get_text(language, "download_timeout"),
            reply_markup=deps.get_home_keyboard(language),
        )

    except asyncio.CancelledError:
        if deps.is_download_cancelled(user_id):
            await deps.safe_edit_status_message(
                status_message,
                deps.get_text(language, "cancelled"),
                reply_markup=deps.get_home_keyboard(language),
            )
        else:
            raise

    except Exception:
        deps.logger.exception(
            "Unexpected download error for user %s",
            user_id,
        )
        await deps.safe_edit_status_message(
            status_message,
            deps.get_text(language, "download_failed"),
            reply_markup=deps.get_home_keyboard(language),
        )

    finally:
        stop_event.set()
        propagate_cancellation = False

        if status_task is not None:
            status_task.cancel()
            try:
                await status_task
            except asyncio.CancelledError:
                task = asyncio.current_task()
                propagate_cancellation = (
                    task is not None
                    and task.cancelling() > 0
                    and not deps.is_download_cancelled(user_id)
                )

        if deps.active_download_tasks.get(user_id) is current_task:
            deps.active_download_tasks.pop(user_id, None)

        if deps.active_status_messages.get(user_id) is status_message:
            deps.active_status_messages.pop(user_id, None)

        if not download_finished:
            deps.finish_download(user_id)

        deps.log_performance(
            platform,
            "total",
            request_started_at,
        )

        if propagate_cancellation:
            raise asyncio.CancelledError
