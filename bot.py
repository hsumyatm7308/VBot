import os
import glob
import tempfile
import subprocess
import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TWITTER_PROXY = os.getenv("TWITTER_PROXY", "").strip()

MAX_MB = 49
DAILY_LIMIT = 20

DB_PATH = "vdlp.db"
ACTIVE_USERS = set()


TERMS_VERSION = "2026-09-29-v1"

LEGAL_CONTACT = os.getenv(
    "LEGAL_CONTACT",
    "Not configured"
)


ALLOWED_USERS = {
    5531100901,
    1652119664,
    1739242512,
    444444444,
    555555555,
}

def init_legal_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS legal_acceptances (
                user_id INTEGER PRIMARY KEY,
                terms_version TEXT NOT NULL,
                accepted_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_usage (
                user_id INTEGER NOT NULL,
                usage_date TEXT NOT NULL,
                download_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, usage_date)
            )
            """
        )

        conn.commit()


def has_accepted_terms(user_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT terms_version
            FROM legal_acceptances
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

    return row is not None and row[0] == TERMS_VERSION


def save_terms_acceptance(user_id: int):
    accepted_at = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO legal_acceptances (
                user_id,
                terms_version,
                accepted_at
            )
            VALUES (?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                terms_version = excluded.terms_version,
                accepted_at = excluded.accepted_at
            """,
            (
                user_id,
                TERMS_VERSION,
                accepted_at,
            ),
        )
        conn.commit()


def get_today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def get_daily_usage(user_id: int) -> int:
    today = get_today_utc()

    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT download_count
            FROM daily_usage
            WHERE user_id = ? AND usage_date = ?
            """,
            (user_id, today),
        ).fetchone()

    if row is None:
        return 0

    return row[0]


def get_remaining_downloads(user_id: int) -> int:
    used = get_daily_usage(user_id)
    return max(0, DAILY_LIMIT - used)


def increment_daily_usage(user_id: int):
    today = get_today_utc()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO daily_usage (
                user_id,
                usage_date,
                download_count
            )
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, usage_date)
            DO UPDATE SET
                download_count = download_count + 1
            """,
            (user_id, today),
        )

        conn.commit()


def get_terms_text():
    return (
        "📄 VDlp Bot — Terms of Use\n\n"

        "VDlp Bot ကို အသုံးပြုခြင်းဖြင့် အောက်ပါစည်းကမ်းများကို "
        "သဘောတူကြောင်း အတည်ပြုရပါမယ်။\n\n"

        "1. ကိုယ်ပိုင် content၊ download လုပ်ခွင့်ရထားသော content၊ "
        "သို့မဟုတ် ဥပဒေအရ download လုပ်ခွင့်ရှိသော content များအတွက်သာ "
        "အသုံးပြုရပါမယ်။\n\n"

        "2. Copyright ချိုးဖောက်သော content၊ paid content၊ private content၊ "
        "login-restricted content သို့မဟုတ် access restrictions ကို "
        "ကျော်ဖြတ်ရန် VDlp Bot ကို မသုံးရပါ။\n\n"

        "3. Video တစ်ခု public ဖြစ်နေခြင်းသည် copyright-free "
        "ဖြစ်သည်ဟု မဆိုလိုပါ။\n\n"

        "4. YouTube, TikTok, X/Twitter နှင့် သက်ဆိုင်ရာ platform များ၏ "
        "Terms of Service နှင့် သက်ဆိုင်ရာဥပဒေများကို လိုက်နာရန် "
        "အသုံးပြုသူတွင် တာဝန်ရှိပါသည်။\n\n"

        "5. VDlp Bot သည် download process အတွက် temporary files "
        "အသုံးပြုပြီး process ပြီးဆုံးသည့်အခါ ဖယ်ရှားရန် ဒီဇိုင်းလုပ်ထားပါသည်။\n\n"

        "6. Abuse၊ copyright infringement သို့မဟုတ် service misuse "
        "တွေ့ရှိပါက အသုံးပြုခွင့်ကို ကန့်သတ်/ပိတ်ပင်နိုင်ပါသည်။\n\n"

        f"📮 Copyright / Abuse Reports:\n{LEGAL_CONTACT}\n\n"

        f"Terms version: {TERMS_VERSION}"
    )


async def send_terms(message):
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ I Agree",
                    callback_data=f"terms_accept:{TERMS_VERSION}",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ I Don't Agree",
                    callback_data=f"terms_decline:{TERMS_VERSION}",
                )
            ],
        ]
    )

    await message.reply_text(
        get_terms_text(),
        reply_markup=keyboard,
    )


