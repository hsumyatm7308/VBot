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
    handle_terms_callback,
    handle_url,
    myid,
    report_command,
    start,
    status_command,
    terms_command,
)


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN မရှိပါ။ .env ထဲမှာ BOT_TOKEN ထည့်ပါ။"
        )

    init_legal_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("terms", terms_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("status", status_command))

    app.add_handler(
        CallbackQueryHandler(
            handle_terms_callback,
            pattern=r"^terms_(accept|decline):",
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_url,
        )
    )

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
