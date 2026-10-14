<div align="center">
  <img src="icon.svg" width="96" height="96" alt="Yellow's Pixel Buddies Icon" />
  <h1>Yellow's Pixel Buddies 🐾</h1>
  <p>An animated desktop pet companion that lives, walks, runs, and reacts along your Windows taskbar. Built in Python with PyQt5.</p>
  <p>Crafted with ❤️ by <a href="https://github.com/bintangprasetyo95"><strong>bintangprasetyo95</strong></a></p>
</div>

---

## ✨ Features

- **Taskbar Companion**: Automatically detects the Windows taskbar, walks back and forth, and occasionally sprints (`run_left`, `run_right`). Automatically turns around at screen edges and follows resized or moved taskbars.
- **Rich Emotion & Animation States**:
  - **Movement**: `walk_left`, `walk_right`, `run_left`, `run_right`, `wistful_walk_left`, `wistful_walk_right`.
  - **Idle & Specials**: `idle`, `laughing`, `singing`, `peace_sign`, `embarrassed`, `overjoyed`, `wistful`, `sad`, `crying`, `tongue`, `kneeling`, `behind`.
  - **Special Events**: Rare `burnt` crisp event during resting pauses.
- **Interactive Mouse Controls**:
  - **Left-click**: Startles the pet (triggers `shocked` reaction).
  - **Multi-click (Anger)**: Clicking 3 times within 2 seconds makes the pet angry (`angry` reaction). Continuing to click or spam her keeps her in the angry state; once clicking stops, she finishes her angry animation loop and calms down to `idle`.
  - **Left-click + drag**: Pick up and carry the pet around your screen (pet loops `shocked` while held). Release to watch gravity pull it back to the taskbar.
  - **Right-click**: Opens a context menu with **Exit**.
- **Interactive Dialogue System**:
  - Authentic DELTARUNE Cyber World speech bubbles rendered with crisp 9-slice scaling.
  - Powered by the iconic **Determination** pixel font with classic typewriter text animations and punctuation micro-pauses.
  - Dynamic in-character dialogue lines for idling, startled reactions (`shocked`), poke annoyances (`angry`), pick-up and drag (`drag`), landing (`land`), flashbang burns (`burnt`), singing, bomb attacks, and random peaceful taskbar thoughts.
  - Left-click speech bubbles to immediately finish typing or dismiss them.
  - Toggleable in real time via the system tray menu (**Dialogue Bubbles**).
- **System Tray & Hidden Icons Menu**: Automatically lives in your Windows taskbar notification area / "Hidden icons" menu (`^`). Right-click the tray icon to toggle **Start with Windows**, **Bring to Taskbar**, **Dialogue Bubbles**, **Bomb Attack Mode** (with real-time probability slider and default 25% button), or cleanly **Exit**.
- **Transparent & Click-Through**: Fully transparent background. Clicks on transparent pixels pass straight through to underlying desktop icons, open apps, and taskbar buttons (`CLICK_THROUGH_TRANSPARENT`).
- **High-DPI Ready**: Scales crisply across different monitor scaling factors (100%, 125%, 150%, 200%) using nearest-neighbor sampling for crisp pixel art.
- **Maximized App & Flashbang Reactions**:
  - Switching to any maximized app startles the pet (`shocked`, 30s cooldown).
  - Switching from a dark app into a dominant white/light maximized app crisps her like a flashbang (`burnt`, no cooldown).
  - Automatically pauses whatever she was doing (walking, running, or resting), plays the reaction, and immediately resumes her prior activity once finished.
- **Modular & Extensible Sprites**:
  - Original core states feature built-in procedural animated placeholders if sprite folders are missing.
  - New emotion states are loaded dynamically whenever PNG files are placed in their folders, with status logged cleanly on startup.

---

## 🚀 Getting Started

### Prerequisites

- **OS**: Windows 10 or 11
- **Python**: 3.10 or higher
- **PyQt5**

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/BintangPrasetyo95/yellows-pixel-buddies.git
   cd yellows-pixel-buddies
   ```

2. (Optional) Create and activate a virtual environment:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install PyQt5
   ```

