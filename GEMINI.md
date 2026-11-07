# Yellow's Pixel Buddies — Agent Workspace Rules & Guidelines

`Yellow's Pixel Buddies` is an animated Windows desktop companion (featuring the tsundere character **Pink**) that walks along the taskbar, interacts with the user, monitors songs and apps, and integrates with Google Gemini AI for dialogue, vision, reminders, and alarms.

---

## 1. Project Architecture & Key Files

- **`yellows_pixel_buddies.py`**: Main desktop pet application (~16,800 LOC monolith). Contains:
  - Configuration section (`1. CONFIGURATION` at top).
  - Windows API interop (`ctypes`, `user32`, `dwmapi`) for taskbar metrics (`ABM_GETTASKBARPOS`), DPI scaling, transparent click-through, and window switch tracking.
  - State machine, frame animations, physics (ballistic cursor jump, hanging, bomb tosses).
  - Gemini AI thread worker, vision screen capture, prompt builder, action tag parser.
  - Alarms, focus timers, and system tray control center (`QSystemTrayIcon`).
  - GitHub release auto-updater.
- **`shop_window.py`**: Deltarune-styled Dark World Sanctuary / Shop UI (`DeltaruneShopWindow`, ~3,300 LOC). Handles tasks, goals, alarms/timers GUI, facts editor, Dark Dollars wallet, and item dialogue.
- **`sprites/`**: Transparent PNG sequences sorted numerically (`1.png`, `2.png`, ...).
- **`fonts/`**: Retro pixel typography (`fonts/determination/determination.ttf`).
- **`sounds/`**: Retro audio effects for shop menus, coin clinks, and pet reactions.
- **`memory/`**: Runtime user data (facts, reminders, alarms, wallet, session history).
- **`Yellows-Pixel-Buddies.spec`**: PyInstaller build specification.
- **`installer.iss`**: Inno Setup script for creating the Windows setup installer.
- **`build_release.bat`**: All-in-one build script (PyInstaller + Inno Setup).

---

## 2. Core Development Commands

- **Run from source**:
  ```powershell
  python yellows_pixel_buddies.py
  ```
- **Install dependencies**:
  ```powershell
  pip install PyQt5 requests pygame
  # Optional for Windows GSMTC media playback detection:
  pip install winrt-runtime winrt-Windows.Media.Control
  ```
- **Build standalone executable & installer**:
  ```cmd
  build_release.bat
  ```
  Or manually:
  ```powershell
  python -m PyInstaller --clean Yellows-Pixel-Buddies.spec
  & "$env:LOCALAPPDATA\Programs\Inno Setup 6\iscc.exe" installer.iss
  ```

---

## 3. Engineering Rules & Constraints

### ⚠️ Surgical Edits on Monolithic Files
- `yellows_pixel_buddies.py` is over 16,000 lines long.
- **Never attempt full file rewrites or indiscriminate bulk replacements.**
- Always use targeted, minimal diffs (`edit_file`) with sufficient surrounding context.
- Verify imports, class scopes, and method references before making changes.

### 🧵 PyQt5 Thread Safety
- Background tasks (Gemini API calls, vision screenshots, GSMTC audio detection, timers) run in worker threads (`threading.Thread` or `QThread`).
- **Never mutate or call Qt GUI widgets directly from background threads.**
- All UI updates must be routed through PyQt signals (`pyqtSignal`) or thread-safe message queues.

### 🪟 Windows OS & High-DPI Interop
- Transparent, frameless window layers rely on Windows OS flags (`WS_EX_TRANSPARENT`, `Qt.FramelessWindowHint`, `Qt.WindowStaysOnTopHint`).
- Click-through logic uses pixel alpha testing (`CLICK_THROUGH_TRANSPARENT`).
- Maintain DPI-aware coordinate math (`PerMonitorV2`, scale factors 1.0x-2.0x) and taskbar bound detection (`ABM_GETTASKBARPOS`). Avoid assumptions about single-monitor setups or taskbar positions (bottom, top, left, right, auto-hidden).

