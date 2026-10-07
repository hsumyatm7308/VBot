# Architecture Decision Records

These records describe current decisions inferred from implementation and operator context. They are not a substitute for future explicit review.

## ADR-001: Python Telegram bot with polling

- **Context:** The app uses asynchronous Telegram handlers and downloader subprocesses.
- **Decision:** Use Python and `python-telegram-bot` 22.8 with long polling.
- **Reason:** Matches the current implementation and async workflow.
- **Alternatives considered:** Webhooks, another Telegram framework, another language — not evidenced as evaluated.
- **Consequences:** A single polling token should have one active instance; no health HTTP endpoint exists.
- **Status:** Current.

## ADR-002: SQLite for persistent application data

- **Context:** The bot needs durable language, Terms acceptance, and daily usage.
- **Decision:** Store these in local SQLite at `vdlp.db`.
- **Reason:** Small single-process deployment, no external database dependency.
- **Alternatives considered:** Remote SQL service or distributed datastore — not evidenced as evaluated.
- **Consequences:** State is local to the host; no multi-host coordination, queue persistence, retention job, or backup automation.
- **Status:** Current; revisit before multi-instance deployment.

## ADR-003: yt-dlp/gallery-dl with FFmpeg for media acquisition

- **Context:** Platform extraction and media composition need different extractors and fallback strategies.
- **Decision:** Use pinned yt-dlp for video, gallery-dl for supported photo paths, and FFmpeg for merging plus TikTok photo/audio MP4 conversion.
- **Reason:** Existing platform-specific commands and tests preserve source quality/fallback behavior.
- **Alternatives considered:** Re-encode all videos, implement platform APIs, or centralize on one extractor — not selected in current code.
- **Consequences:** FFmpeg and sometimes a JS runtime must exist outside Python packages. Normal video selection avoids re-encoding; TikTok photo conversion does encode.
- **Status:** Current.

## ADR-004: Bounded Telegram updates and global media semaphore

- **Context:** Requests consume CPU, disk, network, and upstream rate limits.
- **Decision:** PTB updates default to 8 concurrent handlers; media acquisition defaults to 2 simultaneous slots.
- **Reason:** Separate Telegram responsiveness from expensive media work.
- **Alternatives considered:** Unlimited concurrency or semaphore across upload too — not selected.
- **Consequences:** Uploads do not occupy media semaphore slots; per-user workflow serialization is handled separately. Actual production override is **Unknown / needs verification**.
- **Status:** Current.

## ADR-005: One in-memory FIFO worker per user

- **Context:** A user should not run overlapping downloads, but follow-up requests should be queued.
- **Decision:** Allow one active request and up to two waiting requests, FIFO, per user in a process.
- **Reason:** Prevent overlap while preserving user submissions; queue mutations are synchronous on PTB's event loop.
- **Alternatives considered:** Reject all second requests (historical behavior), persistent queue, distributed broker — not current.
- **Consequences:** Waiting work is lost on restart; queues are not shared across replicas. `/cancel` clears waiters and cancels active work.
- **Status:** Current.

## ADR-006: Dedicated OS account and low production concurrency

- **Context:** Operator context reports a resource-constrained VPS intended to use a dedicated `vbot` account and systemd.
- **Decision:** Documentation recommends an unprivileged dedicated service account and conservative concurrency.
- **Reason:** Reduce blast radius and resource pressure.
- **Alternatives considered:** Running as root or increasing concurrency without measurement — not recommended.
- **Consequences:** Actual account, unit, service PATH, and production concurrency have not been verified from repository/host evidence.
- **Status:** Recommended, deployment verification pending; default code semaphore is 2.

## ADR-007: Minimal child-process environment

- **Context:** yt-dlp/gallery-dl/FFmpeg do not need the bot token or arbitrary application secrets.
- **Decision:** Pass only PATH, locale, and temporary-directory variables (plus Windows runtime essentials) to child processes.
- **Reason:** Avoid credential inheritance while retaining executable/runtime support.
- **Alternatives considered:** Inherit all process environment — rejected by current code.
- **Consequences:** Required executable locations and runtime variables must be configured through a trusted service PATH; arbitrary proxy environment variables are not inherited, while configured proxy arguments are passed explicitly to supported platform commands.
- **Status:** Current security invariant.

## ADR-008: Do not use personal YouTube cookies as default production remedy

- **Context:** Operator-reported VPS requests sometimes receive YouTube `LOGIN_REQUIRED` bot checks while a normal ISP works.
- **Decision:** Do not make personal account cookies the default production approach; verify the issue and evaluate approved egress/runtime options.
- **Reason:** Cookies carry sensitive account access and can bypass restrictions or create account risk.
- **Alternatives considered:** Add personal cookies to production by default — not selected.
- **Consequences:** Some public YouTube URLs may fail from certain egress networks; current production status is **Unknown / needs verification**.
- **Status:** Operator policy; not enforced as a code feature.

## ADR-009: Temporary, scoped media files

- **Context:** Downloads need a place for intermediate fragments and final files.
- **Decision:** Use Python `TemporaryDirectory` per job and remove its contents when processing exits.
- **Reason:** Limit persistent exposure and simplify normal cleanup.
- **Alternatives considered:** Permanent shared media directory — not used.
- **Consequences:** Restart cleanup of already orphaned temp directories depends on OS/runtime behavior; no broad cleanup daemon is implemented.
- **Status:** Current.

## ADR-010: No Telegram file-id cache or same-media single-flight

- **Context:** Reusing prior Telegram uploads could reduce bandwidth, but requires canonical media identity, privacy semantics, persistence, and expiration.
- **Decision:** Do not cache uploaded `file_id`s or coalesce identical requests today.
- **Reason:** No cache/key/retention/privacy design exists in current code; avoid accidental cross-user sharing.
- **Alternatives considered:** Persistent `file_id` cache and in-flight deduplication — possible future evaluation only.
- **Consequences:** Repeat requests may redownload and reupload identical media; no cache TTL exists because there is no cache.
- **Status:** Current absence; possible future work is **PLANNED for evaluation only**.