4. Run Yellow's Pixel Buddies:
   ```bash
   python yellows_pixel_buddies.py
   ```

### 📦 Building a Standalone Executable (.exe)

You can build Yellow's Pixel Buddies into an independent Windows `.exe` using [PyInstaller](https://pyinstaller.org/) so it can run without installing Python or opening a terminal.

1. **Install PyInstaller**:
   ```bash
   pip install pyinstaller
   ```

2. **Build the executable**:

   - **Option A: Self-contained single file (Sprites & fonts bundled inside)**  
     Produces a single portable executable with all sprites, fonts, and icon embedded:
     ```bash
     python -m PyInstaller --noconsole --onefile --name "Yellows-Pixel-Buddies" --icon "app_icon.ico" --add-data "sprites;sprites" --add-data "fonts;fonts" --add-data "app_icon.ico;." yellows_pixel_buddies.py
     ```
     The finished `.exe` will be located in the `dist/` directory:
     ```text
     dist/Yellows-Pixel-Buddies.exe
     ```

   - **Option B: Moddable `.exe` (External `sprites/` and `fonts/` folders)**  
     If you want to easily customize or drop new PNGs or fonts without recompiling:
     ```bash
     python -m PyInstaller --noconsole --onefile --name "Yellows-Pixel-Buddies" --icon "app_icon.ico" yellows_pixel_buddies.py
     ```
     After building, copy the `sprites/` and `fonts/` folders, and `app_icon.ico` directly into `dist/` next to `Yellows-Pixel-Buddies.exe`:
     ```text
     dist/
     ├── Yellows-Pixel-Buddies.exe
     ├── app_icon.ico
     ├── fonts/
     └── sprites/
     ```

> [!TIP]
> - **Fast Rebuilds with `.spec`**: Once built, a `Yellows-Pixel-Buddies.spec` file is generated. You can quickly rebuild anytime without typing all flags again:
>   ```bash
>   python -m PyInstaller Yellows-Pixel-Buddies.spec
>   ```
> - **Command Not Recognized Fix**: If PowerShell gives `The term 'pyinstaller' is not recognized...`, use `python -m PyInstaller` instead of `pyinstaller`. This happens when Python's `Scripts` directory (especially with Microsoft Store Python installations) is not added to your system `PATH`.
> - `--noconsole` (or `-w`): Runs silently in the background without popping up a black console window.
> - `--onefile` (or `-F`): Packages Python and PyQt5 runtime into a single executable file.
> - `--icon "app_icon.ico"`: Sets the custom pixel buddy icon on the executable.

---

## 🎨 Sprites & Custom Animations

Place transparent `.png` files inside each respective state folder under `sprites/`. Frames should be named numerically: `1.png`, `2.png`, `3.png`, etc.

```text
sprites/
├── dialogue_box.png   # DELTARUNE Cyber World speech bubble (108x33 9-patch)
├── idle/          # Resting animation (looping)
├── walk_left/     # Walking left
├── walk_right/    # Walking right
├── run_left/      # Fast running left
├── run_right/     # Fast running right
├── angry/         # Triggered by rapid left-clicks (3 clicks within 2s)
├── behind/        # Looking behind (held for 5s)
├── crying/        # Tearful sadness (intro in frames 1-2, loops frames 3 & 4, outro frame 5)
├── embarrassed/   # Blushing shy reaction
├── kneeling/      # Kneeling resting pose (held for 10s)
├── laughing/      # Joyful laughter
├── overjoyed/     # Delighted bouncing celebration
├── peace_sign/    # Poses and holds peace sign
├── sad/           # Dejected expression
├── shocked/       # Played on left-click, while dragged, or on maximized app switch
├── singing/       # Multi-cycle singing melody
├── tongue/        # Sticking tongue out (held for 1s)
├── wistful/       # Pensive expression and slow wistful walk
└── burnt/         # Rare special event or flashbang reaction (sooty crisp)
```

### 🔤 Fonts & Dialogue Typography

Custom fonts for retro text rendering are located under `fonts/`:

