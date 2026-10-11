<div align="center">
  <img src="icon.svg" width="96" height="96" alt="Desktop Pet Icon" />
  <h1>Desktop Pet 🐾</h1>
  <p>An animated desktop pet companion that lives and walks along your Windows taskbar. Built in Python with PyQt5.</p>
  <p>Crafted with ❤️ by <a href="https://github.com/bintangprasetyo95"><strong>bintangprasetyo95</strong></a></p>
</div>

---

## ✨ Features

- **Taskbar Companion**: Automatically detects the Windows taskbar and walks back and forth, turning around at screen edges.
- **Interactive Mouse Controls**:
  - **Left-click**: Startles the pet (triggers `shocked` reaction).
  - **Left-click + drag**: Pick up and move the pet around your screen. Release to watch gravity pull it back to the taskbar.
  - **Right-click**: Opens a context menu with **Exit**.
- **Transparent & Click-Through**: Fully transparent background. Clicks on transparent pixels pass straight through to whatever is underneath (taskbar icons, open apps, or desktop).
- **High-DPI Ready**: Scales crisply across different monitor scaling factors (100%, 125%, 150%, 200%).
- **Fallback Placeholders**: If any sprite folder is empty or missing, cute built-in procedural animations are generated so the pet always runs immediately.

---

## 🚀 Getting Started

### Prerequisites

- **OS**: Windows 10 or 11
- **Python**: 3.10 or higher
- **PyQt5**

### Installation

1. Clone or download the repository:
   ```bash
   git clone https://github.com/your-username/desktop_pet.git
   cd desktop_pet
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

4. Run the desktop pet:
   ```bash
   python desktop_pet.py
   ```

---

## 🎨 Adding Custom Sprites

Place transparent `.png` files inside each respective state folder under `sprites/`. Frames should be named numerically: `1.png`, `2.png`, `3.png`, etc.

```text
sprites/
├── idle/          # Default resting animation
├── walk_left/     # Walking left
├── walk_right/    # Walking right
├── laughing/      # Special reaction
├── shocked/       # Played when clicked or picked up
├── singing/       # Special reaction
├── peace_sign/    # Poses and holds peace sign
└── burnt/         # Rare special event
```

> [!TIP]
> If you don't have separate sprites for `walk_left`, set `MIRROR_WALK_RIGHT_FOR_LEFT = True` in `desktop_pet.py` to automatically mirror `walk_right`!

---

## ⚙️ Configuration & Customization

All tunable settings live at the top of [`desktop_pet.py`](desktop_pet.py) under **`1. CONFIGURATION`**:

### Pixel Art & Sharpness
```python
SPRITE_SIZE = 128          # On-screen window size (logical pixels)
SMOOTH_SCALING = False     # False = crisp nearest-neighbor (pixel art), True = smooth
```

### Animation & Movement Speed
```python
ANIM_INTERVAL_MS = 100     # Frame duration in ms (100 ms ≈ 10 FPS; lower = faster)
WALK_SPEED_PX_S = 60.0     # Horizontal walking speed (pixels per second)
```

### Pose Holds & Loop Counts
```python
# Hold the last frame for pose-style animations (in milliseconds)
LAST_FRAME_HOLD_MS = {
    "burnt": 2500,
    "peace_sign": 2000,
}

# Number of full animation cycles before returning to idle
SPECIAL_REPEAT_COUNT = {
    "singing": 4,
}
```

### Positioning & Click Behavior
```python
FOOT_PADDING = 0                 # Lowers window so feet touch the taskbar top edge
CLICK_THROUGH_TRANSPARENT = True # Only visible pixels catch mouse clicks
```

---

## 🛑 How to Exit

- **Right-click** on the pet and select **Exit**.
- Or terminate the process in your terminal with `Ctrl + C`.

---

## 🌟 Author & Tribute

<div align="center">
  <a href="https://github.com/bintangprasetyo95">
    <img src="icon.svg" width="64" height="64" alt="bintangprasetyo95 star icon" />
  </a>
  <p>Created by <a href="https://github.com/bintangprasetyo95"><strong>@bintangprasetyo95</strong></a></p>
</div>

