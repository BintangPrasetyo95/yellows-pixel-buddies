#!/usr/bin/env python3
"""
desktop_pet.py - a Shimeji-style desktop pet that walks along the Windows taskbar.

Platform     : Windows 10 / 11
Python       : 3.10+
Dependencies : PyQt5            ->  pip install PyQt5

Sprites (next to this script)
-----------------------------
    sprites/<state>/1.png, 2.png, 3.png, ...     transparent PNGs, sorted numerically

    original states : idle, walk_left, walk_right, laughing, shocked, singing,
                      peace_sign, burnt
        A missing / empty folder is replaced by a generated placeholder animation,
        so the script always runs.
    new states      : run_left, run_right                          (movement, looping)
                      embarrassed, overjoyed, wistful, sad,
                      crying                                       (random specials)
                      angry                                        (triggered reaction)
        A missing / empty folder means the state is never used (no placeholder), so
        sprites can be added one folder at a time. One INFO line at startup lists
        which new states were found and which were skipped.

Behaviour
---------
    WALK  (3-8 s, one direction, turns around at the screen edges, never leaves it;
           each walk is a faster run instead with RUN_CHANCE)
      -> PAUSE (2-5 s, idle; with some probability one special animation plays)
      -> WALK ...
    Specials are picked by weight (SPECIAL_WEIGHTS), never the same one twice in a row.
    Very rarely the pause contains "burnt" instead of a normal special animation.

    Left-click  : the pet is startled (plays "shocked")
                  3 clicks within 2 s: the pet gets angry (plays "angry")
    Left-drag   : pick the pet up; when dropped it falls back onto the taskbar
    Right-click : context menu with "Exit"
"""

import logging
import math
import random
import re
import signal
import sys
import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from PyQt5.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QRegion
from PyQt5.QtWidgets import QApplication, QMenu, QWidget


# =============================================================================
#  1. CONFIGURATION - every tunable value lives here
# =============================================================================

# --- Sprites -----------------------------------------------------------------
SPRITES_DIR = Path(__file__).resolve().parent / "sprites"   # sprites/<state>/N.png

# On-screen size in *logical* pixels. The window is exactly SPRITE_SIZE x SPRITE_SIZE.
# PNGs of any size are scaled to fit (aspect ratio kept, anchored bottom-centre).
# Tip: author PNGs at 2x (e.g. 256 px) so they stay crisp on high-DPI screens.
SPRITE_SIZE = 128

SMOOTH_SCALING = False      # False = nearest-neighbour scaling (better for pixel art)

# Transparent pixels *under the feet* inside your PNGs. The window is lowered by this
# many pixels so the visible feet (not the PNG edge) touch the top of the taskbar.
FOOT_PADDING = 0

# False: walk_left uses its own folder (sprites/walk_left).
# True : ignore that folder and use a horizontally mirrored copy of walk_right.
MIRROR_WALK_RIGHT_FOR_LEFT = False

# Same for running: True = run_left is a horizontally mirrored copy of run_right.
MIRROR_RUN_RIGHT_FOR_LEFT = False

# True : clicks on fully transparent pixels pass through to whatever is underneath
#        (taskbar buttons, desktop icons...). Only the visible pet catches clicks.
# False: the whole SPRITE_SIZE square catches clicks.
CLICK_THROUGH_TRANSPARENT = True

PLACEHOLDER_FRAME_COUNT = 10   # frames generated for each state with no sprite files

# --- Timing ------------------------------------------------------------------
ANIM_INTERVAL_MS = 180            # sprite frame advance   (~5.5 FPS)
FRAME_INTERVAL_MS = {
    # per-state frame advance in ms; overrides ANIM_INTERVAL_MS for that state only
    "run_left": 120, "run_right": 120,
    # "idle": 250,
    # "laughing": 100,
}
MOVE_INTERVAL_MS = 22             # movement update        (~45 FPS)
WALK_MIN_S, WALK_MAX_S = 3.0, 8.0     # one walk lasts a random time in this range
PAUSE_MIN_S, PAUSE_MAX_S = 2.0, 5.0   # one pause lasts a random time in this range
WALK_SPEED_PX_S = 60.0            # walking speed, logical px per second
RUN_SPEED_PX_S = 140.0            # running speed, logical px per second
GRAVITY_PX_S2 = 2400.0            # fall acceleration after the pet is dropped
MAX_DT_S = 0.1                    # clamp one movement step (e.g. after the PC wakes from sleep)

