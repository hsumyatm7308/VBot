from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest

from config import LEGAL_CONTACT, TERMS_VERSION
from database import get_user_language, has_accepted_terms
from i18n import DEFAULT_LANGUAGE, get_text


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
