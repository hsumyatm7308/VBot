import os

from dotenv import load_dotenv


load_dotenv()


BOT_TOKEN = os.getenv("BOT_TOKEN")
TWITTER_PROXY = os.getenv("TWITTER_PROXY", "").strip()
INSTAGRAM_PROXY = os.getenv(
    "INSTAGRAM_PROXY",
    "",
).strip()


DAILY_LIMIT = 30
MAX_DURATION_SECONDS = 900
MAX_MB = 49

DEFAULT_MAX_HEIGHT = 1080
HIGH_MAX_HEIGHT = 1440

DB_PATH = "vdlp.db"
TERMS_VERSION = "2026-09-29-v1"

LEGAL_CONTACT = os.getenv(
    "LEGAL_CONTACT",
    "Not configured",
)

PUBLIC_ACCESS = os.getenv(
    "PUBLIC_ACCESS",
    "false",
).lower() == "true"


ALLOWED_USERS = {
    5531100901,
}
