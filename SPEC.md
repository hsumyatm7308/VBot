# Product Specification

Status labels: **CURRENT** means verified in the checked-in implementation; **PLANNED** means not implemented and not promised.

## Purpose

**CURRENT** — VDlp is a Telegram bot for downloading supported public media links and returning the media to a user in a private Telegram chat. Users are responsible for having the right to download content and complying with applicable law and platform terms. Public availability alone does not imply permission or copyright-free status.

## Supported media

| Platform | Accepted link families | Current behavior |
|---|---|---|
| YouTube | `youtube.com` watch/shorts/live paths and nonempty `youtu.be` paths | Video download; adaptive 1080p → 720p → 480p strategy, preferring H.264/AAC where selected by the format rules. |
| TikTok | Video/photo paths on recognized TikTok hosts; nonempty `vm.tiktok.com` and `vt.tiktok.com` short links | Video download; short links are manually resolved with redirect and target checks. One-photo post with audio becomes MP4. Multi-photo slideshow is unsupported. |
| X/Twitter | Recognized X/Twitter hosts with a `/status/` path | Video download with extractor fallbacks; optional `TWITTER_PROXY`. |
| Instagram | `/reel/`, `/reels/`, `/p/`, `/tv/` on recognized Instagram hosts | Video/reel download. `/p/` is video-first and can fall back to a single image document. Optional `INSTAGRAM_PROXY`. |
| Pinterest | `pin.it/<code>` and `/pin/<id>` on recognized Pinterest hosts | Public video Pins only. Pinterest image-only Pins are rejected with a controlled message. |

Host and path validation is implemented in `platforms.py`; it is not a general-purpose URL fetcher. See [SECURITY.md](SECURITY.md) for redirect handling and residual concerns.

## User flow

1. A Telegram user opens a private chat and chooses English or Myanmar.
2. The user reviews and accepts the current Terms of Use. Acceptance is stored against the current terms version.
3. The user submits a supported link. The bot checks access, language, terms, daily quota, URL shape, and a rolling request-attempt limiter before enqueueing.
4. The user receives a status message; their request runs in FIFO order for that user.
5. The bot downloads into a temporary directory, checks the final size, uploads the result, then increments persistent daily usage.
6. The status is updated with success or a localized controlled failure. Temporary download files are removed when the temporary-directory scope exits.

## Commands

- `/start` — language prompt, Terms, or home screen depending on saved preferences and acceptance.
- `/help` — usage and supported platform list.
- `/status` — current UTC-day usage, remaining quota, and Terms acceptance state.
- `/stats` — aggregate operational counts for configured admin IDs only.
- `/language` — choose English or Myanmar.
- `/terms` — view Terms of Use.
- `/report` — show the configured copyright/abuse contact.
- `/myid` — show the caller's Telegram ID and available profile name/username.
- `/cancel` — cancel the caller's current job and clear their waiting queue.

All updates from non-private chats are stopped by a global access handler. By default, access is restricted to the source-defined `ALLOWED_USERS`; `PUBLIC_ACCESS=true` changes that behavior. Admin status is independently configured through `ADMIN_USER_IDS`.

## Queue, concurrency, and request limiting

- **Per-user queue — CURRENT:** one active job plus at most two waiting jobs, FIFO, in this process's memory. A full waiting queue is rejected. Queue state is lost on process restart and is not shared across multiple bot instances.
- **Telegram update concurrency — CURRENT:** `MAX_CONCURRENT_UPDATES`, default 8, configures PTB update handling.
- **Media concurrency — CURRENT:** `MAX_CONCURRENT_DOWNLOADS`, default 2, gates media acquisition with an asyncio semaphore. It does not gate Telegram uploads.
- **Attempt limiter — CURRENT:** default 15-second cooldown and at most five accepted requests in a rolling 600-second window per user. When a user already has queued/active work, the short cooldown is bypassed for queue additions; the rolling cap remains. The attempt is recorded before a queue-full response.
- **Daily quota — CURRENT:** 30 successful uploads per user per UTC calendar date. Failed, cancelled, over-limit, or upload-failed jobs do not increment usage. A queued job rechecks quota when it starts.

These are distinct controls, not interchangeable limits. Implementation details are in [ARCHITECTURE.md](ARCHITECTURE.md).

## Media limits and conversion

- **CURRENT:** maximum duration is 900 seconds (15 minutes); exactly 15:00 is accepted by YouTube metadata boundary tests. Instagram and Pinterest use unknown-safe yt-dlp duration filtering; known over-limit content is rejected.
- **CURRENT:** `MAX_MB = 49` (the code computes file sizes using 1,048,576 bytes per unit). yt-dlp receives a configured `--max-filesize` limit; the final artifact is also checked before Telegram upload.
- **CURRENT:** YouTube metadata preflight estimates available candidate sizes and uses a 90% safety threshold when estimates exist; runtime fallback verifies actual size and steps down quality if needed.
- **CURRENT:** normal video streams are not re-encoded by the format selectors; FFmpeg merging/remuxing is allowed. TikTok single-photo-plus-audio is intentionally encoded into MP4 using FFmpeg.

## Cancellation and failures

`/cancel` clears waiting jobs and asks the downloader process layer to stop the active subprocess group, then cancels/awaits the per-user worker. Cancellation during Telegram API upload is task cancellation; it cannot retract a message Telegram has already accepted. Failures map to localized messages for duration, size, disk space, timeout, Instagram rate limiting/carousels, and unsupported Pinterest media. Raw subprocess output is not intentionally shown as the user-facing failure text.

## Language, persistence, and privacy

English and Myanmar strings live in `i18n.py`. SQLite stores language preference, Terms version/acceptance timestamp, and UTC-dated successful-download counts. The bot necessarily receives Telegram account/message data. Submitted URLs are not stored in the download-attempt limiter. No media cache or cross-user deduplication is implemented. Data retention/deletion beyond daily counters remaining in SQLite is **Unknown / needs verification**; there is no checked-in retention job.

## Unsupported cases

- Instagram Stories, Instagram carousels, TikTok multi-photo slideshows.
- Pinterest image-only Pins.
- Unsupported hosts/path families, private or login-restricted media, and material the requester lacks permission to download (also prohibited by Terms).
- Durable queue recovery, Telegram `file_id` caching, and same-media request deduplication (**PLANNED only for evaluation; not implemented**).

## Acceptance criteria for behavior changes

Any behavior change must preserve access/Terms requirements, private-chat-only operation, configured attempt and daily limits, one active per-user worker, global media concurrency, cancellation, temporary cleanup, and post-upload-only usage accounting unless an explicitly approved spec change says otherwise. Add focused tests for the affected user flow and localization.
