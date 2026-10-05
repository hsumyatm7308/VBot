# VBot

Telegram bot for downloading supported public videos with `yt-dlp`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install FFmpeg on macOS:

```bash
brew install ffmpeg
```

Create a local `.env` file:

```dotenv
BOT_TOKEN=your_telegram_bot_token
LEGAL_CONTACT=your_contact
ADMIN_USER_IDS=123456789,987654321
```

On macOS/Linux, restrict access to the environment file and database, and use
a restrictive umask before starting the bot:

```bash
umask 077
chmod 600 .env
# After the bot has created vdlp.db, ensure both files are private:
chmod 600 .env vdlp.db
```

The application also creates the SQLite database with owner-only permissions
on POSIX systems.

Run the bot:

```bash
python bot.py
```
