# Deployment Guide

## Evidence boundary

No deployment files are checked in: there is no systemd unit, Dockerfile, Ansible/Terraform config, CI workflow, or environment template. The repository does not prove the current production OS, user, path, service name, proxy, runtime PATH, or concurrency overrides.

The `vbot` account/systemd host described in operator context is **Unknown / needs verification**. Commands and unit below are an illustrative single-host Ubuntu setup, not a representation of an existing production configuration. Adapt paths and repository access before use. Never put secret values in Git or this document.

## Fresh Ubuntu single-host setup (example)

### 1. Install OS packages and create a service account

The app needs Python/venv, Git, certificates, and FFmpeg for merge/conversion paths. Install Deno separately only if the selected yt-dlp extraction path requires a supported JS runtime.

```bash
sudo apt update
sudo apt install -y ca-certificates git python3 python3-venv python3-pip sqlite3 ffmpeg
sudo adduser --system --group --home /opt/vbot vbot
```

Confirm the host's Python is 3.10 or newer. Install Deno from an approved source only if required; this repository does not install or verify it.

### 2. Put the source in an owned application directory

Use a deployment identity with access to the repository. The service should run as the dedicated, unprivileged application user (the account name below follows operator-reported context and must be verified):

```bash
sudo -u vbot git clone <REPOSITORY_URL> /opt/vbot/app
sudo chown -R vbot:vbot /opt/vbot/app
sudo -u vbot python3 -m venv /opt/vbot/app/.venv
sudo -u vbot /opt/vbot/app/.venv/bin/python -m pip install --upgrade pip
sudo -u vbot /opt/vbot/app/.venv/bin/python -m pip install -r /opt/vbot/app/requirements.txt
```

Keep writable application state in a private working directory. Since the current database path is relative, the bot creates `vdlp.db` under the service `WorkingDirectory`.

### 3. Configure secrets and optional settings

Create `/opt/vbot/app/.env` owned by the service account, mode `0600`; set `BOT_TOKEN`, and review `PUBLIC_ACCESS`, `ADMIN_USER_IDS`, and `LEGAL_CONTACT`. Configure `TWITTER_PROXY` or `INSTAGRAM_PROXY` only when required. Do not configure personal YouTube cookies as the default workaround for VPS bot checks.

```bash
sudo chown vbot:vbot /opt/vbot/app/.env
sudo chmod 600 /opt/vbot/app/.env
```

`config.py` loads `.env` relative to the process's current working directory; the service must use the app directory. `DB_PATH` is a code constant, not an environment variable.

### 4. Optional systemd unit template

No unit currently exists in the repository. If systemd is selected, a starting template is:

```ini
[Unit]
Description=VDlp Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=vbot
Group=vbot
WorkingDirectory=/opt/vbot/app
EnvironmentFile=/opt/vbot/app/.env
Environment="PATH=/opt/vbot/app/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
UMask=0077
ExecStart=/opt/vbot/app/.venv/bin/python /opt/vbot/app/bot.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Review hardening and writable paths on the actual host before production use. If the unit is named `vbot.service`, install it under `/etc/systemd/system/vbot.service`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vbot.service
sudo systemctl status vbot.service
```

The effective `PATH` must find `yt-dlp`, `gallery-dl`, `ffmpeg`, and any configured JS runtime. Python packages install command-line scripts into `.venv/bin`; FFmpeg and Deno are external.

### 5. Verify

- Confirm `systemctl status` is active and inspect `journalctl -u vbot.service` for startup errors.
- Confirm the process runs as the intended service account and that `vdlp.db` is created with owner-only permissions.
- Check `/start`, `/status`, and one permitted small public test link in a private Telegram chat.
- Confirm a successful upload increments `/status`; failed/cancelled/upload-failed attempts must not.
- Verify FFmpeg and `yt-dlp`/`gallery-dl` are available to the service environment, not merely an interactive login shell.
- Check free disk, memory, and the configured download concurrency before exposing public access.

## Rollback considerations

Stop the service before switching code revisions. Preserve `.env` and the SQLite database outside any source replacement; back them up securely before schema or dependency changes. Roll back code and pinned Python packages together when extraction behavior changes. Do not reset or overwrite the live database as a rollback shortcut. There is no repository migration/rollback automation; test on a copy first.

For start/stop, backups, monitoring, and incident procedures, see [OPERATIONS.md](OPERATIONS.md).