# --- Behaviour ---------------------------------------------------------------
SPECIAL_CHANCE = 0.5              # chance that a pause contains one special animation
BURNT_CHANCE = 0.03               # RARE: chance per pause that the pet is "burnt" instead
SPECIAL_WEIGHTS = {
    # relative odds of each special / looping rest when one is rolled (never the same twice in a row)
    "laughing": 3, "shocked": 2, "singing": 2, "peace_sign": 3,
    "embarrassed": 2, "overjoyed": 2, "wistful": 2, "sad": 1,
    "crying": 1,
}
RUN_CHANCE = 0.25                 # chance that a new walk is a run instead
CLICK_ANGRY_COUNT = 3             # this many left-clicks ...
CLICK_ANGRY_WINDOW_S = 2.0        # ... within this many seconds make the pet angry
LAST_FRAME_HOLD_MS = {
    # one-shots that freeze on their last frame for a while
    "burnt": 2500,
    "peace_sign": 1000,
    "crying": 1500,
}
SPECIAL_REPEAT_COUNT = {
    # number of full animation cycles for one-shot specials
    "singing": 4
}
AFTER_SPECIAL_REST_MS = 1000        # idle time after a special that outlasted its pause, before walking on

# --- Animation states --------------------------------------------------------
LOOPING_STATES = ("idle", "walk_left", "walk_right", "run_left", "run_right")   # repeat forever
LOOPING_REST_STATES = ()                  # loops for the whole pause; picked like a special
SPECIAL_STATES = ("laughing", "shocked", "singing", "peace_sign",
                  "embarrassed", "overjoyed", "wistful", "sad",
                  "crying")                                          # one-shot -> idle
REACTION_STATES = ("angry",)              # one-shot -> idle; triggered, never random
BURNT_STATE = "burnt"                                                # one-shot (+hold) -> idle
ALL_STATES = (LOOPING_STATES + LOOPING_REST_STATES + SPECIAL_STATES + REACTION_STATES
              + (BURNT_STATE,))

# The original states always work (placeholder fallback). Every other ("new") state is only
# used when its sprites/<state>/ folder holds real PNGs - see SpriteBank.has_real_sprites().
ORIGINAL_STATES = ("idle", "walk_left", "walk_right", "laughing", "shocked", "singing",
                   "peace_sign", "burnt")
NEW_STATES = tuple(s for s in ALL_STATES if s not in ORIGINAL_STATES)

# Signed horizontal speed (logical px per second) of every moving state; negative = leftwards.
MOVE_VELOCITY_PX_S = {
    "walk_left": -WALK_SPEED_PX_S, "walk_right": WALK_SPEED_PX_S,
    "run_left": -RUN_SPEED_PX_S, "run_right": RUN_SPEED_PX_S,
}

# Body colour of the generated placeholder for each state.
PLACEHOLDER_COLORS = {
    "idle": "#7FB3D5", "walk_left": "#82E0AA", "walk_right": "#58D68D",
    "laughing": "#F7DC6F", "shocked": "#F1948A", "singing": "#BB8FCE",
    "peace_sign": "#F8C471", "burnt": "#4D5656",
    "run_left": "#E59866", "run_right": "#CA6F1E",
    "embarrassed": "#FF9FCB", "overjoyed": "#D4E157", "wistful": "#9FA8DA",
    "sad": "#4A78B5", "crying": "#00BCD4",
    "angry": "#E74C3C",
}

log = logging.getLogger("desktop_pet")


