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
```

Run the bot:

```bash
python bot.py
```
