# Release Notes - v0.9.8.3 🐾

**Yellow's Pixel Buddies v0.9.8.3** is a critical stability update focused on bulletproofing the desktop companion's auto-updater engine, eliminating updater crashes and "can't open python" errors on secondary end devices, providing seamless auto-updating for Python/Git development environments, and resolving process restart and pathing errors.

---

## 🌟 What's New & Major Highlights

### 🔄 Bulletproof Multi-Stage Auto-Updater Engine
- **PowerShell Process-Waiting Worker**: Completely replaced fragile command-prompt batch scripts with a hardened background PowerShell updater worker (`apply_update.ps1`). The worker connects directly to Pink's active process PID (`os.getpid()`) and safely waits (`$proc.WaitForExit(15000)`) until Windows kernel file locks are completely released before performing binary swaps.
- **Eliminated `timeout` Input Redirection Glitch**: Resolved a fatal Windows bug where calling `timeout /t 1` in detached / background updater processes immediately crashed with `ERROR: Input redirection is not supported`, which burned through retries in under 15 milliseconds, failed binary copies, and prematurely erased downloaded update files.
- **Fail-Safe Delay & Batch Fallback**: Added a 600ms Windows file-handle flush delay with safe 30-attempt polling, paired with a resilient fallback batch script using standard socket delay (`ping -n 2 127.0.0.1`) if PowerShell script execution is restricted.
- **UAC Elevation Recovery**: Added automatic elevation recovery (`Start-Process powershell -Verb RunAs`). If Pink is installed in write-protected system directories (such as `C:\Program Files`), the updater prompts for administrative permission instead of silently failing.
- **Safe Download Preservation**: Downloaded binaries are now strictly preserved if file locks or permission issues prevent immediate overwriting, accompanied by a native Windows notification dialog guiding the user to the saved update location.
- **Diagnostic Logging**: Every update execution now writes a clean chronological log to `%TEMP%\yellows_update\update.log` for instant troubleshooting.

### 🌿 Smart Git Source Auto-Updates
- **One-Click Git Pull for Developers & Testers**: Running Pink from Python source in a cloned git repository now detects local repo status. Instead of downloading standalone Windows `.exe` binaries into source directories, Pink offers to pull latest changes automatically via `git pull` and cleanly reboots the pet vessel.
- **Friendly Non-Git Source Guidance**: If running from unzipped source archives without Git, Pink now clearly guides the user on updating or installing the compiled binary rather than failing silently.

### 🎯 Smart Installation-Aware Asset Prioritization
- **Setup vs Portable Hot-Swap Matching**: `UpdateCheckerThread` now inspects the application root directory for Inno Setup uninstaller signatures (`unins*.exe`):
  - **Installed Setup**: Prioritizes `Yellows-Pixel-Buddies-Setup.exe` and passes `/CLOSEAPPLICATIONS` so Windows Start Menu shortcuts and registry entries stay perfectly synchronized.
  - **Portable Executable**: Prioritizes `Yellows-Pixel-Buddies.exe` for instant, seamless in-place hot-swapping without running setup wizards.

### 🛠️ Process Restart & Working Directory Hardening
- **Absolute Script Path Resolution**: Hardened `restart_application()` by resolving `main_script` to an absolute path (`Path(__file__).resolve()`) and guaranteeing `cwd=str(_exe_dir)` is passed to child processes.
- **Eliminated "can't open python ... [Errno 2]"**: Fixed working-directory drift during restarts and startup command execution that caused Python to lose track of `yellows_pixel_buddies.py`.

---

## 📦 Installation & Updating
- **Windows Setup Installer**: Download and run `Yellows-Pixel-Buddies-Setup.exe` from GitHub Releases.
- **Portable Version**: Download `Yellows-Pixel-Buddies.exe` and run directly from any folder or USB drive.
- **In-App Updater**: Right-click Pink or use the tray icon and select **Check for Updates 🔄** to update automatically. All memories, facts, and settings in `%APPDATA%\YellowsPixelBuddies\memory` remain 100% safe!

---

# Release Notes - v0.9.8.1 🐾

**Yellow's Pixel Buddies v0.9.8.1** is a focused quality-of-life and stability update. This release enforces single-instance protection with smart desktop summoning (fixing duplicate pet launches), delivers a massive overhaul to interactive companion questions and time-aware care routines, eliminates repetitive song nagging, and hardens the auto-update engine with automated retry file-swap logic.

---

## 🌟 What's New & Major Highlights

