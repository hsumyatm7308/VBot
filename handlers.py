import asyncio
import logging
import subprocess
import tempfile
import time
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from config import (
    PUBLIC_ACCESS,
    ALLOWED_USERS,
    DAILY_LIMIT,
    LEGAL_CONTACT,
    MAX_DURATION_SECONDS,
    MAX_MB,
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
    is_tiktok_photo_url,
    resolve_tiktok_url,
)
from utils import (
    DownloadCancelledError,
    DownloadDurationLimitError,
    DownloadFileTooLargeError,
    DownloadedFileNotFoundError,
    DownloadFailedError,
    get_file_size_mb,
    keep_user_updated,
)


LOGGER = logging.getLogger(__name__)

ACTIVE_DOWNLOAD_TASKS: dict[int, asyncio.Task] = {}
ACTIVE_STATUS_MESSAGES = {}


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


async def safe_edit_message(
    query,
    text,
    reply_markup=None,
    parse_mode=None,
):
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return

        raise


def get_language(user_id: int) -> str:
    return get_user_language(user_id) or DEFAULT_LANGUAGE


def get_terms_text(language: str = DEFAULT_LANGUAGE) -> str:
    return get_text(
        language,
        "terms",
        contact=LEGAL_CONTACT,
        version=TERMS_VERSION,
    )


def get_language_keyboard(
    language: str = DEFAULT_LANGUAGE,
    include_back: bool = False,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("English", callback_data="lang_en"),
            InlineKeyboardButton("မြန်မာ", callback_data="lang_my"),
        ]
    ]

    if include_back:
        rows.append([
            InlineKeyboardButton(
                get_text(language, "button_back"),
                callback_data="menu_home",
            )
        ])

    return InlineKeyboardMarkup(rows)


def get_main_menu_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                get_text(language, "button_help"),
                callback_data="menu_help",
            ),
            InlineKeyboardButton(
                get_text(language, "button_status"),
                callback_data="menu_status",
            ),
        ],
        [
            InlineKeyboardButton(
                get_text(language, "button_language"),
                callback_data="menu_language",
            ),
            InlineKeyboardButton(
                get_text(language, "button_terms"),
                callback_data="menu_terms",
            ),
        ],
        [
            InlineKeyboardButton(
                get_text(language, "button_report"),
                callback_data="menu_report",
            ),
            InlineKeyboardButton(
                get_text(language, "button_myid"),
                callback_data="menu_myid",
            ),
        ],
    ])


def get_back_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            get_text(language, "button_back"),
            callback_data="menu_home",
        )
    ]])


def get_home_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            get_text(language, "button_home"),
            callback_data="menu_home",
        )
    ]])


def get_cancel_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            get_text(language, "button_cancel"),
            callback_data="cancel_download",
        )
    ]])


def get_terms_keyboard(
    language: str,
    acceptance_required: bool,
) -> InlineKeyboardMarkup:
    if not acceptance_required:
        return get_back_keyboard(language)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                get_text(language, "button_accept"),
                callback_data=f"terms_accept:{TERMS_VERSION}",
            ),
            InlineKeyboardButton(
                get_text(language, "button_decline"),
                callback_data=f"terms_decline:{TERMS_VERSION}",
            ),
        ],
        [
            InlineKeyboardButton(
                get_text(language, "button_language"),
                callback_data="menu_language",
            )
        ],
    ])


def get_terms_declined_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            get_text(language, "button_terms"),
            callback_data="menu_terms",
        ),
        InlineKeyboardButton(
            get_text(language, "button_language"),
            callback_data="menu_language",
        ),
    ]])


async def safe_edit_status_message(message, text: str, reply_markup=None):
    if message is None:
        return

    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        pass


async def send_language_prompt(message, include_back: bool = False):
    language = get_language(message.from_user.id)
    await message.reply_text(
        get_text(language, "language_prompt"),
        reply_markup=get_language_keyboard(language, include_back),
    )


async def require_language(update: Update) -> str | None:
    user_id = update.effective_user.id
    language = get_user_language(user_id)

    if language is None:
        await send_language_prompt(update.message)
        return None

    return language


async def show_home_query(query, language: str):
    user_id = query.from_user.id

    if not has_accepted_terms(user_id):
        await safe_edit_message(
            query,
            get_terms_text(language),
            reply_markup=get_terms_keyboard(
                language,
                acceptance_required=True,
            ),
        )
        return

    await safe_edit_message(
        query,
        get_text(language, "home"),
        reply_markup=get_main_menu_keyboard(language),
    )


async def send_terms(message, language: str | None = None):
    user_id = message.from_user.id
    selected_language = language or get_language(user_id)
    acceptance_required = not has_accepted_terms(user_id)

    await message.reply_text(
        get_terms_text(selected_language),
        reply_markup=get_terms_keyboard(
            selected_language,
            acceptance_required,
        ),
    )


