"""Compatibility façade for Telegram handlers.

Implementation is split across :mod:`telegram_handlers`. Existing imports
used by ``bot.py`` and tests remain supported.
"""

import logging
import time
from types import SimpleNamespace

from config import (
    ALLOWED_USERS,
    DAILY_LIMIT,
    LEGAL_CONTACT,
    MAX_DURATION_SECONDS,
    MAX_MB,
    PUBLIC_ACCESS,
    TERMS_VERSION,
)
from database import (
    get_daily_usage,
    get_remaining_downloads,
    get_user_language,
    has_accepted_terms,
    increment_daily_usage,
    save_terms_acceptance,
    set_user_language,
)
from downloaders import (
    begin_download,
    cancel_download,
    download_instagram_photo,
    download_tiktok_photo,
    download_video,
    finish_download,
    is_download_active,
    is_download_cancelled,
    raise_if_cancelled,
)
from i18n import DEFAULT_LANGUAGE, get_text
from platforms import (
    get_platform,
    is_http_url,
    is_instagram_post_url,
    is_instagram_story_url,
    is_tiktok_photo_url,
    resolve_tiktok_url,
)
from telegram_handlers import cancellation, commands, download, ui
from utils import (
    DownloadCancelledError,
    DownloadDurationLimitError,
    DownloadFailedError,
    DownloadFileTooLargeError,
    DownloadedFileNotFoundError,
    InstagramCarouselNotSupportedError,
    InstagramRateLimitError,
    PinterestUnsupportedMediaError,
    get_file_size_mb,
    keep_user_updated,
)


LOGGER = logging.getLogger(__name__)

ACTIVE_DOWNLOAD_TASKS = cancellation.ACTIVE_DOWNLOAD_TASKS
ACTIVE_STATUS_MESSAGES = cancellation.ACTIVE_STATUS_MESSAGES

safe_edit_message = ui.safe_edit_message
get_language = ui.get_language
get_terms_text = ui.get_terms_text
get_language_keyboard = ui.get_language_keyboard
get_main_menu_keyboard = ui.get_main_menu_keyboard
get_back_keyboard = ui.get_back_keyboard
get_home_keyboard = ui.get_home_keyboard
get_cancel_keyboard = ui.get_cancel_keyboard
get_terms_keyboard = ui.get_terms_keyboard
get_terms_declined_keyboard = ui.get_terms_declined_keyboard
safe_edit_status_message = ui.safe_edit_status_message
send_language_prompt = ui.send_language_prompt
require_language = ui.require_language
show_home_query = ui.show_home_query
send_terms = ui.send_terms

handle_language_callback = commands.handle_language_callback
handle_terms_callback = commands.handle_terms_callback
start = commands.start
help_command = commands.help_command
status_command = commands.status_command
language_command = commands.language_command
terms_command = commands.terms_command
report_command = commands.report_command
myid = commands.myid
handle_menu_callback = commands.handle_menu_callback

request_download_cancellation = cancellation.request_download_cancellation
cancel_command = cancellation.cancel_command
handle_cancel_callback = cancellation.handle_cancel_callback


def log_performance(platform: str, stage: str, started_at: float):
    elapsed = time.perf_counter() - started_at
    print(
        f"[PERF] platform={platform} {stage}={elapsed:.2f}s",
        flush=True,
    )


def is_user_allowed(user_id: int) -> bool:
    if PUBLIC_ACCESS:
        return True

    return user_id in ALLOWED_USERS


def _download_dependencies():
    return SimpleNamespace(
        public_access=PUBLIC_ACCESS,
        allowed_users=ALLOWED_USERS,
        daily_limit=DAILY_LIMIT,
        max_duration_seconds=MAX_DURATION_SECONDS,
        max_mb=MAX_MB,
        logger=LOGGER,
        active_download_tasks=ACTIVE_DOWNLOAD_TASKS,
        active_status_messages=ACTIVE_STATUS_MESSAGES,
        get_text=get_text,
        get_language=get_language,
        get_home_keyboard=get_home_keyboard,
        get_cancel_keyboard=get_cancel_keyboard,
        safe_edit_status_message=safe_edit_status_message,
        send_language_prompt=send_language_prompt,
        send_terms=send_terms,
        get_user_language=get_user_language,
        has_accepted_terms=has_accepted_terms,
        get_daily_usage=get_daily_usage,
        get_remaining_downloads=get_remaining_downloads,
        increment_daily_usage=increment_daily_usage,
        is_download_active=is_download_active,
        begin_download=begin_download,
        finish_download=finish_download,
        is_download_cancelled=is_download_cancelled,
        raise_if_cancelled=raise_if_cancelled,
        is_http_url=is_http_url,
        get_platform=get_platform,
        resolve_tiktok_url=resolve_tiktok_url,
        is_tiktok_photo_url=is_tiktok_photo_url,
        is_instagram_post_url=is_instagram_post_url,
        is_instagram_story_url=is_instagram_story_url,
        download_tiktok_photo=download_tiktok_photo,
        download_instagram_photo=download_instagram_photo,
        download_video=download_video,
        keep_user_updated=keep_user_updated,
        get_file_size_mb=get_file_size_mb,
        log_performance=log_performance,
    )


async def handle_url(update, context):
    return await download.handle_url(
        update,
        context,
        _download_dependencies(),
    )
