# Technology Inventory

Versions below are reported only where pinned in `requirements.txt`. Python minimum is inferred from syntax in source (for example `str | None`): **Python 3.10+**. The repository does not pin a Python patch version.

| Component | Version / status | Why it exists |
|---|---|---|
| Python | 3.10+ inferred; patch version unpinned | Application, subprocess orchestration, SQLite access, and `unittest` suite. |
| `python-telegram-bot` | `22.8` pinned; required | Telegram polling application, handlers, callback UI, uploads, and bounded update concurrency. |
| `yt-dlp` | `2026.8.19` pinned; required | Video extraction for supported platforms. |
| `yt-dlp-ejs` | `0.8.0` pinned; required by configured yt-dlp JS challenge-solving support | EJS challenge scripts. A compatible JS runtime is external and not installed/configured by this repository. |
| `gallery-dl` | `1.32.12` pinned; required for current photo paths | TikTok photo+audio asset retrieval and Instagram single-photo fallback. |
| `python-dotenv` | `1.2.3` pinned; required | Loads `.env` from the process working directory. |
| `httpx` | Required by direct import in `platforms.py`; not directly pinned | Async HTTP client used for manually validated TikTok short-link redirects. It is normally present transitively through PTB, but the direct dependency is not explicit. |
| SQLite | Python standard library; required | Persistent language, Terms acceptance, and daily usage data. Database file is `vdlp.db`. |
| FFmpeg | External executable; required for paths that merge media and TikTok photo conversion | Merges separate audio/video streams and encodes a single TikTok photo plus audio to MP4. Not installed by pip. |
| Deno or another yt-dlp-supported JS runtime | External; conditionally needed for YouTube extraction challenges | The repo includes `yt-dlp-ejs` but neither installs nor verifies a runtime. Deno is a likely operator choice, not a checked-in guarantee. |
| curl-cffi | **Unknown / needs verification** | Operator context says TikTok browser impersonation may be needed, but it is absent from requirements and code does not pass an explicit `--impersonate` option. |
| Tests | Python `unittest`; required for development | Async and synchronous tests covering downloaders, platform routing, security, queue, access, stats, and handlers. No pytest dependency or CI workflow is checked in. |
| Production OS/service manager | **Unknown / needs verification** | No OS or service manager is declared by repository files. A `vbot`/systemd deployment was operator-reported; see deployment guide for an illustrative template only. |

## Dependency maintenance

The five packages above are exact-pinned, but there is no complete transitive lockfile, hashes, automated update bot, or dependency vulnerability workflow in the repository. Before changing downloader versions, run the platform and fallback tests and perform a controlled manual smoke test. See [OPERATIONS.md](OPERATIONS.md).

Potential dependency action: decide whether to add `httpx` as a direct dependency and whether TikTok impersonation/curl-cffi is a real production requirement. Do not add packages based only on historical incidents.