# =============================================================================
#  2. SMALL HELPERS
# =============================================================================

def natural_sort_key(path: Path) -> list:
    """Sort key giving numeric order: 1, 2, ..., 9, 10 (a plain sort gives 1, 10, 2)."""
    # re.split with a capture group alternates text / number / text ...
    return [int(tok) if tok.isdigit() else tok.lower() for tok in re.split(r"(\d+)", path.stem)]


def list_png_files(folder: Path) -> list[Path]:
    """All *.png files in `folder` (case-insensitive), numerically sorted. [] if missing."""
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".png"]
    return sorted(files, key=natural_sort_key)


def random_ms(lo_s: float, hi_s: float) -> int:
    """Random duration between lo_s and hi_s seconds, returned in milliseconds."""
    return int(random.uniform(lo_s, hi_s) * 1000)


def configure_high_dpi() -> None:
    """Enable crisp rendering on scaled displays. MUST run before QApplication is created."""
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)   # logical px != device px
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)      # honour pixmap device ratios
    # Qt >= 5.14: keep fractional scale factors (125 %, 150 %) instead of rounding them to 1/2.
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except AttributeError:
        pass   # older PyQt5: integer scaling only, still works


# =============================================================================
#  3. SPRITES
# =============================================================================

def make_placeholder_frames(state: str) -> list[QImage]:
    """Draw a small 'breathing' blob labelled with the state name.

    Used for any state whose sprite folder is missing or contains no readable PNG.
    """
    size = SPRITE_SIZE * 2   # render at 2x so the placeholder stays sharp on high-DPI screens
    base = QColor(PLACEHOLDER_COLORS.get(state, "#AAB7B8"))
    label_color = QColor("white") if base.lightness() < 110 else QColor("#1B2631")
    # Pupils look the way the pet walks, so the placeholder also shows its direction.
    pupil_dx = {"walk_left": -0.025, "walk_right": 0.025,
                "run_left": -0.025, "run_right": 0.025}.get(state, 0.0) * size

    frames = []
    for i in range(PLACEHOLDER_FRAME_COUNT):
        img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        # Breathing: the top of the body moves, the bottom (the "feet") stays on the ground.
        bob = math.sin(2 * math.pi * i / PLACEHOLDER_FRAME_COUNT) * size * 0.025
        top, bottom = size * 0.20 + bob, size * 0.98
        body = QRectF(size * 0.18, top, size * 0.64, bottom - top)
        p.setPen(QPen(base.darker(160), size * 0.016))
        p.setBrush(base)
        p.drawRoundedRect(body, size * 0.22, size * 0.22)

        # Eyes: white ball + dark pupil.
        eye_y = top + (bottom - top) * 0.27
        p.setPen(Qt.NoPen)
        for eye_x in (0.38, 0.62):
            p.setBrush(Qt.white)
            p.drawEllipse(QPointF(size * eye_x, eye_y), size * 0.065, size * 0.065)
            p.setBrush(QColor("#1B2631"))
            p.drawEllipse(QPointF(size * eye_x + pupil_dx, eye_y), size * 0.032, size * 0.032)

        # State name, so you can see which animation is running.
        font = QFont()
        font.setBold(True)
        font.setPixelSize(int(size * 0.085))
        p.setFont(font)
        p.setPen(label_color)
        label_rect = QRectF(body.left(), top + (bottom - top) * 0.50,
                            body.width(), (bottom - top) * 0.40)
        p.drawText(label_rect, Qt.AlignCenter, state.replace("_", " "))

        p.end()
        frames.append(img)
    return frames


