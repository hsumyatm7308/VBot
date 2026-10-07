# Changelog

No release versions or release dates are defined in the repository. This file therefore uses an **Unreleased** section and records only changes corroborated by the current code/tests and recent Git history.

## Unreleased

- Added a per-user in-memory FIFO download queue with one active request and up to two waiting requests, plus queue-aware cancellation and orderly application shutdown.
- Added admin-only `/stats` counts for total successful users, active users today, successful downloads today, and currently active download users.
- Added subprocess environment isolation, log redaction, private-chat enforcement, TikTok short-link redirect checks, temporary disk preflight, SQLite owner-only file creation, and focused security tests.
- Added platform-specific format/fallback handling for YouTube, TikTok, X/Twitter, Instagram, and Pinterest, with size/duration classification and bilingual user feedback.
- Added temporary server-side performance diagnostics for downloader stages and Telegram uploads.

## History notes

Recent Git history records the module split (`49fa12d`, 2026-10-01), TikTok H.264 preference (`348a389`, 2026-10-01), security/admin stats (`b145128`, 2026-10-05), and per-user queue (`0b64c86`, 2026-10-05). Commit subjects are historical summaries; consult code and tests for exact current behavior.
