# Security Model and Invariants

This document records what the checked-in code does and what remains unverified. It is not a claim that the live host has been audited.

## Implemented protections

- **Secrets:** `.env` is gitignored. `BOT_TOKEN` is required at startup; proxy values are read from environment. README recommends owner-only `.env` permissions. Never commit or print secret values.
- **Database permissions:** POSIX database initialization temporarily uses umask `077` and attempts to chmod the SQLite database to `0600`. Filesystem support can limit chmod behavior.
- **Private chat:** a PTB type handler blocks group/channel updates before business handlers.
- **Access control:** access defaults to a source-defined `ALLOWED_USERS` set unless `PUBLIC_ACCESS=true`. `/stats` has a separate `ADMIN_USER_IDS` allowlist; an empty list denies everyone.
- **URL validation:** only known platform host/path patterns are accepted. Credentials in URLs are rejected by platform parsing. TikTok short links are manually redirected with a redirect cap, host/path checks, DNS resolution, and public-IP validation before each request.
- **Subprocesses:** downloader and FFmpeg processes use `asyncio.create_subprocess_exec` with argument lists (no shell), a minimal environment allowlist, captured streams, timeouts, and a new process session for process-group termination.
- **Resource controls:** duration and file-size checks, disk-space preflight, bounded user queues, media semaphore, Telegram update cap, and in-memory attempt limiter constrain work.
- **Logging:** `sanitize_log_text()` removes URL query strings, URL credentials, authorization values, and common secret assignments. Selected downloader errors are sanitized and user-facing failures use controlled localized messages.
- **Temporary media:** files are created under `TemporaryDirectory` and normally removed on scope exit, including handled exceptions/cancellation.
- **Legal access:** Terms prohibit copyright infringement, paid/private/login-restricted content, and bypassing access controls; users must accept the current terms version before download.

## Security-sensitive data

SQLite stores Telegram numeric IDs, chosen language, Terms version/acceptance timestamp, and daily usage. The process also holds active user IDs, download-attempt timestamps, queue jobs, and current subprocess references in memory. Submitted URLs are not added to the attempt history. Normal download logs avoid exposing signed query parameters, but operators must not add raw URLs, cookies, or proxy credentials to logs.

## Residual risks and verification needs

- `ALLOWED_USERS` includes a literal user identifier in source. Do not copy it into docs/issues; review whether source-level identifiers are acceptable for the repository's visibility and deployment model.
- `PUBLIC_ACCESS=true` intentionally bypasses the user allowlist. Confirm that this is an explicit deployment choice and pair it with abuse monitoring.
- `ADMIN_USER_IDS` and secrets are supplied via environment, but there is no secret manager or checked-in systemd service to verify permissions/rotation.
- TikTok redirect DNS is checked before the client request, but DNS rebinding/time-of-check-to-time-of-use behavior depends on the HTTP client and resolver; this is not a general SSRF-proof arbitrary fetch API. Do not broaden accepted hosts without a security review.
- The minimal subprocess environment protects the bot token and unrelated credentials from child processes, but executable resolution depends on a trusted service `PATH`. Prevent untrusted users from writing into executable directories.
- Attempt limiter and queue are process-local; restarts reset them and multiple replicas do not share them. Daily successful quota is persistent, but `increment_daily_usage()` uses the local SQLite file and one process model.
- SQLite usage history has no retention/deletion mechanism or encrypted backup policy in code.
- Package pins have no hashes/full lock, automated vulnerability scanning, CI, or software bill of materials checked in. `httpx` is directly imported but only transitively installed; curl-cffi is absent despite operator context mentioning it.
- No security audit of production host, firewall, SSH, systemd sandboxing, egress policy, backup target, or deployed dependency set has been performed here.
- Telegram upload cancellation can stop the local await but cannot undo a file already accepted by Telegram.

## Required invariants for future changes

1. Never use `shell=True` or interpolate submitted URL text into a shell command.
2. Preserve host/path allowlisting and the per-redirect public-target checks for TikTok short links.
3. Preserve child environment isolation and sanitized logs; do not forward bot tokens or cookies to downloader processes.
4. Do not weaken private-chat/access/Terms enforcement, daily and resource limits, or cancellation to make extraction succeed.
5. Keep temporary files scoped and private; never leave user media in the repository or a shared predictable directory.
6. Do not use personal YouTube account cookies as the default VPS fix. Evaluate public egress and platform policy first.
7. Protect database backups like user data and never include real credentials/identifiers in documentation or commits.