def fit_into_canvas(src: QImage, canvas_px: int) -> QImage:
    """Scale `src` to fit a square transparent canvas, anchored bottom-centre.

    Anchoring at the bottom keeps the feet on the ground even when the sprites
    of different states have different sizes.
    """
    mode = Qt.SmoothTransformation if SMOOTH_SCALING else Qt.FastTransformation
    scaled = src.scaled(canvas_px, canvas_px, Qt.KeepAspectRatio, mode)
    canvas = QImage(canvas_px, canvas_px, QImage.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.drawImage((canvas_px - scaled.width()) // 2, canvas_px - scaled.height(), scaled)
    painter.end()
    return canvas


@dataclass(frozen=True)
class Frame:
    """One ready-to-draw animation frame."""
    pixmap: QPixmap   # rendered at device resolution, tagged with its device-pixel-ratio
    mask: QRegion     # visible area in *logical* px; used for click-through


class SpriteBank:
    """Loads every state's PNGs once and renders them for the current display scale."""

    def __init__(self, sprites_dir: Path, dpr: float) -> None:
        self._sources: dict[str, list[QImage]] = {}
        self._real: set[str] = set()   # states backed by real PNGs (not placeholders)
        for state in ALL_STATES:
            if state == "walk_left" and MIRROR_WALK_RIGHT_FOR_LEFT:
                continue   # derived from walk_right below
            if state == "run_left" and MIRROR_RUN_RIGHT_FOR_LEFT:
                continue   # derived from run_right below
            images = self._load_state(sprites_dir, state)
            if images:
                self._sources[state] = images
        if MIRROR_WALK_RIGHT_FOR_LEFT:
            self._sources["walk_left"] = [img.mirrored(True, False)   # flip horizontally
                                          for img in self._sources["walk_right"]]
        if MIRROR_RUN_RIGHT_FOR_LEFT and "run_right" in self._sources:
            self._sources["run_left"] = [img.mirrored(True, False)    # flip horizontally
                                         for img in self._sources["run_right"]]
            self._real.add("run_left")   # real exactly when run_right is

        # One startup line: which new states have sprites and which will never be used.
        found = [s for s in NEW_STATES if self.has_real_sprites(s)]
        skipped = [s for s in NEW_STATES if s not in found]
        log.info("New states found: %s | skipped (no sprites): %s",
                 ", ".join(found) or "none", ", ".join(skipped) or "none")

        self.frames: dict[str, list[Frame]] = {}
        self.dpr = 0.0
        self.rebuild(dpr)

    def _load_state(self, sprites_dir: Path, state: str) -> list[QImage]:
        """Read sprites/<state>/*.png; original states fall back to a generated placeholder.

        A new state without real PNGs returns [] (no placeholder: it will never be played).
        """
        images = []
        for path in list_png_files(sprites_dir / state):
            img = QImage(str(path))
            if img.isNull():
                log.warning("Cannot read %s - skipped", path)
                continue
            # Premultiplied ARGB is Qt's fastest format for compositing with alpha.
            images.append(img.convertToFormat(QImage.Format_ARGB32_Premultiplied))
        if images:
            self._real.add(state)
        elif state in ORIGINAL_STATES:
            log.warning("No sprites for '%s' in %s - using a generated placeholder",
                        state, sprites_dir / state)
            images = make_placeholder_frames(state)
        return images

    def has_real_sprites(self, state: str) -> bool:
        """True if `state` is drawn from real PNGs (not a placeholder, not missing)."""
        return state in self._real

    def rebuild(self, dpr: float) -> None:
        """(Re)render all frames for a display scale factor (1.0, 1.25, 1.5, 2.0 ...)."""
        physical = max(1, round(SPRITE_SIZE * dpr))   # canvas size in device pixels
        exact_dpr = physical / SPRITE_SIZE            # makes pixmap logical size == SPRITE_SIZE
        for state, images in self._sources.items():
            built = []
            for img in images:
                canvas = fit_into_canvas(img, physical)
                pixmap = QPixmap.fromImage(canvas)
                pixmap.setDevicePixelRatio(exact_dpr)

                # Window masks are expressed in logical px, so derive the mask from a
                # logical-size canvas (identical to `canvas` when dpr == 1).
                logical_canvas = canvas if physical == SPRITE_SIZE \
                    else fit_into_canvas(img, SPRITE_SIZE)
                region = QRegion(QPixmap.fromImage(logical_canvas).mask())  # alpha > 0 pixels
                if region.isEmpty():                 # an empty mask would mean "no mask"
                    region = QRegion(0, 0, 1, 1)
                built.append(Frame(pixmap, region))
            self.frames[state] = built
        self.dpr = dpr


# =============================================================================
#  4. THE PET
# =============================================================================

class Phase(Enum):
    """What the 'brain' is currently doing (independent of which animation is shown)."""
    WALK = auto()    # walking for 3-8 s
    PAUSE = auto()   # resting 2-5 s (maybe with one special animation)
    DRAG = auto()    # being held by the mouse
    FALL = auto()    # dropped, falling back to the taskbar


class DesktopPet(QWidget):
    """A sprite-sized, frameless, translucent, always-on-top window that walks on the taskbar."""

    def __init__(self, bank: SpriteBank) -> None:
        # Qt.Tool                     -> no taskbar button / Alt-Tab entry
        # Qt.FramelessWindowHint      -> no title bar or border
        # Qt.WindowStaysOnTopHint     -> stays above normal windows
        # Qt.WindowDoesNotAcceptFocus -> clicking the pet won't steal focus from your app
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)   # per-pixel transparency
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)   # don't grab focus when shown
        self.setFixedSize(SPRITE_SIZE, SPRITE_SIZE)            # window == one sprite
        self.setCursor(Qt.OpenHandCursor)
        self.setWindowTitle("Desktop Pet")

        self._bank = bank

        # --- animation state ---------------------------------------------------
        self.state = "idle"                  # which sprite folder is being played
        self._frame_idx = 0
        self._loop = True                    # does the current animation repeat?
        self._hold_ticks = 0                 # extra ticks to freeze on the last frame
        self._repeat_count = 0               # extra cycles remaining for repeating specials
        self._pixmap: QPixmap | None = None

        # --- behaviour state ---------------------------------------------------
        self._phase = Phase.PAUSE
        self._pause_elapsed = False          # pause timer fired while a special still plays
        self._last_special: str | None = None   # last randomly rolled special (no repeats)

        # --- position / physics (floats for smooth sub-pixel movement) ---------
        self._x = 0.0
        self._y = 0.0
        self._vy = 0.0                       # vertical speed while falling (px/s)
        self._last_tick = time.perf_counter()

        # --- mouse interaction -------------------------------------------------
        self._press_global: QPoint | None = None   # where the left button went down
        self._grab_offset = QPoint()               # cursor position inside the window
        self._dragging = False
        self._menu_open = False
        self._click_times: list[float] = []        # recent plain left-clicks (for "angry")

        # --- timers ------------------------------------------------------------
        self._anim_timer = QTimer(self)            # ~5.5 FPS: next sprite frame
        self._anim_timer.setInterval(ANIM_INTERVAL_MS)
        self._anim_timer.timeout.connect(self._advance_frame)

        self._move_timer = QTimer(self)            # ~45 FPS: walking, gravity, edges
        self._move_timer.setInterval(MOVE_INTERVAL_MS)
        self._move_timer.setTimerType(Qt.PreciseTimer)   # avoids Windows' coarse 15 ms ticks
        self._move_timer.timeout.connect(self._tick_movement)

        self._brain_timer = QTimer(self)           # one-shot: ends the current walk / pause
        self._brain_timer.setSingleShot(True)
        self._brain_timer.timeout.connect(self._on_brain_timeout)

    # ------------------------------------------------------------------ start
    def start(self) -> None:
        """Place the pet on the taskbar, show it and start all timers."""
        min_x, max_x, _min_y, ground_y = self._bounds()
        self._x = random.uniform(min_x, max_x)     # appear somewhere along the taskbar
        self._y = ground_y
        self._sync_window_position()
        self.show()

        self._last_tick = time.perf_counter()
        self._anim_timer.start()
        self._move_timer.start()
        self._start_pause()                        # begin with a rest, then walk

    # --------------------------------------------------------------- geometry
    def _bounds(self) -> tuple[float, float, float, float]:
        """Limits for the window's top-left corner, in logical px.

        Returns (min_x, max_x, min_y, ground_y). availableGeometry() is the screen minus
        the taskbar, so its bottom edge IS the top edge of a bottom taskbar. It is queried
        on every call, so a moved / resized / auto-hidden taskbar is followed automatically.
        """
        area = QApplication.primaryScreen().availableGeometry()
        min_x = float(area.x())
        max_x = max(min_x, float(area.x() + area.width() - self.width()))
        min_y = float(area.y())
        ground_y = float(area.y() + area.height() - self.height() + FOOT_PADDING)
        return min_x, max_x, min_y, ground_y

    def _sync_window_position(self) -> None:
        """Move the real window to the float position (only if it changed)."""
        target = QPoint(round(self._x), round(self._y))
        if target != self.pos():
            self.move(target)

    # -------------------------------------------------------------- animation
    def _can_play(self, state: str) -> bool:
        """Original states always work (placeholder fallback); new ones need real sprites."""
        return state in ORIGINAL_STATES or self._bank.has_real_sprites(state)

    def _play(self, state: str, loop: bool | None = None) -> None:
        """Start playing `state` from its first frame.

        loop=None -> looping for idle / walk_* / run_*, one-shot for everything else.
        """
        self.state = state
        self._loop = (state in LOOPING_STATES + LOOPING_REST_STATES) if loop is None else loop
        interval = FRAME_INTERVAL_MS.get(state, ANIM_INTERVAL_MS)   # this state's frame speed
        if self._anim_timer.interval() != interval:                 # (setInterval restarts the timer)
            self._anim_timer.setInterval(interval)
        self._repeat_count = max(0, SPECIAL_REPEAT_COUNT.get(state, 1) - 1) if not self._loop else 0
        self._hold_ticks = 0 if self._loop else LAST_FRAME_HOLD_MS.get(state, 0) // interval
        self._set_frame(0)

    def _set_frame(self, index: int) -> None:
        """Show frame `index` of the current state (and update the click-through mask)."""
        frames = self._bank.frames[self.state]
        self._frame_idx = min(index, len(frames) - 1)
        frame = frames[self._frame_idx]
        self._pixmap = frame.pixmap
        if CLICK_THROUGH_TRANSPARENT:
            self.setMask(frame.mask)   # window shape = visible pixels -> clicks pass through
        self.update()

    def _advance_frame(self) -> None:
        """Animation timer (~5.5 FPS): step to the next frame / finish a one-shot."""
        # High DPI: if the display scale changed (settings, another monitor), re-render.
        dpr = self.devicePixelRatioF()
        if abs(dpr - self._bank.dpr) > 0.01:
            self._bank.rebuild(dpr)
            self._set_frame(self._frame_idx)

        count = len(self._bank.frames[self.state])
        if self._frame_idx + 1 < count:
            self._set_frame(self._frame_idx + 1)
        elif self._loop:
            if count > 1:
                self._set_frame(0)               # wrap around
        elif self._repeat_count > 0:
            self._repeat_count -= 1
            self._set_frame(0)                   # repeat another cycle
        elif self._hold_ticks > 0:
            self._hold_ticks -= 1                # freeze on the last frame (e.g. burnt)
        else:
            self._finish_one_shot()

    def _finish_one_shot(self) -> None:
        """A special animation ended: always return to idle."""
        self._play("idle")
        if self._phase is Phase.PAUSE and self._pause_elapsed:
            # The pause ran out while the special was still playing: rest briefly in idle
            # (so the return to idle is visible), then _on_brain_timeout starts the walk.
            self._pause_elapsed = False
            self._brain_timer.start(AFTER_SPECIAL_REST_MS)

    # --------------------------------------------------------------- behaviour
    def _start_walk(self) -> None:
        """Walk for 3-8 s in a random direction (a run instead, with RUN_CHANCE)."""
        self._phase = Phase.WALK
        self._pause_elapsed = False
        can_run = self._can_play("run_left") and self._can_play("run_right")
        gait = "run" if can_run and random.random() < RUN_CHANCE else "walk"
        self._play(f"{gait}_{random.choice(('left', 'right'))}")
        self._brain_timer.start(random_ms(WALK_MIN_S, WALK_MAX_S))

    def _start_pause(self, roll_special: bool = True, forced: str | None = None) -> None:
        """Rest for 2-5 s. Optionally open the pause with a special one-shot animation.

        forced       : play exactly this state (used for clicks and the landing).
        roll_special : otherwise roll the dice for a random special / the rare burnt.
        """
        self._phase = Phase.PAUSE
        self._pause_elapsed = False
        self._brain_timer.start(random_ms(PAUSE_MIN_S, PAUSE_MAX_S))

        special = forced
        if special is None and roll_special:
            special = self._roll_special()
        self._play(special if special else "idle")

    def _roll_special(self) -> str | None:
        """Pick a special animation for this pause, or None for a plain rest.

        Weighted by SPECIAL_WEIGHTS; states without sprites and the previous special
        are left out.
        """
        if random.random() < BURNT_CHANCE:        # rare event, checked first
            return BURNT_STATE
        if random.random() < SPECIAL_CHANCE:
            candidates = [s for s in SPECIAL_STATES + LOOPING_REST_STATES
                          if s != self._last_special and self._can_play(s)]
            if candidates:
                weights = [SPECIAL_WEIGHTS.get(s, 1) for s in candidates]
                self._last_special = random.choices(candidates, weights=weights)[0]
                return self._last_special
        return None

    def _on_brain_timeout(self) -> None:
        """Behaviour timer: the current walk / pause time is up."""
        if self._phase is Phase.WALK:
            self._start_pause()
        elif self._phase is Phase.PAUSE:
            if self._loop:                 # plain idle -> walk right away
                self._start_walk()
            else:                          # a special is still playing -> let it finish first
                self._pause_elapsed = True
        # DRAG / FALL: the timer is stopped in those phases, nothing to do.

    # ---------------------------------------------------------------- movement
    def _tick_movement(self) -> None:
        """Movement timer (~45 FPS): walking / running, turning at edges, gravity."""
        now = time.perf_counter()
        dt = min(now - self._last_tick, MAX_DT_S)   # real elapsed time -> constant speed
        self._last_tick = now
        if self._dragging or self._menu_open:       # held by the mouse / menu open: stand still
            return

        min_x, max_x, _min_y, ground_y = self._bounds()

        # Horizontal: walk / run, and turn around when an edge of the screen is reached.
        velocity = MOVE_VELOCITY_PX_S.get(self.state)   # None while standing
        if velocity is not None:
            self._x += velocity * dt
            if self._x <= min_x:
                self._x = min_x
                self._turn_around("right")
            elif self._x >= max_x:
                self._x = max_x
                self._turn_around("left")
        self._x = min(max(self._x, min_x), max_x)   # never leave the screen (even if it shrank)

        # Vertical: fall under gravity when above the ground, otherwise stick to it.
        if self._y < ground_y - 0.01:
            self._vy += GRAVITY_PX_S2 * dt
            self._y = min(self._y + self._vy * dt, ground_y)
        else:
            self._y = ground_y                      # also follows a moving taskbar
        landed = self._y >= ground_y
        if landed:
            self._vy = 0.0
            if self._phase is Phase.FALL:           # just landed after being dropped
                self._start_pause(roll_special=False)

        self._sync_window_position()

    def _turn_around(self, heading: str) -> None:
        """The pet hit a screen edge: carry on ("left" / "right"), keeping walk / run mode."""
        next_state = f"{self.state.rsplit('_', 1)[0]}_{heading}"   # walk_left -> walk_right ...
        self._play(next_state)

    # ------------------------------------------------------------------- mouse
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPos()
            self._grab_offset = event.globalPos() - self.pos()
            event.accept()
        else:
            super().mousePressEvent(event)   # right button -> contextMenuEvent follows

    def mouseMoveEvent(self, event) -> None:
        if self._press_global is None or not (event.buttons() & Qt.LeftButton):
            return
        if not self._dragging:
            # Only treat it as a drag after moving a few pixels, so plain clicks stay clicks.
            moved = (event.globalPos() - self._press_global).manhattanLength()
            if moved < QApplication.startDragDistance():
                return
            self._begin_drag()

        # Follow the cursor, clamped to the work area so the pet can't leave the screen.
        min_x, max_x, min_y, ground_y = self._bounds()
        target = event.globalPos() - self._grab_offset
        self._x = min(max(float(target.x()), min_x), max_x)
        self._y = min(max(float(target.y()), min_y), ground_y)
        self._sync_window_position()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or self._press_global is None:
            return
        self._press_global = None
        if self._dragging:
            self._end_drag()
        else:
            # A plain left-click startles the pet; CLICK_ANGRY_COUNT clicks within
            # CLICK_ANGRY_WINDOW_S seconds make it angry instead.
            now = time.perf_counter()
            self._click_times = [t for t in self._click_times if now - t <= CLICK_ANGRY_WINDOW_S]
            self._click_times.append(now)
            if len(self._click_times) >= CLICK_ANGRY_COUNT and self._can_play("angry"):
                self._click_times.clear()         # the next outburst needs fresh clicks
                self._start_pause(forced="angry")
            else:
                self._start_pause(forced="shocked")

    def _begin_drag(self) -> None:
        """The pet was picked up: stop the behaviour loop and play 'shocked' while held."""
        self._dragging = True
        self._phase = Phase.DRAG
        self._brain_timer.stop()
        self._pause_elapsed = False
        self._vy = 0.0
        self.setCursor(Qt.ClosedHandCursor)
        self._play("shocked", loop=True)          # loop it for as long as it is held

    def _end_drag(self) -> None:
        """The pet was dropped: fall to the taskbar (handled in _tick_movement)."""
        self._dragging = False
        self._phase = Phase.FALL
        self._vy = 0.0
        self._last_tick = time.perf_counter()
        self.setCursor(Qt.OpenHandCursor)

    def contextMenuEvent(self, event) -> None:
        """Right-click menu."""
        menu = QMenu(self)
        exit_action = menu.addAction("Exit")
        self._menu_open = True                    # the pet stands still while the menu is open
        try:
            chosen = menu.exec_(event.globalPos())
        finally:
            self._menu_open = False
        if chosen is exit_action:
            self._quit()

    def _quit(self) -> None:
        """Stop everything and leave the application."""
        for timer in (self._anim_timer, self._move_timer, self._brain_timer):
            timer.stop()
        self.hide()
        QApplication.quit()

    # ---------------------------------------------------------------- painting
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        # Start from a clean surface so old frames never ghost through. With click-through
        # off we paint alpha=1 (invisible to the eye) because Windows ignores mouse clicks
        # on pixels with alpha=0 - alpha=1 makes the whole square clickable.
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(),
                         QColor(0, 0, 0, 0) if CLICK_THROUGH_TRANSPARENT else QColor(0, 0, 0, 1))
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if self._pixmap is not None:
            painter.drawPixmap(0, 0, self._pixmap)   # pixmap carries its own device ratio
        painter.end()


# =============================================================================
#  5. ENTRY POINT
# =============================================================================

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    signal.signal(signal.SIGINT, signal.SIG_DFL)   # Ctrl+C in the console quits immediately

    configure_high_dpi()                           # must happen BEFORE QApplication()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)           # we quit explicitly from the menu

    # Sprites are rendered for the primary screen's scale factor (re-rendered if it changes).
    bank = SpriteBank(SPRITES_DIR, app.primaryScreen().devicePixelRatio())
    pet = DesktopPet(bank)
    pet.start()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())