async def handle_language_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    if query.data not in {"lang_en", "lang_my"}:
        await query.answer()
        return

    user_id = update.effective_user.id
    selected_language = (
        "en"
        if query.data == "lang_en"
        else "my"
    )
    current_language = get_user_language(user_id)

    if current_language == selected_language:
        await query.answer()
        return

    await query.answer()
    set_user_language(user_id, selected_language)

    if not has_accepted_terms(user_id):
        await safe_edit_message(
            query,
            get_terms_text(selected_language),
            reply_markup=get_terms_keyboard(
                selected_language,
                acceptance_required=True,
            ),
        )
        return

    await show_home_query(query, selected_language)


async def handle_terms_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    language = get_language(user_id)
    data = query.data

    if data.startswith("terms_accept:"):
        version = data.split(":", 1)[1]

        if version != TERMS_VERSION:
            await safe_edit_message(
                query,
                get_text(language, "terms_updated")
                + "\n\n"
                + get_terms_text(language),
                reply_markup=get_terms_keyboard(
                    language,
                    acceptance_required=True,
                ),
            )
            return

        save_terms_acceptance(user_id)

        if get_user_language(user_id) is None:
            await safe_edit_message(
                query,
                get_text(DEFAULT_LANGUAGE, "language_prompt"),
                reply_markup=get_language_keyboard(),
            )
            return

        await show_home_query(query, language)
        return

    if data.startswith("terms_decline:"):
        await safe_edit_message(
            query,
            get_text(language, "terms_declined"),
            reply_markup=get_terms_declined_keyboard(language),
        )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id
    language = get_user_language(user_id)

    if language is None:
        await send_language_prompt(update.message)
        return

    if not has_accepted_terms(user_id):
        await send_terms(update.message, language)
        return

    await update.message.reply_text(
        get_text(language, "home"),
        reply_markup=get_main_menu_keyboard(language),
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    language = await require_language(update)
    if language is None:
        return

    await update.message.reply_text(
        get_text(language, "help", daily_limit=DAILY_LIMIT),
        reply_markup=get_back_keyboard(language),
    )


async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    language = await require_language(update)
    if language is None:
        return

    user_id = update.effective_user.id
    used = get_daily_usage(user_id)
    remaining = get_remaining_downloads(user_id)
    terms_key = (
        "terms_accepted"
        if has_accepted_terms(user_id)
        else "terms_not_accepted"
    )

    await update.message.reply_text(
        get_text(
            language,
            "status",
            used=used,
            daily_limit=DAILY_LIMIT,
            remaining=remaining,
            terms_status=get_text(language, terms_key),
        ),
        reply_markup=get_back_keyboard(language),
    )


async def language_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id
    language = get_language(user_id)
    await update.message.reply_text(
        get_text(language, "language_prompt"),
        reply_markup=get_language_keyboard(
            language,
            include_back=get_user_language(user_id) is not None,
        ),
    )


async def terms_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    language = await require_language(update)
    if language is None:
        return

    await send_terms(update.message, language)


async def report_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    language = await require_language(update)
    if language is None:
        return

    await update.message.reply_text(
        get_text(language, "report", contact=LEGAL_CONTACT),
        reply_markup=get_back_keyboard(language),
    )


async def myid(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    language = await require_language(update)
    if language is None:
        return

    user = update.effective_user
    username_line = ""
    if user.username:
        username_line = get_text(
            language,
            "username_line",
            username=user.username,
        )

    await update.message.reply_text(
        get_text(
            language,
            "myid",
            user_id=user.id,
            full_name=user.full_name,
            username_line=username_line,
        ),
        reply_markup=get_back_keyboard(language),
    )


async def handle_menu_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    action = query.data
    user_id = query.from_user.id
    stored_language = get_user_language(user_id)

    if stored_language is None:
        await safe_edit_message(
            query,
            get_text(DEFAULT_LANGUAGE, "language_prompt"),
            reply_markup=get_language_keyboard(),
        )
        return

    language = stored_language

    if action == "menu_home":
        await show_home_query(query, language)
        return

    if action == "menu_help":
        text = get_text(language, "help", daily_limit=DAILY_LIMIT)
    elif action == "menu_status":
        terms_key = (
            "terms_accepted"
            if has_accepted_terms(user_id)
            else "terms_not_accepted"
        )
        text = get_text(
            language,
            "status",
            used=get_daily_usage(user_id),
            daily_limit=DAILY_LIMIT,
            remaining=get_remaining_downloads(user_id),
            terms_status=get_text(language, terms_key),
        )
    elif action == "menu_language":
        await safe_edit_message(
            query,
            get_text(language, "language_prompt"),
            reply_markup=get_language_keyboard(
                language,
                include_back=True,
            ),
        )
        return
    elif action == "menu_terms":
        await safe_edit_message(
            query,
            get_terms_text(language),
            reply_markup=get_terms_keyboard(
                language,
                acceptance_required=not has_accepted_terms(user_id),
            ),
        )
        return
    elif action == "menu_report":
        text = get_text(language, "report", contact=LEGAL_CONTACT)
    elif action == "menu_myid":
        user = query.from_user
        username_line = ""
        if user.username:
            username_line = get_text(
                language,
                "username_line",
                username=user.username,
            )
        text = get_text(
            language,
            "myid",
            user_id=user.id,
            full_name=user.full_name,
            username_line=username_line,
        )
    else:
        return

    await safe_edit_message(
        query,
        text,
        reply_markup=get_back_keyboard(language),
    )


async def request_download_cancellation(user_id: int) -> bool:
    cancelled = await cancel_download(user_id)

    if not cancelled:
        return False

    task = ACTIVE_DOWNLOAD_TASKS.get(user_id)
    current_task = asyncio.current_task()

    if (
        task is not None
        and task is not current_task
        and not task.done()
    ):
        task.cancel()

        try:
            await asyncio.wait_for(
                asyncio.shield(task),
                timeout=5,
            )
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    return True


async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id
    language = get_language(user_id)
    status_message = ACTIVE_STATUS_MESSAGES.get(user_id)
    cancelled = await request_download_cancellation(user_id)

    if not cancelled:
        await update.message.reply_text(
            get_text(language, "no_active_download"),
            reply_markup=get_home_keyboard(language),
        )
        return

    if status_message is not None:
        await safe_edit_status_message(
            status_message,
            get_text(language, "cancelled"),
            reply_markup=get_home_keyboard(language),
        )
    else:
        await update.message.reply_text(
            get_text(language, "cancelled"),
            reply_markup=get_home_keyboard(language),
        )


async def handle_cancel_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    language = get_language(user_id)
    cancelled = await request_download_cancellation(user_id)
    text_key = "cancelled" if cancelled else "no_active_download"

    await safe_edit_message(
        query,
        get_text(language, text_key),
        reply_markup=get_home_keyboard(language),
    )


async def handle_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    request_started_at = time.perf_counter()
    user_id = update.effective_user.id
    language = get_language(user_id)

    if not PUBLIC_ACCESS and user_id not in ALLOWED_USERS:
        await update.message.reply_text(
            get_text(language, "private_access")
        )
        return

    LOGGER.info(
        "Download request from user %s (%s)",
        user_id,
        update.effective_user.username,
    )

    stored_language = get_user_language(user_id)
    if stored_language is None:
        await send_language_prompt(update.message)
        return

    language = stored_language

    if not has_accepted_terms(user_id):
        await send_terms(update.message, language)
        return

    used_today = get_daily_usage(user_id)
    if used_today >= DAILY_LIMIT:
        await update.message.reply_text(
            get_text(
                language,
                "daily_limit_reached",
                daily_limit=DAILY_LIMIT,
            ),
            reply_markup=get_home_keyboard(language),
        )
        return

    if is_download_active(user_id):
        await update.message.reply_text(
            get_text(language, "active_download")
        )
        return

    url = update.message.text.strip()
    if not is_http_url(url):
        await update.message.reply_text(
            get_text(language, "invalid_url")
        )
        return

    platform = get_platform(url)
    if platform is None:
        await update.message.reply_text(
            get_text(language, "unsupported_url")
        )
        return

    if platform == "tiktok":
        resolve_started_at = time.perf_counter()
        resolve_succeeded = False
        try:
            url = await resolve_tiktok_url(url)
            resolve_succeeded = True
        finally:
            log_performance(
                platform,
                "resolve",
                resolve_started_at,
            )
            if not resolve_succeeded:
                log_performance(
                    platform,
                    "total",
                    request_started_at,
                )

        platform = get_platform(url)

        if platform is None:
            log_performance(
                "tiktok",
                "total",
                request_started_at,
            )
            await update.message.reply_text(
                get_text(language, "tiktok_resolve_failed")
            )
            return

    is_tiktok_photo = (
        platform == "tiktok"
        and is_tiktok_photo_url(url)
    )

    begin_download(user_id)
    current_task = asyncio.current_task()
    if current_task is not None:
        ACTIVE_DOWNLOAD_TASKS[user_id] = current_task

    status_message = None
    stop_event = asyncio.Event()
    status_task = None
    cancel_keyboard = get_cancel_keyboard(language)
    download_finished = False

    try:
        status_message = await update.message.reply_text(
            get_text(language, "checking"),
            reply_markup=cancel_keyboard,
        )
        ACTIVE_STATUS_MESSAGES[user_id] = status_message

        await status_message.edit_text(
            get_text(language, "downloading"),
            reply_markup=cancel_keyboard,
        )
        status_task = asyncio.create_task(
            keep_user_updated(
                status_message,
                stop_event,
                language,
                reply_markup=cancel_keyboard,
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            if is_tiktok_photo:
                await status_message.edit_text(
                    get_text(language, "preparing_media"),
                    reply_markup=cancel_keyboard,
                )
                video_path = await download_tiktok_photo(
                    url,
                    tmpdir,
                    user_id,
                )
            else:
                video_path = await download_video(
                    platform,
                    url,
                    tmpdir,
                    user_id,
                )

            raise_if_cancelled(user_id)

            stop_event.set()
            if status_task is not None:
                status_task.cancel()
                try:
                    await status_task
                except asyncio.CancelledError:
                    task = asyncio.current_task()
                    if task is not None and task.cancelling():
                        raise
                status_task = None

            raise_if_cancelled(user_id)
            size_mb = get_file_size_mb(video_path)
            print(
                f"[PERF] platform={platform} file_size={size_mb:.2f}MB",
                flush=True,
            )

            if size_mb > MAX_MB:
                await status_message.edit_text(
                    get_text(
                        language,
                        "file_too_large_with_size",
                        size_mb=size_mb,
                        max_mb=MAX_MB,
                    ),
                    reply_markup=get_home_keyboard(language),
                )
                return

            await status_message.edit_text(
                get_text(language, "uploading"),
                reply_markup=cancel_keyboard,
            )

            upload_started_at = time.perf_counter()
            try:
                with open(video_path, "rb") as video:
                    await update.message.reply_video(
                        video=video,
                        caption=Path(video_path).name,
                        supports_streaming=True,
                        read_timeout=120,
                        write_timeout=120,
                        connect_timeout=30,
                        pool_timeout=30,
                    )
            finally:
                log_performance(
                    platform,
                    "upload",
                    upload_started_at,
                )

            increment_daily_usage(user_id)
            finish_download(user_id)
            download_finished = True

            used = get_daily_usage(user_id)
            remaining = get_remaining_downloads(user_id)

            await safe_edit_status_message(
                status_message,
                get_text(
                    language,
                    "done",
                    used=used,
                    daily_limit=DAILY_LIMIT,
                    remaining=remaining,
                ),
                reply_markup=get_home_keyboard(language),
            )

    except DownloadCancelledError:
        await safe_edit_status_message(
            status_message,
            get_text(language, "cancelled"),
            reply_markup=get_home_keyboard(language),
        )

    except DownloadDurationLimitError:
        await safe_edit_status_message(
            status_message,
            get_text(
                language,
                "video_too_long",
                max_duration_minutes=MAX_DURATION_SECONDS / 60,
            ),
            reply_markup=get_home_keyboard(language),
        )

    except DownloadFileTooLargeError:
        await safe_edit_status_message(
            status_message,
            get_text(language, "file_too_large"),
            reply_markup=get_home_keyboard(language),
        )

    except DownloadFailedError:
        await safe_edit_status_message(
            status_message,
            get_text(language, "download_failed"),
            reply_markup=get_home_keyboard(language),
        )

    except DownloadedFileNotFoundError:
        LOGGER.warning("Downloaded file missing for user %s", user_id)
        await safe_edit_status_message(
            status_message,
            get_text(language, "download_failed"),
            reply_markup=get_home_keyboard(language),
        )

    except subprocess.TimeoutExpired:
        LOGGER.warning("Download timed out for user %s", user_id)
        await safe_edit_status_message(
            status_message,
            get_text(language, "download_timeout"),
            reply_markup=get_home_keyboard(language),
        )

    except asyncio.CancelledError:
        if is_download_cancelled(user_id):
            await safe_edit_status_message(
                status_message,
                get_text(language, "cancelled"),
                reply_markup=get_home_keyboard(language),
            )
        else:
            raise

    except Exception:
        LOGGER.exception("Unexpected download error for user %s", user_id)
        await safe_edit_status_message(
            status_message,
            get_text(language, "download_failed"),
            reply_markup=get_home_keyboard(language),
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
                    and not is_download_cancelled(user_id)
                )

        if ACTIVE_DOWNLOAD_TASKS.get(user_id) is current_task:
            ACTIVE_DOWNLOAD_TASKS.pop(user_id, None)

        if ACTIVE_STATUS_MESSAGES.get(user_id) is status_message:
            ACTIVE_STATUS_MESSAGES.pop(user_id, None)

        if not download_finished:
            finish_download(user_id)

        log_performance(
            platform,
            "total",
            request_started_at,
        )

        if propagate_cancellation:
            raise asyncio.CancelledError
