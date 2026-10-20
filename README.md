<div align="center">
  <img src="icon.svg" width="96" height="96" alt="Yellow's Pixel Buddies Icon" />
  <h1>Yellow's Pixel Buddies 🐾</h1>
  <p>An intelligent, animated desktop pet companion that lives, walks, runs, talks, and reacts along your Windows taskbar. Powered by PyQt5 and Google Gemini AI.</p>
  <p>Crafted with ❤️ by <a href="https://github.com/bintangprasetyo95"><strong>bintangprasetyo95</strong></a></p>
</div>

---

## ✨ Features

### 🐾 Windows Taskbar Companion
- **Adaptive Taskbar Awareness**: Automatically docks to the Windows taskbar, walks back and forth, and occasionally sprints (`run_left`, `run_right`) or takes slow wistful strolls (`wistful_walk_left`, `wistful_walk_right`).
- **Edge Safety & Re-compositing**: Smoothly reverses direction at monitor bounds and automatically adapts whenever the taskbar is moved, resized, or auto-hidden.

### 🧠 Gemini AI Desktop Companion & Screen Vision
- **Interactive Chat Bar**: Double-click Pink or select **Talk to Pink 💬** to open a retro Cyber World text prompt.
- **Sassy Tsundere Personality**: Inspired by **Mad Mew Mew** from *DELTARUNE / Undertale*—dramatic, proud, playfully tsundere, but secretly helpful and observant.
- **Screen Vision Awareness (Eye Toggle)**: Click the custom eye toggle icon (`sprites/eye/`) next to the input bar to let Pink take a screenshot of your active desktop. She can critique your code, inspect wallpapers, roast open apps, or comment on your current gaming session.
- **Smart Fallback & Robust Token Ceiling**: Runs by default on fast, high-rate-limit **`gemini-3.5-flash-lite`**, with automatic failover to `gemini-3.1-flash-lite`, `gemini-flash-lite-latest`, and `gemini-3.5-flash`. Configured with thinking-token awareness so dialogue is never truncated mid-sentence.
- **Real-Time Temporal Awareness**: Dynamically injects your current local time and calculated absence duration into the system prompt, allowing Pink to accurately know the time of day, schedule, and precisely how long you have been away from your computer.
- **Explosion VFX & Burnt Error Handling**: If an API error, rate limit (429), or vision glitch occurs, Pink dramatically explodes into a 17-frame foreground pixel explosion (`sprites/explosion/`) and stays soot-covered and burnt (`burnt`).
- **Secret Test Commands**: Type `/error`, `/test-error`, or `test error` into the chat bar to test the error explosion VFX and burnt animation on demand.

### 💾 Persistent Memory & Context
- **Session Logging**: All conversation turns are automatically recorded with status, timestamps, user text, spoken dialogue, and emotion tags in `memory/sessions/session_<timestamp>.json`.
- **Cross-Session Fact Retention**: Pink remembers long-term facts about the user across sessions stored in `memory/facts.json`.
- **30-Day Active Reminders & To-Dos**: Save, edit, or delete temporary reminders stored in `memory/reminders.json`. Pink tracks them in your context and auto-prunes anything older than 30 days. Manage them via chat commands (`/remind`, `/del_reminder`, `/edit_reminder`, `/clear_reminders`, `/reminders`) or visually through the system tray.
- **AI Token Analytics & Quota Tracking**: Ask Pink anytime (`"how much token left"`, `"ai token"`, or `/tokens`) or click **AI Token Usage 📊** in the tray menu. Pink gives an instant in-character report on active context window tokens remaining (out of 1,048,576), last query token breakdown, and today's session usage without consuming extra API calls.
- **In-App Memory Controls**: Open the memory folder, clear current session memory, manage reminders, or check token usage directly through the system tray (**Memory Storage 🧠**).
- **Flexible API Key Storage**: Seamlessly loads your Gemini API key from the environment, `.env` file, `memory/config.json`, or the in-app popup dialog.

