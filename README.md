# VDlp

VDlp is a Python Telegram bot that accepts links to supported public media and returns downloaded media in Telegram. The current platform and product behavior is defined in [SPEC.md](SPEC.md); module responsibilities and request flow are in [ARCHITECTURE.md](ARCHITECTURE.md).

## Quick start

Requirements: Python 3.10 or newer, a Telegram bot token, and FFmpeg for media merging and TikTok photo-post conversion. YouTube may also need a supported JavaScript runtime for yt-dlp challenge solving; see [TECHNOLOGY.md](TECHNOLOGY.md). The repository does not automate installation of FFmpeg or Deno.

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Install FFmpeg separately (for example, `brew install ffmpeg` on macOS or `sudo apt install ffmpeg` on Ubuntu).

Create `.env` in the repository working directory:

```dotenv
BOT_TOKEN=replace-with-your-telegram-bot-token
ADMIN_USER_IDS=
LEGAL_CONTACT=replace-with-a-report-contact
PUBLIC_ACCESS=false
# Optional, only if needed:
# TWITTER_PROXY=http://proxy.example:port
# INSTAGRAM_PROXY=http://proxy.example:port
```

Keep `.env` private. On POSIX systems, use a restrictive umask and permissions:

```bash
umask 077
chmod 600 .env
```

By default, only user IDs in the source-defined `ALLOWED_USERS` set can use downloads. For a public bot, `PUBLIC_ACCESS=true` enables public access; make that an intentional deployment choice. Set `ADMIN_USER_IDS` separately to grant `/stats` access. `LEGAL_CONTACT` should identify a monitored reporting channel.

### Configuration reference

| Setting | Default / source | Purpose |
|---|---|---|
| `BOT_TOKEN` | Required; `.env`/environment | Telegram bot credential. |
| `PUBLIC_ACCESS` | `false` | When `true`, bypasses the source-defined user allowlist. |
| `ADMIN_USER_IDS` | Empty set | Comma-separated Telegram IDs allowed to use `/stats`; separate from download access. |
| `LEGAL_CONTACT` | `Not configured` | Contact displayed for copyright/abuse reports. |
| `TWITTER_PROXY`, `INSTAGRAM_PROXY` | Empty | Optional explicit proxy arguments for those platform download paths. |
| `MAX_CONCURRENT_UPDATES` | `8` | PTB update concurrency. |
| `MAX_CONCURRENT_DOWNLOADS` | `2` | Global media-acquisition concurrency. |
| `DOWNLOAD_ATTEMPT_COOLDOWN_SECONDS` | `15` | Short per-user request cooldown. |
| `DOWNLOAD_ATTEMPT_WINDOW_SECONDS` | `600` | Rolling request-attempt window. |
| `DOWNLOAD_ATTEMPT_MAX_PER_WINDOW` | `5` | Maximum accepted attempts per rolling window. |
| `DAILY_LIMIT`, `MAX_DURATION_SECONDS`, `MAX_MB` | `30`, `900`, `49` | Source constants for successful daily uploads, duration seconds, and file size. |
| `DB_PATH`, `TERMS_VERSION` | `vdlp.db`, version string in `config.py` | Database path is relative to working directory; a terms-version change requires users to accept again. |
| `ALLOWED_USERS` | Source-defined set in `config.py` | Restricted-mode download access; no environment variable currently overrides this set. |

Positive integer environment settings fall back to their defaults when invalid or non-positive. See [TECHNOLOGY.md](TECHNOLOGY.md) for external runtime dependencies and [SECURITY.md](SECURITY.md) for secret handling.

Run locally from the directory containing `.env`:

```bash
python bot.py
```

The SQLite database is created as `vdlp.db` in the current working directory. It is ignored by Git and created owner-only on POSIX systems.

## Current capabilities

- YouTube, TikTok, X/Twitter, Instagram, and Pinterest video Pins.
- TikTok single-photo posts with audio are converted into MP4; TikTok photo slideshows are not supported.
- Instagram `/p/` tries video first, then a single-photo fallback; Instagram Stories and carousels are unsupported.
- A per-user FIFO queue allows one active job and up to two waiting jobs. A global semaphore limits simultaneous media acquisition.
- `/cancel` cancels the user's active job and clears that user's waiting queue.
- Daily successful-upload quota: 30 per UTC day. A quota count is recorded only after Telegram upload succeeds.
- English and Myanmar messages.

See [SPEC.md](SPEC.md) for complete behavior and limits.

## Tests

The project uses the Python standard-library `unittest` runner:

```bash
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m py_compile bot.py config.py database.py platforms.py utils.py handlers.py downloaders.py downloader_core/*.py telegram_handlers/*.py tests/*.py
git diff --check
```

## Documentation map

For a first handoff, read: [SPEC](SPEC.md) → [PROJECT_CONTEXT](PROJECT_CONTEXT.md) → [TECHNOLOGY](TECHNOLOGY.md) → [ARCHITECTURE](ARCHITECTURE.md) → [DEPLOYMENT](DEPLOYMENT.md) → [OPERATIONS](OPERATIONS.md) → [SECURITY](SECURITY.md) → [DECISIONS](DECISIONS.md) → [ROADMAP](ROADMAP.md) → [CHANGELOG](CHANGELOG.md). Coding agents must follow [AGENTS.md](AGENTS.md); [CLAUDE.md](CLAUDE.md) points Claude to the same canonical instructions.

## Status and unknowns

The repository contains no CI workflow, deployment manifest, systemd unit, Deno installer, or production configuration. Current production host details and the operator-reported VPS-specific YouTube issue therefore need verification; see [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) and [DEPLOYMENT.md](DEPLOYMENT.md).
