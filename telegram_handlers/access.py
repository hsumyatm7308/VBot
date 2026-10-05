from telegram import Chat, Update
from telegram.ext import ApplicationHandlerStop

from i18n import get_text
from telegram_handlers.ui import get_language


async def enforce_private_chat(update: Update, context):
    """Stop group/channel updates before any account or media handler runs."""
    chat = update.effective_chat
    if chat is None or chat.type == Chat.PRIVATE:
        return

    user_id = update.effective_user.id if update.effective_user else None
    language = get_language(user_id) if user_id is not None else None
    response = get_text(language, "private_chat_only")

    if update.callback_query is not None:
        await update.callback_query.answer(response, show_alert=True)
    elif update.effective_message is not None:
        await update.effective_message.reply_text(response)

    raise ApplicationHandlerStop