### ❓ Interactive DELTARUNE Choice Questions
- **Branching Prompts**: Pink periodically pauses during idle periods to ask interactive questions with clickable choice buttons inside the speech bubble (e.g. asking about taskbar cleanliness, taking breaks, motivation, or gaming habits).
- **In-Character Reactions**: Clicking a choice button triggers a custom response tailored to your answer.

### 👻 Ghost Takeover & Spectral Aura Mode
- **Fury-Fueled Tantrums**: Speaking any line from `GHOST_DIALOGUE_LINES` activates the Ghost Takeover visual effect:
  - Snaps into the `angry` emotion state.
  - Generates a pulsating cyan spectral aura behind her sprite.
  - Adds ghost jitter and floating spectral embers.

### 💣 Jump to Cursor & Cat Bomb Attack Mode
- **Ballistic Cursor Jump**: When the mouse rests idle above her on the screen, Pink ballistically leaps up (`airborne`) to catch the cursor (`hanging`).
- **Cursor Shake-Off**: Quickly shaking your mouse dislodges her grip, causing her to fall back to the taskbar with a cheeky laugh.
- **Cat-Head Bomb Barrage**: While hanging, Pink can throw bouncy cat-head bombs with animated spark fuses. Upon detonating, they trigger screen-wide pixel laser crosses (`BombLaserOverlay`).
- **Configurable Bomb Chance**: Real-time probability slider and a quick 25% default button built directly into the system tray menu.

### 🎵 Windows GSMTC Music & Song Detection
- Detects media playback across Windows (Spotify, YouTube, browser, media players) via the Windows GSMTC API.
- Pink announces the song title and artist when a track starts.
- **Autonomous AI Song Commentary**: Powered by Gemini AI, Pink spontaneously comments on newly played songs. Rather than repeating generic author praises, Pink specifically reacts to the **song title itself**—its theme, drama, wordplay, and vibe (with special Toby Fox lore deja vu when applicable). Can be toggled on/off in the system tray.
- **Normal Song Loading & Thoughtful Pauses**: After announcing a song, Pink enters her signature Undertale-style listening/loading bubble (`* ...`) before delivering commentary.
- **Instant Skip Abort**: Skipping a track immediately stops and aborts the previous song's loading bubble and background query, preventing stale commentary from lagging behind or playing out of sync.
- **Playlist Skip Stress & Confusion Mechanic**: Rapidly skipping songs within 8 seconds stresses Pink out!
  - **Skip 1**: Mild curiosity (`* ...?`).
  - **Skip 2**: Impatient listening (`* ...?! (Wait, make up your mind!)` with her `behind` sprite).
  - **Skip 3+ (Overwhelmed & Dizzy)**: Pink reaches her breaking point—she gets dizzy and confused, screaming in shocked or angry sprites about her spinning cotton head and playlist whiplash while saving Gemini tokens! Continuous playback for $\ge 8$ seconds calms her back down.
- **Smart YouTube Shorts & Reel Filtering**: Automatically filters out YouTube Shorts, short clips, and video reels (duration $\le 60$s from browsers or titles containing `#shorts`/`#reels`/`#tiktok`) so Pink won't spam speech bubbles while you scroll. Can be toggled in the system tray.
- **Short Audio & Minimum Track Duration Filter ($\ge 20$s)**: Automatically ignores any audio clips, sound effects, meme sounds, and tracks shorter than 20 seconds. Also aborts in-flight commentary if playback stops in under 20 seconds so premature skips or stopped sounds never generate unwanted comments.

### 🖥️ Window Switch & Flashbang Reactions
- **Maximized App Startle**: Switching to any maximized window startles Pink (`shocked`, 30s cooldown).
- **Flashbang Reaction**: Switching from a dark workspace to a dominant light/white window crisps her like a flashbang (`burnt`, 5s cooldown).
- Pauses current movement or pauses, plays the reaction, and resumes her schedule cleanly.

