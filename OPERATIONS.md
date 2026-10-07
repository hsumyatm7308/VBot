# Operations Runbook

This is a runbook for the illustrative `vbot.service` unit in [DEPLOYMENT.md](DEPLOYMENT.md). The actual production service name/host is **Unknown / needs verification**.

## Service controls

```bash
sudo systemctl start vbot.service
sudo systemctl stop vbot.service
sudo systemctl restart vbot.service
sudo systemctl status vbot.service
sudo journalctl -u vbot.service -n 100 --no-pager
sudo journalctl -u vbot.service -f
```

The bot uses Telegram long polling. There is no HTTP health endpoint. Verify health through service state/logs and a private Telegram `/status` request. `/stats` is available only to IDs configured in `ADMIN_USER_IDS`.

## Safe code deployment

1. Confirm branch/revision and cleanly identify local changes; do not overwrite `.env`, `vdlp.db`, or user data.
2. Run the test and compile commands from README in the deployment checkout.
3. Back up the database and `.env` using the secure procedures below.
4. Stop the single polling instance; ensure another process with the same bot token is not running.
5. Deploy the reviewed revision, install the exact `requirements.txt`, then verify executable PATH includes venv and system tools.
6. Start/restart the service and inspect journal logs.
7. Verify `/start`, `/status`, a small permitted media link, upload, daily count, and cancellation.
8. If unhealthy, stop and roll back code/dependencies; restore database only if a verified data issue requires it.

There is no automated deploy or rollback script checked in. Keep a single poller per token unless webhook/multi-instance coordination is deliberately designed.

## Database backup

The database is sensitive: it contains Telegram numeric identifiers, language choices, legal acceptance timestamps, and usage history. Store backups in a restricted location accessible only to authorized operators. Do not put backups in the repository or public artifacts.

When the service is stopped, an example backup using the SQLite CLI is:

```bash
sudo sqlite3 /opt/vbot/app/vdlp.db ".backup '/var/backups/vdlp.db'"
sudo chmod 600 /var/backups/vdlp.db
```

Confirm ownership and backup retention/encryption according to host policy. Test restore procedures against a separate copy. No automated backup or retention job is implemented.

## Resource and temporary-file checks

```bash
df -h / /tmp /opt
free -h
swapon --show
ps -o user,pid,%cpu,%mem,etime,cmd -C python
```

Each job uses a Python `TemporaryDirectory`; normal completion and handled failures clean it automatically. Before deleting leftovers, confirm no bot process is using them. Investigate disk-full conditions rather than broadly removing temp directories. The preflight requires free space equal to twice `MAX_MB` (currently 98 MiB) in the temp filesystem; actual merges may need additional headroom.

## Dependency updates

1. Review changelogs/security advisories for pinned packages.
2. Change pins in a dedicated branch; do not silently switch yt-dlp to nightly.
3. Run the full test suite, compile checks, and selector/fallback tests.
4. Smoke-test each supported platform in a non-production environment with public, permitted media.
5. Confirm external FFmpeg and JS runtime availability under the service user.
6. Deploy one controlled revision and monitor logs/errors before broader rollout.

`httpx` is directly imported but not separately pinned; curl-cffi is not currently declared. Resolve those dependency questions before relying on them.

## Troubleshooting flow

1. Check service state and recent journal entries.
2. Confirm only one poller uses the token, then validate `.env` and service-user permissions without printing secret values.
3. Confirm service `PATH`, Python virtual environment, `yt-dlp`, `gallery-dl`, FFmpeg, and optional Deno availability.
4. Check free disk, memory/swap, active subprocesses, network reachability, and proxy configuration.
5. Use localized bot error class and sanitized server logs to identify the platform branch; avoid logging full signed URLs or credentials.
6. Reproduce with a small public link and current stable pinned dependencies. Do not disable URL validation, subprocess isolation, access controls, or size/duration limits.

## Common incidents

### Telegram polling conflict

- Symptom: Telegram reports another `getUpdates` request or polling conflict.
- Check for duplicate services/processes/containers using the same `BOT_TOKEN`.
- Keep one long-polling instance; stop the stale instance and restart the intended service.
- Do not rotate/reveal the token in logs. If token exposure is suspected, revoke it through the official bot management channel and update the secret store.

### `yt-dlp` / `gallery-dl` / `ffmpeg` executable not found

- Check executable resolution as the service user and inspect `Environment=PATH` in the unit.
- Python-installed scripts are in `.venv/bin`; OS FFmpeg is usually in `/usr/bin`.
- Do not rely on shell profile PATH settings; `create_subprocess_exec` receives a minimal environment derived from the service environment.

### TikTok challenge or impersonation errors

- Check pinned yt-dlp version and the exact error; ordinary availability failures can be upstream/network-side.
- curl-cffi and an explicit impersonation option are not configured in this repository. Verify the production environment before claiming that support exists.
- Do not install browser cookies, weaken URL/network controls, or change all platform formats as a workaround. Test any dependency/option change separately.

### YouTube `LOGIN_REQUIRED` / “Sign in to confirm you're not a bot”

- Compare the same public URL from the service egress and a normal network; this may indicate IP/reputation differences rather than a code regression.
- Confirm stable yt-dlp/EJS versions and required JS runtime are available to the service.
- Do not treat personal account cookies as the default production solution. Do not bypass access controls; verify whether content is public and evaluate an approved egress strategy.
- Current production status is **Unknown / needs verification**.

### Disk-space problems

- Check `df`, `du` on the app/temp filesystem, and active bot jobs.
- `ensure_temporary_disk_space()` rejects work below twice the configured maximum-file size.
- Let active `TemporaryDirectory` scopes complete; only remove confirmed stale directories after stopping the relevant process and identifying exact paths.

### Stuck download or cancellation

- `/cancel` clears the user's waiting jobs and sends TERM to the active process group, escalating to KILL after the grace period.
- Check whether the job is still downloading, waiting on the global semaphore, or uploading. Telegram upload is not an OS subprocess.
- Inspect process tree and service logs. Restart only if necessary; process restart discards all in-memory queues/rate-limit state.
- Application shutdown is wired to cancel queue workers and their subprocesses; verify the unit actually stops the process cleanly.