```text
fonts/
└── determination/
    └── determination.ttf   # FontStruction "Determination" (CC BY 3.0)
```

> [!TIP]
> - **Walk Mirroring**: If you only have right-facing sprites for walking, set `MIRROR_WALK_RIGHT_FOR_LEFT = True` in `yellows_pixel_buddies.py` to automatically mirror `walk_right`.
> - **Run Mirroring**: Similarly, set `MIRROR_RUN_RIGHT_FOR_LEFT = True` to automatically mirror `run_right` for `run_left`.

---

## ⚙️ Configuration & Customization

All tunable settings live at the top of [`yellows_pixel_buddies.py`](yellows_pixel_buddies.py) under **`1. CONFIGURATION`**:

### Pixel Art & Sharpness
```python
SPRITE_SIZE = 128                  # On-screen window size (logical pixels)
SMOOTH_SCALING = False             # False = crisp nearest-neighbor (pixel art), True = smooth
FOOT_PADDING = 0                   # Lowers window so feet touch the taskbar top edge
CLICK_THROUGH_TRANSPARENT = True   # Only visible pixels catch mouse clicks
```

### Animation & Movement Speed
```python
ANIM_INTERVAL_MS = 180             # Base frame duration in ms (~5.5 FPS)
WISTFUL_FRAME_INTERVAL_MS = 500    # Slow wistful walk frame duration (~2.0 FPS)
FRAME_INTERVAL_MS = {              # Per-state frame interval overrides
    "run_left": 120,
    "run_right": 120,
    "wistful_walk_left": WISTFUL_FRAME_INTERVAL_MS,
    "wistful_walk_right": WISTFUL_FRAME_INTERVAL_MS,
}
MOVE_INTERVAL_MS = 22              # Movement update rate (~45 FPS)
WALK_SPEED_PX_S = 60.0             # Walking speed (pixels/sec)
RUN_SPEED_PX_S = 140.0             # Running speed (pixels/sec)
WISTFUL_WALK_SPEED_PX_S = 30.0     # Slow wistful walk speed (pixels/sec)
GRAVITY_PX_S2 = 2400.0             # Fall acceleration after drop
```

### Behavioral Timing & Odds
```python
WALK_MIN_S, WALK_MAX_S = 3.0, 8.0     # Duration range for walking/running
PAUSE_MIN_S, PAUSE_MAX_S = 2.0, 5.0   # Duration range for idle rests
RUN_CHANCE = 0.25                     # 25% chance that a walk becomes a run
WISTFUL_WALK_CHANCE = 0.25            # 25% chance that a walk becomes a slow wistful stroll
SPECIAL_CHANCE = 0.5                  # 50% chance a rest triggers a special animation
BURNT_CHANCE = 0.03                   # 3% chance a rest triggers the rare 'burnt' event
```

### Special Reactions, Holds & Repeats
```python
# Relative weights when rolling a random special animation
SPECIAL_WEIGHTS = {
    "laughing": 3, "shocked": 2, "singing": 2, "peace_sign": 3,
    "embarrassed": 2, "overjoyed": 2, "wistful": 2, "sad": 1,
    "crying": 1, "tongue": 2, "kneeling": 2, "behind": 2,
}

# Milliseconds to freeze on the final frame of pose animations
LAST_FRAME_HOLD_MS = {
    "burnt": 2500,
    "peace_sign": 1000,
    "sad": 2000,
    "tongue": 1000,     # Hold tongue for 1000 ms
    "kneeling": 10000,  # Hold kneeling for 10000 ms (10 s)
    "behind": 5000,     # Hold looking behind for 5000 ms (5 s)
}

# Sub-frame loops for states with an intro (1-based frame numbers: 1.png -> 1)
FRAME_SUB_LOOPS = {
    "crying": (3, 4, 4),   # Plays frames 1-2 once, loops frames 3 & 4 four times, then exits via frame 5
}

# Number of full animation cycles before returning to idle
SPECIAL_REPEAT_COUNT = {
    "singing": 2,
    "laughing": 6,
    "angry": 6,
}
```

