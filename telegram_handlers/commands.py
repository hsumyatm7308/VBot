from telegram import Update
from telegram.ext import ContextTypes

from config import DAILY_LIMIT, LEGAL_CONTACT, TERMS_VERSION
from database import (
    get_daily_usage,
    get_remaining_downloads,
    get_user_language,
    has_accepted_terms,
    save_terms_acceptance,
    set_user_language,
)
from i18n import DEFAULT_LANGUAGE, get_text
from telegram_handlers.ui import (
    get_back_keyboard,
    get_language,
    get_language_keyboard,
    get_main_menu_keyboard,
    get_terms_declined_keyboard,
    get_terms_keyboard,
    get_terms_text,
    require_language,
    safe_edit_message,
    send_language_prompt,
    send_terms,
    show_home_query,
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
    selected_language = "en" if query.data == "lang_en" else "my"
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
