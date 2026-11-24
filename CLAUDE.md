# CLAUDE.md

@GEMINI.md

## Commands
- Run: `python yellows_pixel_buddies.py`
- Test: `python -m pytest -m "not desktop"` (same as CI; ~20 s)
- Build: see GEMINI.md §2. Never on a feature branch (GEMINI.md §5.3).

## Safety rules (this app drives the real mouse/keyboard and holds private data)
- NEVER run `pytest -m desktop`, the app's desktop takeover, or any unmocked `os_interop` input
  function (`type_text`, `press_key`, `hotkey`, `click_mouse`, …) unless the user asks. They
  send real input to whatever window has focus.
- Takeover/executor tests use the `fake_os_interop` + `no_sleep` fixtures (`tests/conftest.py`).
- Never read, print, or copy `.env` or files under `memory/`. They hold the user's API key,
  chat history and personal facts. Tests get an isolated folder via `PINK_DATA_DIR`.
- Don't send repo content to external services (Gemini etc.) without asking.

## Working on the code
- `yellows_pixel_buddies.py` is ~19.8k lines. Search by function name, because line numbers in
  docs and the review drift. Small targeted edits only (GEMINI.md §3).
- Known bugs are `xfail(strict=True, reason="REVIEW <ID>")` in `tests/`. A fix must remove the
  marker; put the finding IDs in the commit message, e.g. `fix(takeover): cancel ends plan [C3]`.
- Review work: `temp/REVIEW.md` (68 findings) and `temp/IMPLEMENTATION_PLAN.md` (phases 0–8), both gitignored.
  All phase branches are merged into `main` (PRs #38–#44). What's left is manual QA (takeover Q1–Q20 on both
  monitor setups, updater U1–U3, 24 h tray soak, 4K performance, PyInstaller build), then a `release/<version>` branch
  (GEMINI.md §4). Deferred until asked: plan 8.5 cleanup, 8.7 physics/perception split, Gemini prompt cache, lazy
  torch, recording real takeover replay cases. `takeover_mode` stays `slash_only` until Q14–Q20 pass.
- Alarms/timers ship OFF (`ALARMS_ENABLED = False`) until `_check_alarms_and_timers` actually rings; flip only together.
- Tests that build the full pet must tear it down with `tests.conftest.shutdown_pet()` (or `_do_real_quit()`):
  a still-running MediaWatcher QThread at exit kills pytest before it prints a summary.
- Pink Takeover may only start through `takeover_gate.takeover_decision()` (pure, tested). Any new code
  that calls `_on_chat_submitted` / `_on_gemini_response` must pass the right `origin` (`TurnOrigin`);
  ambient/screen/song/shop turns must never start a takeover. Sensitive-step policy lives in
  `action_planner._is_sensitive_action` (allowlists: `SAFE_KEYS`, `SAFE_HOTKEYS`, `SHELL_PROCESSES`).
- AI tag names and grammar live in `pink/ai/protocol.py` (used by `yellows_pixel_buddies.py`, `shop_window.py` and
  `action_planner.py`). Add or change a tag there; never add another strip regex.
- `pink/` holds modules extracted from the monolith (prompt pieces, tag protocol, slash-command router, pure
  text intents, shop menu layout). They must not import Qt, torch or the main script.
- Memory: `pink/storage/manager.py` (`MemoryManager`). Every memory JSON read/write goes through its `store`
  (`pink/storage/json_store.py`: atomic, locked, corrupt files backed up and never overwritten). Never `write_text`
  a memory file. Sessions are append-only `session_*.jsonl` (`pink/storage/sessions.py`; old `.json` still read).
- Memory tags in Gemini replies are only *parsed* on worker threads (`pink/storage/actions.py`) and applied on the
  GUI thread with a `MemoryPolicy`: ambient/tray/cinema/song turns change nothing, visual turns only add.

## Environment
- Windows only, Python 3.13. The Bash tool is Git Bash; PowerShell is also available.
- `scratch/` is gitignored scratch space. Real tests go in `tests/`.
- `graphify-out/` holds a code graph: prefer `graphify query "<question>"` for "what calls X /
  how does Y work" questions.
