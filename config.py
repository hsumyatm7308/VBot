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

ALLOWED_USERS = {
    5531100901,
    1652119664,
    1739242512,
    444444444,
    555555555,
}