### 💾 Storage & Persistence Hierarchy
- User data must follow the resolution logic in `_resolve_user_data_dir()`:
  1. **Portable mode**: If `portable.txt` exists next to executable -> local directory.
  2. **Development mode**: If running raw script and local `./memory/` exists -> local directory.
  3. **Production mode**: Standard Windows `%APPDATA%\YellowsPixelBuddies\memory` (survives app updates and reinstalls).
- Never hardcode raw file paths for persistent state.

### 🎭 Pink's Persona & AI Action Tag Protocol
- Pink's dialogue style is inspired by **Mad Mew Mew** from *Undertale / DELTARUNE*: proud, dramatic, tsundere, observant, secretly affectionate. Uses asterisks (`* ...`) and retro typewriter pacing.
- The AI prompt and dialogue parser recognize structured action tags:
  - `[set_timer: <duration>, <label>]`
  - `[set_alarm: <time>, <label>]`
  - `[emotion: <state>]`
- Do not alter or break this tag format without updating the parser in both `yellows_pixel_buddies.py` and `shop_window.py`.

### 📦 Asset & PyInstaller Packaging Sync
- **New animation folders**: If adding a new folder under `sprites/<new_state>`, register its name in `ALL_STATES` in `yellows_pixel_buddies.py`.
- **New top-level assets**: If adding new asset folders (e.g., `sounds/`), make sure they are listed in `datas` inside `Yellows-Pixel-Buddies.spec` so PyInstaller packages them into the final `.exe`.

---

## 4. Release & Version Bump Protocol (MANDATORY)

Whenever preparing a release, drafting release notes, or building distribution artifacts, you **MUST** ensure all version identifiers are updated in tandem:

1. **Main Pet Script**:
   Update `APP_VERSION` in `yellows_pixel_buddies.py` (near line 128):
   ```python
   APP_VERSION = "X.Y.Z.W"
   ```
2. **Inno Setup Installer Script**:
   Update `#define MyAppVersion` in `installer.iss` (near line 5):
   ```iss
   #define MyAppVersion "X.Y.Z.W"
   ```
3. **Release Notes & Documentation**:
   Ensure `temp/release_notes_vX.Y.Z.W.md` (or `README.md`) matches the exact same version string.
4. **Rebuild Order**:
   **NEVER run `build_release.bat` before updating both `yellows_pixel_buddies.py` and `installer.iss`.** Otherwise, `Yellows-Pixel-Buddies-Setup.exe` will be compiled with the previous version's metadata and the updater (`UpdateCheckerThread`) will loop or download stale binaries.
5. **Pre-Release Check**:
   Before committing, verify synchronization across the codebase:
   ```powershell
   Select-String -Path "yellows_pixel_buddies.py", "installer.iss" -Pattern "(APP_VERSION|MyAppVersion)"
   ```

---

## 5. Multi-Agent & Git Branching Protocol

When operating in an environment where multiple agents work simultaneously across feature branches:

1. **Always Verify Active Branch**:
   - Check `git branch --show-current` before staging or committing any code.
   - Never switch branches (`git checkout` / `git switch`) without explicit user instructions.

2. **Surgical Git Staging Only**:
   - **NEVER use `git add .` or `git add -A`**.
   - Only stage the exact files modified for the specific task assigned to this agent (e.g. `git add yellows_pixel_buddies.py`).
   - This prevents accidentally committing uncommitted work or test files generated by another agent.

3. **Branch-Scoped Versioning**:
   - Do **NOT** bump `APP_VERSION` or `MyAppVersion` on normal feature/bugfix branches.
   - Version bumping and running `build_release.bat` is strictly reserved for the final release preparation branch or when the user explicitly requests a release build.

4. **Push Isolation**:
   - Always push explicitly to your assigned branch (`git push origin <branch-name>`).
   - Never push directly to `main` or force push (`--force`) without explicit user permission.