### 🐾 Hiding & Cinematic Summoning
- **Hide to Tray 📥**: Completely vanish Pink from the desktop into the system tray via right-click, tray menu, or `/hide_tray`. While hidden, she remains invisible on screen but reads your screen in the background every 5 minutes to keep conversation context and maintain an active session. When you click or double-click the tray icon, she returns to the taskbar with a contextual greeting referencing what she observed while hidden!
- **Ghost Ear Peeking**: While in hide mode, Pink rests invisibly below the taskbar with only her ghost ears peeking out at the bottom-right corner.
- **Hide on Demand**: Right-click Pink or use the tray menu to choose **Hide (Peek Ears) 🐾**—she sprints offscreen to the right and surfaces at the hiding spot.
- **Cinematic Summoning**: Click her peeking ears (or select **Call Pink 🐾** from the tray) to summon her: she floats up as a spectral ghost (`ghost/`), looks around, dashes offscreen, and dramatically pops onto the taskbar in her physical doll body (`shocked`)!

### 🖱️ Interactive Mouse Controls
- **Single Left-click**: Plays a friendly random animation (`peace_sign`, `laughing`, or `shocked`) without speech dialogue.
- **Double Left-click**: Opens the interactive **Chat Input Overlay ("Talk to Pink 💬")**.
- **Left-click + drag**: Pick up and carry Pink around the screen (loops `shocked` while held). Release to watch gravity pull her back to the taskbar.
- **Right-click**: Opens a context menu with **Talk to Pink 💬**, **Ask me something ❓**, **Hide to Tray 📥**, **Hide (Peek Ears) 🐾**, and **Exit**.
- **Sprint to Exit**: Selecting **Exit** triggers a high-speed sprint to the furthest screen edge before cleanly closing the application.

### 🎛️ System Tray & Hidden Icons Control Center
Right-click the tray icon in your Windows notification area (`^`) to:
- **Start with Windows**: Toggle automatic startup via Windows Registry.
- **Call Pink 🐾 / Bring to Taskbar**: Re-summon or reset position.
- **Talk to Pink 💬**: Launch the Gemini chat prompt.
- **Set Gemini API Key 🔑**: Open a secure dialog to update your Gemini API key.
- **Memory Storage 🧠**:
  - **Manage Reminders 📝**: View, add, edit, or delete active 30-day reminders in an interactive desktop window.
  - **Open Memory Folder 📂**: Opens `memory/` in Windows File Explorer.
  - **Clear Current Session 🧹**: Flushes in-memory context and initializes a clean session file.
  - **AI Token Usage 📊**: Pop up a dialogue bubble with live token analytics and context window headroom.
- **Hide to Tray 📥 / Restore Pink from Tray 📤**: Vanish completely into tray with 5-minute background screen reading, or restore to taskbar.
- **Hide (Peek Ears) 🐾**: Send Pink to her peeking spot behind the taskbar.
- **Bomb Attack Mode**: Toggle cursor bomb throws and tune odds with the embedded slider.
- **Dialogue Bubbles**: Toggle speech bubbles on or off in real time.
- **AI Song Commentary 🎵**: Toggle autonomous music track commentary on or off.
- **Filter YouTube Shorts 🔕**: Toggle ignoring YouTube Shorts and short video reels.
- **Exit**: Cleanly terminate the application.

### ⚙️ Transparent, Click-Through & High-DPI Ready
- Clicks on transparent pixels pass straight through to underlying desktop icons, open apps, and taskbar buttons (`CLICK_THROUGH_TRANSPARENT`).
- Scales cleanly across Windows display scaling factors (100%, 125%, 150%, 200%) using nearest-neighbor pixel sampling.

---

## 🚀 Getting Started

### Prerequisites

- **Operating System**: Windows 10 or 11
- **Python**: 3.10 or higher
- **Core Dependencies**: `PyQt5`, `requests`
- *(Optional)* **Windows Media Control**: `winrt-runtime` and `winrt-Windows.Media.Control` (for automatic GSMTC music playback detection)

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/bintangprasetyo95/yellows-pixel-buddies.git
   cd yellows-pixel-buddies
   ```

2. **(Optional) Create and activate a virtual environment**:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install PyQt5 requests
   ```
   *(Optional for song detection)*:
   ```bash
   pip install winrt-runtime winrt-Windows.Media.Control
   ```