### 🛡️ Single-Instance Enforcement & Desktop Summoning
- **Zero Multiple Buddies**: Fixed a bug where launching the application shortcut multiple times or running autostart concurrently spawned duplicate walking pets, stacked tray icons, and conflicting audio engines.
- **Kernel-Level Named Mutex**: Implemented Windows session-scoped mutex locking (`Local\YellowsPixelBuddies_<username>_SingleInstance`) that prevents duplicate processes with zero overhead and automatic OS-level cleanup if terminated unexpectedly.
- **Instant IPC Pet Summoning**: Launching a duplicate instance communicates with your existing companion via Qt local socket IPC and terminates cleanly in milliseconds.
- **Smart Focus & Reaction**: When a duplicate launch is detected, your existing Pink companion:
  - Automatically restores to the taskbar if hidden in the system tray.
  - Sinks/rises out of peek mode if currently hidden.
  - Brings her window topmost and front-and-center.
  - Plays a cheerful `peace_sign` pose and announces her presence: `"* Hey! I'm already right here, captain! Were you looking for me? :D"`.
  - Brings the Sanctuary Shop window to the front if currently open.
- **Seamless `/restart` & `/reboot` Support**: Added `--restarting` handoff delay coordination so chat restart commands smoothly restart the vessel without being blocked by the single-instance lock.

### 💬 Interactive Questions & Casual Care Overhaul
- **Anti-Fixation Music Tracking**: Pink now actively tracks song titles commented on, eliminating repetitive and nagging question loops whenever you listen to background music or stream tracks.
- **Time-Aware Casual Care**: Integrated natural, time-contextual dialogue based on local system time without feeling preachy or robotic:
  - 🍱 **Lunch Check-ins** (~11:30–13:30): Casual reminders to grab food and take a breather.
  - 🍲 **Dinner Check-ins** (~18:00–20:30): Evening meal banter and winding-down thoughts.
  - 💧 **Hydration Checks**: Natural check-ins during long desk sessions.
  - 🌙 **Late-Night Rest**: Gentle prompts when burning the midnight oil.
- **Authentic Deltarune Lore & True Divergence**: Overhauled `QUESTION_ITEMS` to replace generic health nags and formulaic "slacking" templates with in-character questions, dark world lore, and true 3-choice emotional divergence (no repetitive dismissal starters like `* Hmph!`).
- **Memory & Care Tracking**: Acknowledged hydration and meal responses are recorded directly into persistent memory context and fact sheets.

### 🔄 Hardened Auto-Updater & Standalone EXE Hot-Swap
- **Standalone EXE Swapping**: Prioritizes direct standalone `.exe` hot-swapping for portable installations and manual directories.
- **Automated Self-Cleaning Retry Worker**: Generates a temporary `update_helper.bat` that safely polls and retries file replacement up to 30 times (~15 seconds) while Windows releases process locks on the closing application, eliminating file-in-use errors.
- **Instant Cleanup**: The batch script automatically launches the newly updated executable and self-deletes upon completion.

### 📦 Build & Dependency Specifications
- **PyQt5.QtNetwork Integration**: Added `PyQt5.QtNetwork` to PyInstaller's `hiddenimports` in `Yellows-Pixel-Buddies.spec` to guarantee IPC networking libraries are bundled into standalone binaries.

---

## 🛠️ Bug Fixes & Refinements
- **Multiple Instances Resolved**: Only one instance of Pixel Buddies can run at any time per Windows user session.
- **Clean IPC Connection Teardown**: Handled connection state verification on local socket reads to eliminate device-not-open socket warnings.
- **Question Fallbacks**: Fixed static question selection fallbacks so unexpected API errors always smoothly default to rich multi-choice dialogue rather than blank bubbles.

---

## 📦 Installation & Updating
- **Windows Setup Installer**: Download and run `Yellows-Pixel-Buddies-Setup.exe` from GitHub Releases.
- **Portable Version**: Download `Yellows-Pixel-Buddies.exe` and run directly from any folder or USB drive.
- **In-App Updater**: Right-click Pink or use the tray icon and select **Check for Updates 🔄** to update automatically. All memory files, notes, and wallet data are preserved in `%APPDATA%\YellowsPixelBuddies\memory`.

---

# Release Notes - v0.9.8 🐾

**Yellow's Pixel Buddies v0.9.8** brings a massive visual and UX overhaul to the **Dark World Sanctuary Shop**, directly aligning all menus and interaction boxes with authentic Deltarune/Undertale references. This update also adds a full-width scrollable note inspector with in-game editing, restores comfortable desktop speech bubble proportions, introduces dynamic cursor feedback, refines memory addressing, and resolves runaway animations and alarm loops.

---

## 🌟 What's New & Major Highlights

### 🏪 Complete Sanctuary Shop Layout Overhaul
The in-game sanctuary shop has been completely redesigned to faithfully mirror authentic *DELTARUNE* shop HUD layouts:
- **Main Menu (`menu.png`)**: Split 2-box HUD with dynamic shopkeeper dialogue on the left, primary navigation options (`CHARACTER`, `TASKS & ALARMS`, `TALK`, `CONFIG & SETTINGS`, `EXIT`) on the right, animated red soul heart cursor, and wallet amount (`P$ 000015`) at the bottom-right.
- **Submenus (`sub menu.png`)**: Wardrobe, Tasks & Alarms, Settings, Companion Toggles, and Facts Sheet now consistently use the authentic 2-box layout:
  - **Left Box**: Vertical options list with line height and spacing matching the main menu, complete with red soul heart selection cursor.
  - **Right Box**: Dynamic shopkeeper dialogue preview, detailed descriptions, and wallet balance.
  - **No Awkward Top Cards**: Eliminated out-of-place 3-box HUD elements and misplaced cards across all submenus.
