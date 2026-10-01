import asyncio

from downloaders import cancel_download
from i18n import get_text
from telegram_handlers.ui import (
    get_home_keyboard,
    get_language,
    safe_edit_message,
    safe_edit_status_message,
)


ACTIVE_DOWNLOAD_TASKS: dict[int, asyncio.Task] = {}
ACTIVE_STATUS_MESSAGES = {}


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


async def cancel_command(update, context):
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


async def handle_cancel_callback(update, context):
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