4. **Set up your Gemini API Key**:
   - Create a `.env` file in the root directory:
     ```env
     GEMINI_API_KEY="your_google_gemini_api_key_here"
     ```
   - *Alternatively*: Launch the app and enter your key via the tray menu (**Set Gemini API Key 🔑**) or when prompted during your first chat!

5. **Run Yellow's Pixel Buddies**:
   ```bash
   python yellows_pixel_buddies.py
   ```

---

## 📦 Building a Standalone Executable (.exe)

You can compile Yellow's Pixel Buddies into an independent Windows `.exe` using [PyInstaller](https://pyinstaller.org/) so it runs without installing Python.

1. **Install PyInstaller**:
   ```bash
   pip install pyinstaller
   ```

2. **Build using the included `.spec` file**:
   ```bash
   python -m PyInstaller Yellows-Pixel-Buddies.spec
   ```
   The generated executable will be placed in `dist/`:
   ```text
   dist/Yellows-Pixel-Buddies.exe
   ```

3. **Manual PyInstaller Build Command**:
   If building without the `.spec` file, bundle required asset directories:
   ```bash
   python -m PyInstaller --noconsole --onefile --name "Yellows-Pixel-Buddies" --icon "app_icon.ico" --add-data "sprites;sprites" --add-data "fonts;fonts" --add-data "app_icon.ico;." yellows_pixel_buddies.py
   ```

> [!TIP]
> - Memory files (`memory/`) will automatically be created next to your `.exe` or Python script upon first run.
> - If PowerShell returns `The term 'pyinstaller' is not recognized...`, use `python -m PyInstaller` to ensure Python's script directory is invoked.

---

## 🎨 Sprites & Custom Assets

All animations are loaded dynamically from transparent PNGs inside `sprites/`, sorted numerically (`1.png`, `2.png`, `3.png`, ...):

```text
sprites/
├── dialogue_box.png   # DELTARUNE Cyber World speech bubble (108x33 9-patch)
├── eye/               # Vision toggle icons (off.png, on.png)
├── ghost/             # Spectral ghost rising animation
├── explosion/         # 17-frame foreground pixel explosion VFX
├── bomb/              # Cat-head bomb sprites
├── sparks/            # Burning bomb fuse spark frames
├── laser_mid/         # Pulsating laser beam cores
├── laser_extend/      # Laser cross beam tips
├── idle/              # Resting animation (looping)
├── walk_left/         # Walking left
├── walk_right/        # Walking right
├── run_left/          # Sprinting left
├── run_right/         # Sprinting right
├── wistful_walk_left/ # Slow wistful walk left
├── wistful_walk_right/# Slow wistful walk right
├── airborne/          # Ballistic jump towards cursor
├── hanging/           # Hanging from cursor hands
├── throw/             # Cat-head bomb toss pose
├── angry/             # Angry stomping reaction
├── behind/            # Looking behind (5s hold)
├── crying/            # Tearful intro, loop, and exit
├── embarrassed/       # Blushing shy reaction
├── kneeling/          # Kneeling rest pose (10s hold)
├── laughing/          # Joyful laughter
├── overjoyed/         # Delighted bouncing celebration
├── peace_sign/        # Posing peace sign
├── sad/               # Dejected expression
├── shocked/           # Startled / pick-up reaction
├── singing/           # Multi-cycle singing melody
├── tongue/            # Sticking tongue out (1s hold)
├── wistful/           # Pensive wistful expression
└── burnt/             # Crispy burnt doll state
```

### 🔤 Retro Typography
```text
fonts/
└── determination/
    └── determination.ttf   # FontStruction "Determination" (CC BY 3.0)
```

---

## ⚙️ Configuration & Customization

All tunable settings live at the top of [`yellows_pixel_buddies.py`](yellows_pixel_buddies.py) under **`1. CONFIGURATION`**:

### Pixel Art & Dimensions
```python
SPRITE_SIZE = 128                  # On-screen window size (logical pixels)
SMOOTH_SCALING = False             # False = crisp nearest-neighbor, True = smooth
FOOT_PADDING = 0                   # Lowers window so feet touch taskbar top edge
CLICK_THROUGH_TRANSPARENT = True   # Only visible pixels catch mouse clicks
```

### Movement & Speeds
```python
WALK_SPEED_PX_S = 60.0             # Walking speed (pixels/sec)
RUN_SPEED_PX_S = 140.0             # Running speed (pixels/sec)
WISTFUL_WALK_SPEED_PX_S = 30.0     # Slow wistful walk speed (pixels/sec)
GRAVITY_PX_S2 = 2400.0             # Fall acceleration after drop
WALK_MIN_S, WALK_MAX_S = 3.0, 8.0  # Duration range for walking/running
PAUSE_MIN_S, PAUSE_MAX_S = 2.0, 5.0# Duration range for idle rests
RUN_CHANCE = 0.25                  # 25% chance walk becomes a run
WISTFUL_WALK_CHANCE = 0.25         # 25% chance walk becomes a wistful walk
```

### Gemini AI & Model Configuration
```python
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_FALLBACK_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
]
GEMINI_TIMEOUT_S = 35              # Request timeout in seconds (supports vision payloads)
```

### Interactive Dialogue & Questions
```python
DIALOGUE_ENABLED = True            # Enable speech bubbles / dialogue popups
DIALOGUE_QUESTION_CHANCE = 0.25    # 25% chance an idle dialogue is an interactive question
DIALOGUE_QUESTION_COOLDOWN_S = 60.0# Cooldown between interactive question prompts
DIALOGUE_TYPEWRITER_MS = 32        # Typewriter speed (~31 chars/sec)
DIALOGUE_PUNCTUATION_PAUSE_TICKS = 4 # Extra pause ticks on punctuation for retro pacing
```

### Bomb Attacks & Cursor Interaction
```python
HANG_BOMB_DEFAULT_CHANCE_PERCENT = 25  # Default chance to throw a bomb while hanging
HANG_BOMB_COOLDOWN_S = 4.0             # Cooldown between bomb tosses
STILL_JUMP_CHANCE = 0.50               # Chance to jump when cursor stays still
GRAB_RADIUS_PX = 32.0                  # Catch radius to grab the cursor
```

---

## 🛑 How to Exit

- **Right-click** Pink and select **Exit**.
- **Right-click** her icon in the **Hidden icons (`^`)** tray menu and select **Exit**.
- Or press `Ctrl + C` in the terminal running the script.

---

## 🌟 Author & Tribute

<div align="center">
  <a href="https://github.com/bintangprasetyo95">
    <img src="icon.svg" width="64" height="64" alt="bintangprasetyo95 star icon" />
  </a>
  <p>Created with love by <a href="https://github.com/bintangprasetyo95"><strong>@bintangprasetyo95</strong></a></p>
</div>

---

## ⚖️ Disclaimer & Fan-Work Notice

- This is a free, non-commercial fan-made companion.
- Character personality and original sprite art are inspired by **DELTARUNE © Toby Fox**.
- All rights to DELTARUNE belong to Toby Fox and Royal Sciences LLC.
- This project is unofficial and is not affiliated with, endorsed by, or sponsored by Toby Fox.

---

## 📄 License & Credits

- **Source Code**: Licensed under the [MIT License](LICENSE).
- **Sprite Artwork & Characters**: Belong to their respective copyright holders (**DELTARUNE © Toby Fox**) and are not covered under the MIT License.
- **Font Attribution ("Determination")**:
  - **File**: `fonts/determination/determination.ttf`
  - **Author**: [anonymous-1438277 on FontStruct](https://fontstruct.com/fontstructions/show/2368299)
  - **License**: [Creative Commons Attribution 3.0 Unported (CC BY 3.0)](http://creativecommons.org/licenses/by/3.0/)