- **Draggable Shop Window**: Click and drag any empty background area in the shop to move the window anywhere on your screen. The mouse pointer dynamically changes to open/closed grab hands.
- **Serious Shopkeeper Mode**: When the sanctuary shop is opened, Pink enters a serious, composed state—idle explosions, drop-tongue reactions, and glitch animations are suppressed while inside.

### 📝 Scrollable & Editable Note Inspector ("Note enter is like talk")
- **Full-Width Inspection Box (`talk.png`)**: Opening any fact note now displays inside an authentic full-width dialogue box across the bottom of the screen. Notes text is no longer drawn at the top-left card area.
- **Scrollable Long Notes**: Note text is cleanly line-wrapped across 540 pixels. Long notes can now be scrolled using the **mouse wheel**, **Up/Down arrow keys**, or by clicking the `▲` / `▼` indicators.
- **In-Game Note Editing**: Added an interactive `[ EDIT NOTE ]` choice button alongside `[ DELETE NOTE ]` and `[ BACK ]`. Selecting Edit launches an in-game input bar pre-filled with the current note text, instantly persisting changes to `%APPDATA%\YellowsPixelBuddies\memory\facts.json`.

### 👗 Character Wardrobe & Equipment
- **Equipped Companion Status**: The wardrobe menu clearly displays `Pink (Equipped)`.
- **Clean Coming Soon Styling**: Unreleased character slots are neatly labeled `(COMING SOON)` in dark white (`#888888`), preventing clutter and placeholders.

### 💬 Desktop Speech Bubble Polish
- **Authentic Medium Proportions**: Restored comfortable, readable Undertale/Deltarune proportions for desktop bubbles (`DIALOGUE_BOX_SCALE = 1.5`, `DIALOGUE_FONT_PIXEL_SIZE = 14`, `DIALOGUE_MAX_WIDTH_PX = 260`)—neither too large nor too small.
- **Zero Bold Fonts**: All HUD texts and dialogue bubbles strictly use normal weight Determination font for crisp, authentic pixel art typography.
- **Dialogue Hover Pause**: Hovering the cursor over an active speech bubble pauses its auto-dismiss timer so you can read long thoughts without feeling rushed.
- **Speech Category Resolution**: Fixed a category formatting bug in `_say()` that caused sprite actions (like `idle`, `walk`, `dance`, `tongue`) to occasionally output raw text names.

### 🖱️ Dynamic Grab & Interaction Cursors
- **Desktop Companion Cursors**:
  - Hovering over Pink displays an open hand cursor (`Qt.OpenHandCursor`).
  - Dragging Pink displays a closed hand cursor (`Qt.ClosedHandCursor`).
  - Hovering over Pink while she peeks behind the taskbar displays a pointing hand cursor (`Qt.PointingHandCursor`).
  - **Interactive Shop Elements**: Clickable choices, scroll arrows, and dialogue boxes consistently trigger the pointing hand cursor.

### 👤 Memory, Nicknames & Proof of Work
- **Primary Nickname Addressing**: Pink now prioritizes your primary nickname set in `facts.json` across all interactions, while naturally referencing secondary facts from your notes.
- **Nickname Manager**: Quickly change your preferred name directly through sanctuary settings or via the `/name <nickname>` slash command.
- **Proof-of-Work Task Verification**: Completing chores runs an automated check against screen sight logs and recent session memories before awarding Pink Dollars (P$).

### ⏰ Alarms & Timers Maintenance
- **Temporary Maintenance Mode**: Alarms and focus timers have been placed into `(COMING SOON)` maintenance mode while their background engine is re-architected.
- **Eliminated Loops & Sound Hangs**: Completely disabled background ticker loops and audio triggers, preventing runaway alert notifications and freeze bugs.

---

## 🛠️ Bug Fixes & Refinements
- **Explosion Loop Fix**: Fixed an explosion debounce issue that could cause Pink to continuously explode when opening the shop window or upon receiving fast error callbacks.
- **Drop Glitch Fix**: Fixed an animation frame mismatch where Pink would momentarily show a drop-tongue or glitch frame when moved or dragged while in shop mode.
- **Action Callback Error Fix**: Resolved a `TypeError` in action choice callbacks when cancelling or confirming task choices.
- **Canvas Scaling**: Optimized canvas scaling and sprite offsets to prevent top/bottom cropping of shopkeeper art.
