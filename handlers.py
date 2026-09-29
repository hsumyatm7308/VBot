import asyncio
import subprocess
import tempfile
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import (
    ALLOWED_USERS,
    DAILY_LIMIT,
    LEGAL_CONTACT,
    MAX_MB,
    TERMS_VERSION,
)
from database import (
    get_daily_usage,
    get_remaining_downloads,
    has_accepted_terms,
    increment_daily_usage,
    save_terms_acceptance,
)
from downloaders import download_tiktok_photo, download_video
from platforms import (
    get_platform,
    is_http_url,
    is_tiktok_photo_url,
    resolve_tiktok_url,
)
from utils import (
    DownloadedFileNotFoundError,
    DownloadFailedError,
    get_file_size_mb,
    keep_user_updated,
)


ACTIVE_USERS = set()


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

    if not is_http_url(url):
        await update.message.reply_text("Valid URL တစ်ခု ပို့ပါ။")
        return

    platform = get_platform(url)

    if platform is None:
        await update.message.reply_text(
            "❌ ဒီ link ကို support မလုပ်သေးပါဘူး။"
        )
        return

    if platform == "tiktok":
        url = await resolve_tiktok_url(url)

        # Redirect ပြီးတဲ့ URL ကို ပြန်စစ်
        platform = get_platform(url)

        if platform is None:
            await update.message.reply_text(
                "❌ TikTok link ကို resolve မလုပ်နိုင်ပါ။"
            )
            return

    is_tiktok_photo = (
        platform == "tiktok"
        and is_tiktok_photo_url(url)
    )

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
            if is_tiktok_photo:
                await status_message.edit_text(
                    "📸 TikTok photo နဲ့ song ကို ပြင်ဆင်နေပါတယ်..."
                )

                video_path = await download_tiktok_photo(
                    url,
                    tmpdir,
                )
            else:
                video_path = await download_video(
                    platform,
                    url,
                    tmpdir,
                )

            size_mb = get_file_size_mb(video_path)

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

    except DownloadFailedError as error:
        await status_message.edit_text(
            "Download မအောင်မြင်ပါ။\n\n"
            f"Error:\n{error.last_error}"
        )

    except DownloadedFileNotFoundError:
        await status_message.edit_text("Downloaded file မတွေ့ပါ။")

    except subprocess.TimeoutExpired:
        await status_message.edit_text(
            "Download အချိန်ကြာလွန်းလို့ ရပ်လိုက်ပါတယ်။"
        )

    except Exception as error:
        await status_message.edit_text(f"Error ဖြစ်ပါတယ်: {error}")

    finally:
        ACTIVE_USERS.discard(user_id)

        stop_event.set()
        status_task.cancel()

        try:
            await status_task
        except asyncio.CancelledError:
            pass
