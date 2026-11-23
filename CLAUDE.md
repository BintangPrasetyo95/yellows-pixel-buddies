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
- Current work: `temp/REVIEW.md` (68 findings) and `temp/IMPLEMENTATION_PLAN.md` (phases 0–8;
  Phase 0 merged, Phase 1 on `fix/takeover-safety-gates`). Both are gitignored and exist locally only.
- Pink Takeover may only start through `takeover_gate.takeover_decision()` (pure, tested). Any new code
  that calls `_on_chat_submitted` / `_on_gemini_response` must pass the right `origin` (`TurnOrigin`);
  ambient/screen/song/shop turns must never start a takeover. Sensitive-step policy lives in
  `action_planner._is_sensitive_action` (allowlists: `SAFE_KEYS`, `SAFE_HOTKEYS`, `SHELL_PROCESSES`).
- Any change to AI tag parsing must update both `yellows_pixel_buddies.py` and `shop_window.py`.

## Environment
- Windows only, Python 3.13. The Bash tool is Git Bash; PowerShell is also available.
- `scratch/` is gitignored scratch space. Real tests go in `tests/`.
- `graphify-out/` holds a code graph: prefer `graphify query "<question>"` for "what calls X /
  how does Y work" questions.
