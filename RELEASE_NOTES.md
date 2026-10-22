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

---

## 📦 Installation & Updating
- **Windows Setup Installer**: Download and run `Yellows-Pixel-Buddies-Setup.exe` from GitHub Releases.
- **Portable Version**: Download `Yellows-Pixel-Buddies.exe` and run directly from any folder or USB drive.
- **In-App Updater**: Right-click Pink or use the tray icon and select **Check for Updates 🔄** to update automatically. All memory files, notes, and wallet data are preserved in `%APPDATA%\YellowsPixelBuddies\memory`.
