import os

from dotenv import load_dotenv


load_dotenv()


BOT_TOKEN = os.getenv("BOT_TOKEN")
TWITTER_PROXY = os.getenv("TWITTER_PROXY", "").strip()

MAX_MB = 49
DAILY_LIMIT = 20

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
