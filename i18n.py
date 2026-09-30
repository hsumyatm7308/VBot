DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = {"en", "my"}


TEXTS = {
    "en": {
        "language_prompt": "Choose language\nဘာသာစကားရွေးပါ",
        "home": "VDlp\n\nPaste a link\n\nYouTube • TikTok • X",
        "help": (
            "How to use\n\n"
            "1. Copy a supported link\n"
            "2. Send it to VDlp\n"
            "3. Wait for the download\n"
            "4. Save the returned video\n\n"
            "Supported\n"
            "YouTube\n"
            "TikTok\n"
            "X\n"
            "Instagram\n\n"
            "Daily limit: {daily_limit}"
        ),
        "status": (
            "Usage\n\n"
            "Used: {used} / {daily_limit}\n"
            "Remaining: {remaining}\n"
            "Terms: {terms_status}"
        ),
        "terms": (
            "Terms of Use\n\n"
            "1. Use VDlp only for your own content, content you have permission "
            "to download, or content that may legally be downloaded.\n\n"
            "2. Do not use VDlp for copyright infringement, paid or private "
            "content, login-restricted content, or to bypass access controls.\n\n"
            "3. Public availability does not mean that a video is "
            "copyright-free.\n\n"
            "4. You are responsible for following applicable laws and the "
            "Terms of Service of YouTube, TikTok, and X/Twitter.\n\n"
            "5. VDlp uses temporary files during processing and is designed to "
            "remove them when processing ends.\n\n"
            "6. Access may be restricted or removed for abuse, copyright "
            "infringement, or service misuse.\n\n"
            "Copyright / Abuse Reports:\n{contact}\n\n"
            "Terms version: {version}"
        ),
        "report": (
            "Copyright / Abuse Report\n\n"
            "Send the video URL and the reason for the report to:\n\n"
            "{contact}\n\n"
            "Do not include unnecessary personal information."
        ),
        "myid": "My ID\n\nID: {user_id}\nName: {full_name}{username_line}",
        "username_line": "\nUsername: @{username}",
        "terms_accepted": "Accepted",
        "terms_not_accepted": "Not accepted",
        "terms_updated": (
            "The Terms have changed. Review and accept the latest version."
        ),
        "terms_declined": (
            "Terms not accepted.\n\n"
            "VDlp downloads are unavailable until you accept the Terms."
        ),
        "terms_required": "Accept the Terms of Use before downloading.",
        "private_access": (
            "This bot is private.\n"
            "Access is not available for this account."
        ),
        "daily_limit_reached": (
            "Daily limit reached\n\n"
            "Limit: {daily_limit}\n"
            "Try again tomorrow."
        ),
        "active_download": "A download is already active.",
        "invalid_url": "Send a valid link.",
        "unsupported_url": "This link is not supported.",
        "tiktok_resolve_failed": "The TikTok link could not be resolved.",
        "checking": "Checking link…",
        "downloading": "Downloading…",
        "downloading_elapsed": "Downloading…\n{seconds}s",
        "preparing_media": "Preparing media…",
        "uploading": "Uploading…",
        "done": (
            "Done\n\n"
            "Usage: {used} / {daily_limit}\n"
            "Remaining: {remaining}"
        ),
        "file_too_large": (
            "File too large\n\n"
            "This video exceeds the current download size limit."
        ),
        "file_too_large_with_size": (
            "File too large\n\n"
            "Size: {size_mb:.1f} MB\n"
            "Limit: {max_mb} MB"
        ),
        "video_too_long": (
            "Video too long\n\n"
            "This video exceeds the current "
            "{max_duration_minutes:g}-minute limit."
        ),
        "download_failed": (
            "Download failed\n\n"
            "The source could not be reached. Try again later."
        ),
        "download_timeout": (
            "Download timed out\n\n"
            "Try again later."
        ),
        "cancelled": "Cancelled\n\nSend another link anytime.",
        "no_active_download": "No active download.",
        "button_help": "How to use",
        "button_status": "Usage",
        "button_language": "Language",
        "button_terms": "Terms",
        "button_report": "Report",
        "button_myid": "My ID",
        "button_back": "Back",
        "button_home": "Home",
        "button_cancel": "Cancel",
        "button_accept": "I Agree",
        "button_decline": "I Don't Agree",
    },
    "my": {
        "language_prompt": "Choose language\nဘာသာစကားရွေးပါ",
        "home": "VDlp\n\nLink တစ်ခု ပို့ပါ\n\nYouTube • TikTok • X",
        "help": (
            "အသုံးပြုနည်း\n\n"
            "1. Support လုပ်ထားသော link ကို copy လုပ်ပါ\n"
            "2. VDlp သို့ ပို့ပါ\n"
            "3. Download ပြီးသည်အထိ စောင့်ပါ\n"
            "4. ပြန်ပို့လာသော video ကို save လုပ်ပါ\n\n"
            "Support လုပ်ထားသည်များ\n"
            "YouTube\n"
            "TikTok\n"
            "X\n"
            "Instagram\n\n"
            "တစ်ရက်ကန့်သတ်ချက်: {daily_limit}"
        ),
        "status": (
            "အသုံးပြုမှု\n\n"
            "အသုံးပြုပြီး: {used} / {daily_limit}\n"
            "လက်ကျန်: {remaining}\n"
            "စည်းကမ်းချက်: {terms_status}"
        ),
        "terms": (
            "အသုံးပြုမှုစည်းကမ်းချက်များ\n\n"
            "1. ကိုယ်ပိုင် content၊ download လုပ်ခွင့်ရထားသော content၊ "
            "သို့မဟုတ် ဥပဒေအရ download လုပ်ခွင့်ရှိသော content များအတွက်သာ "
            "VDlp ကို အသုံးပြုရပါမည်။\n\n"
            "2. Copyright ချိုးဖောက်သော content၊ paid content၊ private "
            "content၊ login-restricted content သို့မဟုတ် access restrictions "
            "ကို ကျော်ဖြတ်ရန် VDlp ကို မသုံးရပါ။\n\n"
            "3. Video တစ်ခု public ဖြစ်နေခြင်းသည် copyright-free ဖြစ်သည်ဟု "
            "မဆိုလိုပါ။\n\n"
            "4. YouTube၊ TikTok၊ X/Twitter တို့၏ Terms of Service နှင့် "
            "သက်ဆိုင်ရာဥပဒေများကို လိုက်နာရန် အသုံးပြုသူတွင် တာဝန်ရှိပါသည်။\n\n"
            "5. VDlp သည် လုပ်ငန်းစဉ်အတွင်း temporary files အသုံးပြုပြီး "
            "ပြီးဆုံးချိန်တွင် ဖယ်ရှားရန် ဒီဇိုင်းလုပ်ထားပါသည်။\n\n"
            "6. Abuse၊ copyright infringement သို့မဟုတ် service misuse "
            "တွေ့ရှိပါက အသုံးပြုခွင့်ကို ကန့်သတ် သို့မဟုတ် ပိတ်ပင်နိုင်ပါသည်။\n\n"
            "Copyright / Abuse Reports:\n{contact}\n\n"
            "Terms version: {version}"
        ),
        "report": (
            "Copyright / Abuse Report\n\n"
            "Report လုပ်လိုသော video URL နှင့် အကြောင်းပြချက်ကို "
            "အောက်ပါ contact သို့ ပို့ပါ။\n\n"
            "{contact}\n\n"
            "မလိုအပ်သော ကိုယ်ရေးအချက်အလက်များ မပို့ပါနှင့်။"
        ),
        "myid": "မိမိ၏ ID\n\nID: {user_id}\nအမည်: {full_name}{username_line}",
        "username_line": "\nUsername: @{username}",
        "terms_accepted": "သဘောတူထားသည်",
        "terms_not_accepted": "သဘောမတူရသေးပါ",
        "terms_updated": (
            "စည်းကမ်းချက်များ ပြောင်းလဲထားပါသည်။ "
            "နောက်ဆုံး version ကိုဖတ်ပြီး သဘောတူပါ။"
        ),
        "terms_declined": (
            "စည်းကမ်းချက်များကို သဘောမတူပါ။\n\n"
            "သဘောမတူသေးသရွေ့ VDlp download ကို အသုံးမပြုနိုင်ပါ။"
        ),
        "terms_required": "Download မလုပ်မီ စည်းကမ်းချက်များကို သဘောတူပါ။",
        "private_access": (
            "ဤ bot သည် private ဖြစ်ပါသည်။\n"
            "ဤ account ဖြင့် အသုံးပြုခွင့်မရှိပါ။"
        ),
        "daily_limit_reached": (
            "ယနေ့ကန့်သတ်ချက် ပြည့်သွားပါပြီ\n\n"
            "ကန့်သတ်ချက်: {daily_limit}\n"
            "နောက်နေ့တွင် ပြန်စမ်းပါ။"
        ),
        "active_download": "Download တစ်ခု လုပ်ဆောင်နေပြီးဖြစ်သည်။",
        "invalid_url": "မှန်ကန်သော link တစ်ခု ပို့ပါ။",
        "unsupported_url": "ဤ link ကို support မလုပ်ပါ။",
        "tiktok_resolve_failed": "TikTok link ကို resolve မလုပ်နိုင်ပါ။",
        "checking": "Link စစ်နေသည်…",
        "downloading": "Download လုပ်နေသည်…",
        "downloading_elapsed": "Download လုပ်နေသည်…\n{seconds} စက္ကန့်",
        "preparing_media": "Media ပြင်ဆင်နေသည်…",
        "uploading": "Upload လုပ်နေသည်…",
        "done": (
            "ပြီးပါပြီ\n\n"
            "အသုံးပြုမှု: {used} / {daily_limit}\n"
            "လက်ကျန်: {remaining}"
        ),
        "file_too_large": (
            "File အရွယ်အစားကြီးလွန်းပါတယ်\n\n"
            "ဒီ video က လက်ရှိ download size limit ထက်ကျော်နေပါတယ်။"
        ),
        "file_too_large_with_size": (
            "File အရွယ်အစား ကြီးလွန်းပါသည်\n\n"
            "အရွယ်အစား: {size_mb:.1f} MB\n"
            "ကန့်သတ်ချက်: {max_mb} MB"
        ),
        "video_too_long": (
            "Video အချိန်ရှည်လွန်းပါတယ်\n\n"
            "ဒီ video က လက်ရှိ {max_duration_minutes:g} မိနစ် "
            "limit ထက် ကျော်နေပါတယ်။"
        ),
        "download_failed": (
            "Download မအောင်မြင်ပါ\n\n"
            "မူရင်း source ကို ဆက်သွယ်၍မရပါ။ နောက်မှပြန်စမ်းပါ။"
        ),
        "download_timeout": (
            "Download အချိန်ကျော်သွားပါပြီ\n\n"
            "နောက်မှပြန်စမ်းပါ။"
        ),
        "cancelled": "ရပ်လိုက်ပါပြီ\n\nနောက်ထပ် link တစ်ခု အချိန်မရွေးပို့နိုင်ပါသည်။",
        "no_active_download": "လုပ်ဆောင်နေသော download မရှိပါ။",
        "button_help": "အသုံးပြုနည်း",
        "button_status": "အသုံးပြုမှု",
        "button_language": "ဘာသာစကား",
        "button_terms": "စည်းကမ်းချက်",
        "button_report": "Report",
        "button_myid": "မိမိ၏ ID",
        "button_back": "နောက်သို့",
        "button_home": "ပင်မစာမျက်နှာ",
        "button_cancel": "ရပ်မည်",
        "button_accept": "သဘောတူသည်",
        "button_decline": "သဘောမတူပါ",
    },
}


def get_text(language: str | None, key: str, **kwargs) -> str:
    selected_language = (
        language
        if language in SUPPORTED_LANGUAGES
        else DEFAULT_LANGUAGE
    )
    template = TEXTS[selected_language].get(key, TEXTS[DEFAULT_LANGUAGE][key])
    return template.format(**kwargs)
