import sqlite3
from datetime import datetime, timezone

from config import DAILY_LIMIT, DB_PATH, TERMS_VERSION


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
