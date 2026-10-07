# Project Context

## Goal and maturity

VDlp provides Telegram users with a private-chat workflow for downloading supported public media. It is a working single-process Python bot with platform-specific yt-dlp/gallery-dl integrations, persistent SQLite preferences/Terms/quota data, bilingual UI, and focused automated tests. It is not a distributed worker system: download queues and attempt limits are process-local.

## Current status (verified from repository)

- Current source includes YouTube, TikTok, X/Twitter, Instagram, and Pinterest video paths, with the documented TikTok and Instagram photo-specific paths.
- The last reviewed Git commit at documentation time is `0b64c86` (`feat: add per-user download queue`, 2026-10-05); branch and origin tracking are environment-specific, not product configuration.
- The test suite is standard-library `unittest`; a baseline run during this documentation task completed 122 tests successfully.
- No CI workflow, deployment manifest, systemd unit, Dockerfile, environment example, or operations runbook exists in the repository.
- There is no media cache, Telegram `file_id` cache, or same-media single-flight deduplication in the checked-in code.

## Current production environment

**Unknown / needs verification from the live host.** The repository does not establish the production OS, service account, install directory, systemd unit, actual concurrency overrides, Deno/FFmpeg availability, or backup/monitoring setup.

The following are operator-reported context supplied for this documentation task, not verified by this repository or a live host check:

- Production is intended to run under a dedicated `vbot` OS account and systemd.
- The VPS is resource-constrained and should use low download concurrency.
- YouTube requests from the VPS have reportedly received `LOGIN_REQUIRED` / “Sign in to confirm you're not a bot”, while the same downloader setup worked from a normal local ISP connection.
- Personal YouTube account cookies should not be the default production workaround.
- TikTok browser impersonation support via curl-cffi may be required in the deployment environment.

Treat these as verification tasks, not proven configuration. See [DEPLOYMENT.md](DEPLOYMENT.md) and [TECHNOLOGY.md](TECHNOLOGY.md).

## Durable operational and design facts

- Default daily quota is 30 successful uploads per UTC day; maximum duration is 900 seconds and configured file-size ceiling is 49 MiB.
- A per-user in-memory FIFO has one active job plus up to two waiting jobs. A global semaphore (default 2) gates media acquisition. These differ from Telegram update concurrency (default 8).
- A rolling attempt limit defaults to five attempts per 600 seconds plus a 15-second cooldown; queued work bypasses only the cooldown.
- SQLite file name is `vdlp.db` under the process working directory. It stores legal acceptance, daily successful counts, and language preference.
- Child subprocesses receive a minimal allowlisted environment; downloader commands avoid a shell. Temporary job files use `TemporaryDirectory`.
- User-facing errors are bilingual; stats are restricted to configured `ADMIN_USER_IDS`.

## Important incidents and fixes recorded in Git

Commit history confirms an architectural split into `downloader_core/` and `telegram_handlers/` (2026-10-01), TikTok H.264 format preference (2026-10-01), and admin statistics/security hardening plus per-user queue work (2026-10-05). The current code and tests—not commit subjects—define actual behavior. Historical X/Twitter timeout and YouTube/VPS incidents are **operator-reported** and current status is **Unknown / needs verification**.

## Known limitations and unresolved questions

- Queue and rate-limit attempt history are lost on restart and are not coordinated between multiple bot replicas.
- No retry/recovery mechanism resumes an interrupted active or waiting download after restart.
- No monitoring/health endpoint, deployment automation, CI, dependency lock with hashes, or automated backup/retention process is checked in.
- `httpx` is directly imported but not explicitly pinned in `requirements.txt`; it is normally installed through python-telegram-bot's dependency graph. Confirm whether it should be declared directly.
- `curl-cffi`/yt-dlp impersonation flags are not present in the checked-in requirements or command construction; verify whether the operator-reported TikTok setup is still needed.
- `yt-dlp-ejs` is pinned, but a JavaScript runtime (for example Deno) is not installed or checked by this repository.
- Production account, service, working directory, effective environment, concurrency values, VPS egress strategy, and database backup status require operator verification.
- SQLite keeps prior dated usage rows; no retention/deletion policy is implemented.

## Current priorities

1. Keep platform behavior and security invariants covered by tests.
2. Verify production deployment/runtime facts and capture the actual systemd configuration without adding secrets.
3. Decide whether direct/transitive runtime dependencies should be declared and locked explicitly.
4. Evaluate operational monitoring and queue persistence only after measuring real production needs.

## Common misunderstandings to avoid

- `MAX_CONCURRENT_UPDATES`, `MAX_CONCURRENT_DOWNLOADS`, queue capacity, attempt limiting, and daily quota solve different problems.
- Daily usage increments only after Telegram upload succeeds; a request attempt is separately counted by the in-memory rate limiter.
- Instagram `/p/` is not assumed to be a photo: video is attempted first, and only `DownloadFailedError` triggers the photo fallback.
- “No re-encoding” applies to normal source-video format selection, not TikTok single-photo-plus-audio conversion.
- `ALLOWED_USERS` is currently source-defined; `ADMIN_USER_IDS` is a separate environment-driven stats authorization list.
- A supported public URL does not imply that private/login-gated content is allowed by Terms.
