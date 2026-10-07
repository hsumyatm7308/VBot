# Roadmap

This is a set of maintenance priorities, not a promise or a list of implemented features. Current state is defined by code/tests and [SPEC.md](SPEC.md).

## Now

- Keep downloader selectors, limits, error classification, queue behavior, and security invariants covered by focused tests.
- Verify real production facts: service account, systemd unit, working directory, runtime PATH, Deno/FFmpeg availability, concurrency override, backup/monitoring, and current YouTube VPS behavior.
- Resolve direct dependency declarations for `httpx` and verify whether TikTok actually needs curl-cffi/impersonation in production.
- Preserve a clear distinction between local source facts and operator-reported deployment observations.

## Next (evaluate before committing)

- Add CI to run compile checks and the `unittest` suite on supported Python versions.
- Add a fully reproducible dependency lock (including transitive versions and hashes) and a reviewed dependency-update process.
- Add documented/automated database backup and restore verification, plus a defined retention policy for dated usage records.
- Add deployment configuration only after the actual host, service user, paths, and secret-management approach are verified.
- Add lightweight health/alerting based on operational needs; no health endpoint/monitoring integration exists now.
- Expand integration/smoke tests for each platform while keeping them opt-in and free of credentials/private content.

## Later / exploratory

- Evaluate Telegram `file_id` caching, including authorization/privacy model, stable cache keys, invalidation, and TTL.
- Evaluate canonical media IDs and same-media single-flight deduplication; do not share media across users without a privacy/terms decision.
- Evaluate a better YouTube egress/IP strategy for VPS bot checks without defaulting to personal account cookies or bypassing access controls.
- Evaluate stronger worker/process isolation and distributed queueing only if deployment becomes multi-instance or resource needs justify it.
- Evaluate additional observability and queue metrics without exposing URLs or personal identifiers.

All items above are **PLANNED / candidate work**, not current capabilities.