async def handle_terms_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if data.startswith("terms_accept:"):
        version = data.split(":", 1)[1]

        if version != TERMS_VERSION:
            await query.edit_message_text(
                "Terms ကို update လုပ်ထားပါတယ်။ "
                "/terms ကိုနှိပ်ပြီး Terms အသစ်ကို ပြန်ဖတ်ပေးပါ။"
            )
            return

        save_terms_acceptance(user_id)

        await query.edit_message_text(
            "✅ Terms accepted.\n\n"
            "YouTube, TikTok သို့မဟုတ် X/Twitter "
            "public video link ပို့နိုင်ပါပြီ။"
        )
        return

    if data.startswith("terms_decline:"):
        await query.edit_message_text(
            "Terms ကို သဘောမတူသောကြောင့် "
            "VDlp download feature ကို အသုံးပြု၍မရပါ။\n\n"
            "နောက်မှ ပြန်သဘောတူချင်ရင် /terms ကိုသုံးပါ။"
        )

async def terms_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await send_terms(update.message)


async def report_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "📮 Copyright / Abuse Report\n\n"
        "Report လုပ်လိုသော video URL နှင့် "
        "report reason ကို အောက်ပါ contact သို့ ပို့ပါ။\n\n"
        f"{LEGAL_CONTACT}\n\n"
        "Private information သို့မဟုတ် unnecessary personal data "
        "မပို့ပါနှင့်။"
    )


async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id

    used = get_daily_usage(user_id)
    remaining = get_remaining_downloads(user_id)

    terms_status = (
        "✅ Accepted"
        if has_accepted_terms(user_id)
        else "❌ Not accepted"
    )

    await update.message.reply_text(
        "📊 VDlp Status\n\n"
        f"Today's downloads: {used}/{DAILY_LIMIT}\n"
        f"Remaining: {remaining}\n"
        f"Terms: {terms_status}\n\n"
        "Daily usage resets automatically each day."
    )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id

    if has_accepted_terms(user_id):
        await update.message.reply_text(
            "👋 Welcome to VDlp Bot!\n\n"
            "YouTube, TikTok, X/Twitter video link ပို့ပါ။\n"
            "အသုံးပြုခွင့်ရှိတဲ့ content များအတွက်သာ အသုံးပြုပါ။\n\n"
            "📄 /terms — Terms of Use\n"
            "📮 /report — Copyright / Abuse Report\n"
            "🆔 /myid — Your Telegram ID"
        )
    else:
        await update.message.reply_text(
            "👋 Welcome to VDlp Bot!\n\n"
            "Bot ကို စတင်အသုံးပြုရန် Terms of Use ကို "
            "ဖတ်ပြီး သဘောတူရန်လိုပါတယ်။"
        )

        await send_terms(update.message)



async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    text = f"Your Telegram user ID is:\n{user.id}\n\nName: {user.full_name}"

    if user.username:
        text += f"\nUsername: @{user.username}"

    await update.message.reply_text(text)


def get_platform(url: str):
    try:
        parsed = urlparse(url)
    except Exception:
        return None

    # Only normal web URLs
    if parsed.scheme not in ("http", "https"):
        return None

    # Reject URLs containing username/password
    if parsed.username or parsed.password:
        return None

    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path or "/"

    # -------------------------
    # YouTube
    # -------------------------
    youtube_hosts = {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
    }

    if host in youtube_hosts:
        if host == "youtu.be":
            if path.strip("/"):
                return "youtube"
            return None

        valid_youtube_paths = (
            "/watch",
            "/shorts/",
            "/live/",
        )

        if path.startswith(valid_youtube_paths):
            return "youtube"

        return None

    # -------------------------
    # TikTok
    # -------------------------
    tiktok_hosts = {
        "tiktok.com",
        "www.tiktok.com",
        "m.tiktok.com",
        "vm.tiktok.com",
        "vt.tiktok.com",
    }

    if host in tiktok_hosts:
        # TikTok short links
        if host in {"vm.tiktok.com", "vt.tiktok.com"}:
            if path.strip("/"):
                return "tiktok"
            return None

        # Normal TikTok video links
        if "/video/" in path:
            return "tiktok"

        return None

    # -------------------------
    # X / Twitter
    # -------------------------
    twitter_hosts = {
        "x.com",
        "www.x.com",
        "mobile.x.com",
        "twitter.com",
        "www.twitter.com",
        "mobile.twitter.com",
    }

    if host in twitter_hosts:
        if "/status/" in path:
            return "twitter"

        return None

    return None


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


