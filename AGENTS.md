# Instructions for Coding Agents

This is the canonical repository instruction file. Read it before changing code. Product behavior is in [SPEC.md](SPEC.md); architecture and trust boundaries are in [ARCHITECTURE.md](ARCHITECTURE.md) and [SECURITY.md](SECURITY.md).

## Before every task

- [ ] Read the task and identify whether it asks for diagnosis, documentation, or code changes.
- [ ] Inspect the actual files, callers, tests, and relevant Git state before editing; do not infer behavior from names or old chat history.
- [ ] Check `git status` and preserve all existing user changes and untracked files. Never reset, clean, or revert unrelated work.
- [ ] Identify the relevant limits, error mappings, localization, subprocess/security controls, and cancellation paths before touching downloader behavior.
- [ ] If a fact cannot be established from code, tests, or checked-in operational artifacts, label it **Unknown / needs verification**.

## Working rules

- Keep changes within the requested scope. Do not make adjacent behavior changes without asking when they alter product behavior.
- Never expose, copy, or commit tokens, cookies, proxy credentials, private keys, personal identifiers, or production secrets. `.env` and databases are private runtime data.
- Do not weaken security controls just to make a downloader succeed. Preserve URL allowlisting and redirect checks, sanitized logs, private-chat enforcement, resource limits, and minimal subprocess environment.
- Never use `shell=True`. Continue to invoke subprocesses with argument arrays and the established process-group cancellation/timeout handling.
- Keep platform-specific extraction and format logic isolated in `downloader_core/`; keep Telegram UI/orchestration in `telegram_handlers/` and handlers thin where practical.
- Keep compatibility façades (`downloaders.py`, `handlers.py`) working unless the task explicitly authorizes an API migration.
- Preserve current selectors, proxies, retry/fallback order, duration/file-size rules, daily accounting, queue semantics, and user-visible Burmese/English strings unless explicitly requested otherwise.
- Add or update focused tests for behavioral changes. Prefer the existing standard-library `unittest` suite; do not add test dependencies without need.
- Update canonical docs when behavior, architecture, configuration, security, or operations change. Keep current behavior separate from proposals and history.
- Do not create a commit or push unless the user explicitly asks.
- Ask only when a material product decision is ambiguous or an action would be destructive/outside authorized scope. For normal reversible implementation details, make a bounded assumption and document it.

## Definition of Done

- Requested behavior is implemented or the diagnosis is evidence-backed; unrelated user work remains untouched.
- Relevant tests pass. For broad changes run the complete suite:

  ```bash
  .venv/bin/python -m unittest discover -s tests -q
  .venv/bin/python -m py_compile bot.py config.py database.py platforms.py utils.py handlers.py downloaders.py downloader_core/*.py telegram_handlers/*.py tests/*.py
  git diff --check
  ```

- Review the complete diff for unintended behavior changes, secrets, generated files, and stale documentation.
- Report what changed, verification results, known limitations, and any **Unknown / needs verification** facts. Never claim a live production check that was not performed.
