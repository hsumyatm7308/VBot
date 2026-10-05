import os
import warnings

from dotenv import load_dotenv


load_dotenv()


def positive_int_from_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError:
        warnings.warn(
            f"Ignoring invalid {name}; using {default}.",
            RuntimeWarning,
            stacklevel=2,
        )
        return default
    return value if value > 0 else default


def parse_admin_user_ids(raw_value: str | None) -> set[int]:
    if not raw_value:
        return set()

    admin_ids = set()
    invalid_values = []

    for value in raw_value.split(","):
        candidate = value.strip()
        if not candidate:
            continue

        try:
            user_id = int(candidate)
        except ValueError:
            invalid_values.append(candidate)
            continue

        if user_id <= 0:
            invalid_values.append(candidate)
            continue

        admin_ids.add(user_id)

    if invalid_values:
        warnings.warn(
            "Ignoring invalid ADMIN_USER_IDS values: "
            + ", ".join(invalid_values),
            RuntimeWarning,
            stacklevel=2,
        )

    return admin_ids


BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_IDS = parse_admin_user_ids(
    os.getenv("ADMIN_USER_IDS", "")
)
TWITTER_PROXY = os.getenv("TWITTER_PROXY", "").strip()
INSTAGRAM_PROXY = os.getenv(
    "INSTAGRAM_PROXY",
    "",
).strip()


DAILY_LIMIT = 30
MAX_DURATION_SECONDS = 900
MAX_MB = 49
MAX_CONCURRENT_UPDATES = positive_int_from_env(
    "MAX_CONCURRENT_UPDATES",
    8,
)
MAX_CONCURRENT_DOWNLOADS = positive_int_from_env(
    "MAX_CONCURRENT_DOWNLOADS",
    2,
)
DOWNLOAD_ATTEMPT_COOLDOWN_SECONDS = positive_int_from_env(
    "DOWNLOAD_ATTEMPT_COOLDOWN_SECONDS",
    15,
)
DOWNLOAD_ATTEMPT_WINDOW_SECONDS = positive_int_from_env(
    "DOWNLOAD_ATTEMPT_WINDOW_SECONDS",
    600,
)
DOWNLOAD_ATTEMPT_MAX_PER_WINDOW = positive_int_from_env(
    "DOWNLOAD_ATTEMPT_MAX_PER_WINDOW",
    5,
)

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
