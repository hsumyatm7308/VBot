from telegram import BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN
from database import init_legal_db
from handlers import (
    cancel_command,
    handle_cancel_callback,
    handle_language_callback,
    handle_menu_callback,
    handle_terms_callback,
    handle_url,
    help_command,
    language_command,
    myid,
    report_command,
    start,
    status_command,
    terms_command,
)


async def post_init(application):
    commands = [
        BotCommand("start", "Open VDlp Bot"),
        BotCommand("help", "How to use the bot"),
        BotCommand("status", "Check today's usage"),
        BotCommand("language", "Change language"),
        BotCommand("terms", "Terms of Use"),
        BotCommand("report", "Copyright / Abuse Report"),
        BotCommand("myid", "Show your Telegram ID"),
        BotCommand("cancel", "Cancel active download"),
    ]

    await application.bot.set_my_commands(commands)


async def error_handler(update, context):
    print(
        "Unhandled Telegram error:",
        context.error,
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN မရှိပါ။ .env ထဲမှာ BOT_TOKEN ထည့်ပါ။"
        )

    init_legal_db()

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("terms", terms_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("cancel", cancel_command))

    app.add_handler(
        CallbackQueryHandler(
            handle_terms_callback,
            pattern=r"^terms_(accept|decline):",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            handle_menu_callback,
            pattern=r"^menu_",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            handle_language_callback,
            pattern=r"^lang_(en|my)$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            handle_cancel_callback,
            pattern=r"^cancel_download$",
        )
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_url,
        )
    )
    app.add_error_handler(error_handler)



    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
