# Architecture

This document describes the checked-in single-process implementation. Product behavior is in [SPEC.md](SPEC.md); security invariants and risks are in [SECURITY.md](SECURITY.md).

## Modules

| Module | Responsibility |
|---|---|
| `bot.py` | Validates required token, initializes SQLite, builds the PTB polling application, registers handlers, and shuts down queue workers. |
| `config.py` | Loads `.env`, parses configuration, and defines limits/defaults. |
| `database.py` | Creates SQLite tables and implements Terms, language, daily usage, and admin-stat queries. |
| `platforms.py` | Recognizes supported host/path families and manually resolves TikTok short links with redirect safety checks. |
| `handlers.py` | Compatibility façade; assembles dependencies for download orchestration and re-exports UI/command handlers. |
| `telegram_handlers/` | Telegram access guard, UI, commands, cancellation, queue, and download orchestration. |
| `downloaders.py` | Compatibility façade for public downloader APIs. |
| `downloader_core/` | Platform command construction, metadata/format logic, subprocess execution, and fallback runner. |
| `utils.py` | Download exception types, log sanitization, temporary-space preflight, file-size helper, and progress updates. |
| `i18n.py` | English and Myanmar UI/error strings. |
| `tests/` | Standard-library `unittest` suites. |

## Telegram update and download flow

```mermaid
sequenceDiagram
    participant T as Telegram
    participant A as PTB update handler
    participant G as Private-chat guard
    participant H as Download request handler
    participant Q as Per-user FIFO worker
    participant S as Global media semaphore
    participant D as Platform downloader
    participant P as yt-dlp/gallery-dl/FFmpeg
    participant U as Telegram upload
    participant DB as SQLite

    T->>A: text link update
    A->>G: enforce_private_chat
    G->>H: allow private chat only
    H->>H: access, language, Terms, quota, URL and attempt checks
    H->>Q: enqueue (one active + up to two waiting)
    Q->>S: acquire media slot when this user's job starts
    S->>D: dispatch platform operation
    D->>P: subprocess arguments, isolated environment
    P-->>D: output / downloaded files
    D-->>S: media path (slot released)
    Q->>U: upload media; job remains serialized for this user
    U-->>Q: upload success
    Q->>DB: increment UTC daily usage
    Q-->>T: localized final status
```

### The concurrency and limiting controls are distinct

1. **Telegram update concurrency:** PTB is configured by `MAX_CONCURRENT_UPDATES` (default 8). This governs simultaneous update callbacks, not media processes.
2. **Per-user queue:** `DownloadQueueManager` in `telegram_handlers/queue.py` starts one worker per user. It permits one active job and two waiting jobs. This serializes the full request workflow for a user, including upload; it is in-memory and process-local.
3. **Global media semaphore:** `MAX_CONCURRENT_DOWNLOADS` (default 2) is an asyncio semaphore around `acquire_media()`. It limits active media acquisition/conversion, not the upload phase. Separate event loops get separate semaphores.
4. **Attempt rate limiter:** `downloader_core/process.py` stores monotonic timestamps in process memory. Defaults: 15-second cooldown and five accepted attempts per rolling 600 seconds. While a user already has work queued/active, the cooldown is skipped for additional queue submissions; the rolling cap still applies. Attempt state resets on restart.
5. **Daily quota:** SQLite stores successful upload counts by UTC date. Default is 30 per user/date. A queued job checks quota again when it begins. This is accounting, not concurrency control.

Queue capacity (`max_queued=2`) is currently a code constant rather than a setting. Running multiple bot instances does not provide shared FIFO or shared rate limiting.

## Download lifecycle and failure paths

1. `telegram_handlers/access.py` stops group/channel messages and callbacks.
2. `telegram_handlers/download.py:prepare_request()` checks access, saved language, Terms acceptance, daily count, HTTP URL prefix, Instagram Stories, and platform validation.
3. It records an attempt and submits a closure/job to `DOWNLOAD_QUEUE`. Queue-full and cooldown failures return localized feedback.
4. TikTok short links go through manual redirect resolution. Each redirect is checked against allowed TikTok hosts and public DNS/IP targets before the next HTTP request.
5. A status updater runs while the job processes. Media acquisition enters the global semaphore, checks cancellation and free temp space, and dispatches platform-specific behavior.
6. Download command construction is in `downloader_core/commands.py` and platform files. YouTube runs metadata preflight and size selection; other platforms use their own configured fallback commands.
7. `downloader_core/process.py` launches argument arrays with `asyncio.create_subprocess_exec`, an allowlisted child environment, process session, captured output, timeout, and process-group cancellation.
8. Fallback result classification is in `downloader_core/runner.py`. It checks duration/file-size/Pinterest unsupported-media markers across attempts, accepts a real later success, finds the output, and enforces actual YouTube output size.
9. `TemporaryDirectory` scopes download artifacts. After acquisition, the handler checks actual size again and uploads video with `reply_video()` or Instagram image with `reply_document()`.
10. Only after upload returns successfully does the handler increment persistent daily usage. Errors map to localized responses, and cleanup happens as the temp-directory context exits.

Cancellation behavior: `/cancel` clears waiting jobs, signals the active subprocess (SIGTERM then SIGKILL after a short grace period), cancels the worker task, and awaits it. Application shutdown invokes queue shutdown and process cancellation. The worker manager catches unexpected per-job errors to avoid stranding later FIFO jobs.

## Platform-specific logic

- `youtube.py` has metadata extraction, size estimation, 90% preflight margin, player-client fallback, 1080p/720p/480p selector ordering, actual size retry, and temporary attempt cleanup. Format definitions are in `formats.py`.
- `tiktok.py` constructs video fallback commands and the gallery-dl + FFmpeg single-photo/audio path. Photo slideshows are rejected.
- `instagram.py` constructs yt-dlp video commands and a gallery-dl single-photo fallback. The handler attempts the video path for `/p/` first. Gallery-dl 429 maps to a dedicated photo-specific error. Multi-item carousels are rejected.
- `twitter.py` preserves three extractor API variants and optional proxy arguments.
- `pinterest.py` supports video Pins with its configured format/sort and maps detected image-only/no-video responses to a controlled error.

## Database responsibilities

`database.py` uses stdlib SQLite and `DB_PATH = "vdlp.db"` relative to the process working directory. Tables:

- `legal_acceptances`: one current terms version and acceptance timestamp per Telegram user ID.
- `daily_usage`: successful-upload count keyed by user ID and UTC date.
- `user_preferences`: selected language keyed by Telegram user ID.

There is no queue table, attempt-history table, media metadata/cache, or data-retention job. `/stats` derives unique successful users, active-today users, and today's successful downloads from `daily_usage`; currently downloading is derived from the active user state set.

## Caching and deduplication

**CURRENT:** none. The bot does not cache Telegram `file_id`, reuse previously uploaded media, canonicalize media identifiers for reuse, or coalesce simultaneous requests for the same media. These are possible future investigations, not implemented functionality.