async def keep_user_updated(status_message, stop_event):
    seconds = 0

    while not stop_event.is_set():
        await asyncio.sleep(15)
        seconds += 15

        if seconds == 15:
            text = "Downloading... 15 seconds ကြာနေပါပြီ။ ခဏစောင့်ပေးပါ။"
        elif seconds == 30:
            text = "Still downloading... video file ကြီးနိုင်ပါတယ်။"
        elif seconds == 60:
            text = "Still working... မပြီးသေးပါ။ ရနိုင်သေးရင် ဆက်လုပ်နေပါတယ်။"
        else:
            text = f"Still downloading... {seconds} seconds ကြာနေပါပြီ။"

        try:
            await status_message.edit_text(text)
        except Exception:
            pass


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in ALLOWED_USERS:
        await update.message.reply_text(
            "This bot is currently private. You are not allowed to use it."
        )
        return

    print("User ID:", update.effective_user.id)
    print("Username:", update.effective_user.username)

    if not has_accepted_terms(user_id):
        await update.message.reply_text(
            "⚠️ Download မလုပ်ခင် Terms of Use ကို သဘောတူရန်လိုပါတယ်."
        )

        await send_terms(update.message)
        return


    used_today = get_daily_usage(user_id)

    if used_today >= DAILY_LIMIT:
        await update.message.reply_text(
            "🚫 ဒီနေ့ download limit ပြည့်သွားပါပြီ။\n\n"
            f"Daily limit: {DAILY_LIMIT}\n"
            "နောက်နေ့မှ ပြန်အသုံးပြုနိုင်ပါမယ်။"
        )
        return


    if user_id in ACTIVE_USERS:
        await update.message.reply_text(
            "⏳ လက်ရှိ download တစ်ခု လုပ်နေပါတယ်။ "
            "အဲ့ဒီ download ပြီးမှ နောက်တစ်ခု ပို့ပေးပါ။"
        )
        return

    url = update.message.text.strip()



    if not url.startswith(("http://", "https://")):
        await update.message.reply_text("Valid URL တစ်ခု ပို့ပါ။")
        return

    platform = get_platform(url)

    if platform is None:
        await update.message.reply_text(
            "❌ ဒီ link ကို support မလုပ်သေးပါဘူး။\n\n"
            "လက်ရှိ support လုပ်ထားတာတွေက:\n"
            "• YouTube\n"
            "• TikTok\n"
            "• X / Twitter"
        )
        return

    parsed = urlparse(url)
    path = parsed.path or ""

    if platform == "tiktok" and "/photo/" in path:
        await update.message.reply_text(
            "📸 TikTok Photo/Slideshow posts ကို လက်ရှိ မထောက်ပံ့သေးပါဘူး။\n"
            "TikTok video links ကိုသာ ပို့ပေးပါ။"
        )
        return


    ACTIVE_USERS.add(user_id)

    status_message = await update.message.reply_text(
        "Checking video... ခဏစောင့်ပါ။"
    )
    stop_event = asyncio.Event()
    status_task = asyncio.create_task(
        keep_user_updated(status_message, stop_event)
    )

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
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

                last_error = result.stderr[-1000:]

            if result is None or result.returncode != 0:
                await status_message.edit_text(
                    "Download မအောင်မြင်ပါ။\n\n"
                    f"Error:\n{last_error}"
                )
                return

            files = glob.glob(f"{tmpdir}/*")

            if not files:
                await status_message.edit_text("Downloaded file မတွေ့ပါ။")
                return

            video_path = max(files, key=os.path.getsize)
            size_mb = os.path.getsize(video_path) / (1024 * 1024)

            if size_mb > MAX_MB:
                await status_message.edit_text(
                    f"File size က {size_mb:.1f}MB ဖြစ်နေတယ်။ "
                    "Telegram bot က 50MB အထိပဲ ပို့နိုင်လို့ မပို့နိုင်ပါ။"
                )
                return

            await status_message.edit_text("Upload လုပ်နေပါတယ်...")

            with open(video_path, "rb") as video:
                await update.message.reply_video(
                    video=video,
                    caption=Path(video_path).name,
                    supports_streaming=True,
                )

            increment_daily_usage(user_id)

            used = get_daily_usage(user_id)
            remaining = get_remaining_downloads(user_id)

            await status_message.edit_text(
                "ပြီးပါပြီ ✅\n\n"
                f"Today's usage: {used}/{DAILY_LIMIT}\n"
                f"Remaining: {remaining}"
            )

    except subprocess.TimeoutExpired:
        await status_message.edit_text(
            "Download အချိန်ကြာလွန်းလို့ ရပ်လိုက်ပါတယ်။"
        )

    except Exception as e:
        await status_message.edit_text(f"Error ဖြစ်ပါတယ်: {e}")

    finally:
        ACTIVE_USERS.discard(user_id)

        stop_event.set()
        status_task.cancel()

        try:
            await status_task
        except asyncio.CancelledError:
            pass


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