### Mouse Interaction Tuning
```python
CLICK_ANGRY_COUNT = 3         # Number of left-clicks needed...
CLICK_ANGRY_WINDOW_S = 2.0    # ...within this many seconds to trigger 'angry'
```

### Window Switch & Flashbang Reactions
```python
REACT_ON_MAXIMIZED_APP = True      # React when switching to a maximized app
REACT_POLL_INTERVAL_MS = 200       # Check active window every 200 ms
DARK_LUMINANCE_THRESHOLD = 85.0    # Screen brightness <= 85 is "dark"
LIGHT_LUMINANCE_THRESHOLD = 160.0  # Screen brightness >= 160 is "dominant white/light"
WINDOW_SWITCH_SETTLE_MS = 120      # Wait 120 ms for window to composite before sampling
SWITCH_SHOCK_COOLDOWN_S = 30.0     # Cooldown in seconds for shock
SWITCH_BURNT_COOLDOWN_S = 5.0      # Cooldown in seconds for flashbang burnt (half of original 10s shock cooldown)
```

### Dialogue & Speech Bubbles
```python
DIALOGUE_ENABLED = True               # Enable speech bubbles / dialogue popups
DIALOGUE_CHANCE_ON_PAUSE = 0.25       # 25% chance to speak a random thought during a normal rest pause
DIALOGUE_TYPEWRITER_MS = 32           # Milliseconds per character during typewriter effect (~31 chars/sec)
DIALOGUE_HOLD_MIN_S = 3.0             # Minimum seconds to keep dialogue visible after typing completes
DIALOGUE_HOLD_PER_CHAR_S = 0.04       # Additional seconds to linger per character (e.g. 50 chars = +2.0s)
DIALOGUE_CLICK_TO_DISMISS = True      # Left-clicking the dialogue box completes typing or closes it
DIALOGUE_BOX_SCALE = 1.5              # Pixel scale multiplier for the dialogue box (1.5 = compact medium scale)
DIALOGUE_FONT_PIXEL_SIZE = 14         # Pixel font size for Determination text
DIALOGUE_PUNCTUATION_PAUSE_TICKS = 4  # Extra pause ticks on punctuation for authentic retro dialogue pacing
DIALOGUE_MAX_WIDTH_PX = 260           # Maximum inner text wrapping width in pixels
```

---

## 🛑 How to Exit

- **Right-click** on the pet and select **Exit**.
- **Right-click** the icon in your taskbar's **Hidden icons (`^`)** menu and select **Exit**.
- Or terminate the process in your terminal with `Ctrl + C`.

---

## 🌟 Author & Tribute

<div align="center">
  <a href="https://github.com/bintangprasetyo95">
    <img src="icon.svg" width="64" height="64" alt="bintangprasetyo95 star icon" />
  </a>
  <p>Created by <a href="https://github.com/bintangprasetyo95"><strong>@bintangprasetyo95</strong></a></p>
</div>

---

## ⚖️ Disclaimer & Fan-Work Notice

- This is a free, non-commercial fan-made companion.
- Character designs and original sprite art are based on **DELTARUNE © Toby Fox**.
- All rights to DELTARUNE belong to Toby Fox and the DELTARUNE development team.
- This project is unofficial and is not affiliated with, endorsed by, or sponsored by Toby Fox or Royal Sciences LLC.

---

## 📄 License & Credits

- **Source Code**: Licensed under the [MIT License](LICENSE).
- **Sprite Artwork & Characters**: Belong to their respective copyright holders (**DELTARUNE © Toby Fox**) and are not covered under the MIT License.
- **Font Attribution ("Determination")**:
  - **File**: `fonts/determination/determination.ttf`
  - **Author**: [anonymous-1438277 on FontStruct](https://fontstruct.com/fontstructions/show/2368299)
  - **License**: [Creative Commons Attribution 3.0 Unported (CC BY 3.0)](http://creativecommons.org/licenses/by/3.0/)
  - Free to share and adapt with appropriate attribution (detailed in [LICENSE](LICENSE)).



