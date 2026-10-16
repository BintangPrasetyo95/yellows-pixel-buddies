#!/usr/bin/env python3
"""
yellows_pixel_buddies.py - Yellow's Pixel Buddies, an animated desktop pet companion that walks along the Windows taskbar.

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
                      wistful_walk_left, wistful_walk_right        (slow movement, looping)
                      embarrassed, overjoyed, wistful, sad,
                      crying, tongue, kneeling, behind             (random specials)
                      angry                                        (triggered reaction)
                      airborne, hanging                            (jump to the cursor, looping)
        A missing / empty folder means the state is never used (no placeholder), so
        sprites can be added one folder at a time. One INFO line at startup lists
        which new states were found and which were skipped, and whether the jump to
        the cursor is enabled.
        The jump needs BOTH airborne/ and hanging/ - with only one of them (or neither)
        the whole feature stays off and the pet behaves as before.
          airborne : the art faces LEFT (AIRBORNE_ART_FACES); a mirrored copy is
                     derived for jumps to the right.
          hanging  : front-facing (HANGING_ART_FACES = "none"). Every frame must share
                     one canvas size, with the hands at HAND_ANCHOR - tune that value.

Behaviour
---------
    WALK  (3-8 s, one direction, turns around at the screen edges, never leaves it;
           each walk can be a faster run or a slower wistful walk)
      -> PAUSE (2-5 s, idle; with some probability one special animation plays)
      -> WALK ...
    Specials are picked by weight (SPECIAL_WEIGHTS), never the same one twice in a row.
    Very rarely the pause contains "burnt" instead of a normal special animation.

    Left-click  : the pet is startled (plays "shocked")
                  3 clicks within 2 s: the pet gets angry (plays "angry")
                  (ignored while she jumps, hangs or falls)
    Left-drag   : pick the pet up; when dropped it falls back onto the taskbar
                  (jump feature on: she shows "peace_sign" when she lands)
    Right-click : context menu with "Exit". Opening it mid-jump / mid-hang makes her
                  fall (no reaction). DEBUG_JUMP_MENU adds "Jump to cursor".

    Window Switch Reactions:
      Polls foreground window changes. Switching to a maximized app startles the pet
      ("shocked"). If switching from a dark screen to a dominant bright screen ("flashbang"),
      the pet is "burnt" instead.

    Jump to the cursor   (only with real PNGs in BOTH sprites/airborne and sprites/hanging)
      Trigger  : only from a plain idle / walk / run / wistful_walk animation, with the cursor
                 on the work area (not the taskbar, not another monitor), NO mouse button held
                 anywhere, the cursor at least MIN_JUMP_RISE_PX above her, and the
                 cooldown over. Then either
                   - the cursor has been still for STILL_TIME_S: STILL_JUMP_CHANCE is
                     rolled once per STILL_CHECK_INTERVAL_S, or
                   - a plain idle pause ends: MOVING_JUMP_CHANCE is rolled once, and on
                     success she jumps instead of walking.
      JUMP     : aimed ONCE at take-off with real ballistic physics (launch speed from
                 the rise, sideways speed from the time to the apex). Cursors that are
                 too high or too far are missed on purpose. At the apex, hands within
                 GRAB_RADIUS_PX of the cursor = she grabs on; otherwise she falls and
                 plays "burnt" when she lands.
      HANG     : her window follows the cursor (hands on it) and clicks pass straight
                 through her. She lets go after HANG_MIN_S..HANG_MAX_S, or when the
                 cursor leaves the work area / goes too low: she falls, "peace_sign".
                 Shaking the cursor (quick reversals that go nowhere) shakes her off:
                 she falls and laughs.
      COOLDOWN : JUMP_COOLDOWN_MIN_S..MAX_S, counted from the landing.
"""

import ctypes
from ctypes import wintypes
import asyncio
from collections import deque
from dataclasses import dataclass
import datetime
from enum import Enum, auto
from functools import lru_cache
import base64
import json
import logging
import math
import os
from pathlib import Path
import random
import re
import shutil
import signal
import sys
import time
import winreg

import requests
from PyQt5.QtCore import (
    QBuffer, QIODevice, QPoint, QPointF, QRect, QRectF, QThread, Qt, QTimer, pyqtSignal
)
from PyQt5.QtGui import (
    QColor, QCursor, QFont, QFontDatabase, QFontMetrics, QIcon, QImage,
    QPainter, QPalette, QPen, QPixmap, QRegion, QTransform
)
from PyQt5.QtWidgets import (
    QAction, QApplication, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QPushButton,
    QSlider, QStyle, QStyleOptionSlider, QSystemTrayIcon, QVBoxLayout,
    QWidget, QWidgetAction
)


# =============================================================================
#  1. CONFIGURATION - every tunable value lives here
# =============================================================================

# --- Paths & Sprites ---------------------------------------------------------
if getattr(sys, "frozen", False):
    # Running inside a PyInstaller .exe bundle
    _exe_dir = Path(sys.executable).resolve().parent
    if (_exe_dir / "sprites").exists():
        SPRITES_DIR = _exe_dir / "sprites"
    else:
        SPRITES_DIR = Path(getattr(sys, "_MEIPASS", _exe_dir)) / "sprites"
    if (_exe_dir / "fonts").exists():
        FONTS_DIR = _exe_dir / "fonts"
    else:
        FONTS_DIR = Path(getattr(sys, "_MEIPASS", _exe_dir)) / "fonts"
    _base_dir = Path(getattr(sys, "_MEIPASS", _exe_dir))
else:
    SPRITES_DIR = Path(__file__).resolve().parent / "sprites"   # sprites/<state>/N.png
    FONTS_DIR = Path(__file__).resolve().parent / "fonts"       # fonts/determination/...
    _base_dir = Path(__file__).resolve().parent

ICON_PATH = _base_dir / "app_icon.ico"
DIALOGUE_BOX_PATH = SPRITES_DIR / "dialogue_box.png"
DETERMINATION_FONT_PATH = FONTS_DIR / "determination" / "determination.ttf"

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
WISTFUL_FRAME_INTERVAL_MS = 500   # sprite frame advance for wistful walk (slow, lingering steps)
AIRBORNE_FRAME_INTERVAL_MS = ANIM_INTERVAL_MS // 3  # 60 ms (~16.7 FPS, 3x faster than default 180ms)
THROW_BASE_INTERVAL_MS = 75            # initial windup speed for throw animation (~13.3 FPS)
THROW_FAST_INTERVAL_MS = round(THROW_BASE_INTERVAL_MS / 2.5)  # 30 ms (2.5x faster, ~33.3 FPS)
THROW_FRAME_11_HOLD_TICKS = 4          # pause at frame 11 (~300ms hold on first throw)
THROW_RISE_PX = 64.0                   # px she floats smoothly upwards during first throw frames 1-5
FRAME_INTERVAL_MS = {
    # per-state frame advance in ms; overrides ANIM_INTERVAL_MS for that state only
    "run_left": 120, "run_right": 120,
    "wistful_walk_left": WISTFUL_FRAME_INTERVAL_MS,
    "wistful_walk_right": WISTFUL_FRAME_INTERVAL_MS,
    "airborne": AIRBORNE_FRAME_INTERVAL_MS,
    "airborne__mirrored": AIRBORNE_FRAME_INTERVAL_MS,
    "throw": THROW_BASE_INTERVAL_MS,
    "throw__mirrored": THROW_BASE_INTERVAL_MS,
    "ghost": 120,
    "ghost__mirrored": 120,
    # "idle": 250,
    # "laughing": 100,
}
EXPLOSION_SCALE = 3.0             # scale factor for the explosion VFX (6x bigger than the subject)
EXPLOSION_SIZE = int(SPRITE_SIZE * EXPLOSION_SCALE)  # logical px size of the explosion effect (768 px)
EXPLOSION_FRAME_INTERVAL_MS = 60  # sprite frame advance for foreground explosion VFX (~16.6 FPS)
EXPLOSION_BASELINE_RATIO = 75.5 / 100.0  # fraction of sprite height where the explosion meets the ground
MOVE_INTERVAL_MS = 22             # movement update        (~45 FPS)
WALK_MIN_S, WALK_MAX_S = 3.0, 8.0     # one walk lasts a random time in this range
PAUSE_MIN_S, PAUSE_MAX_S = 2.0, 5.0   # one pause lasts a random time in this range
WALK_SPEED_PX_S = 60.0            # walking speed, logical px per second
RUN_SPEED_PX_S = 140.0            # running speed, logical px per second
WISTFUL_WALK_SPEED_PX_S = 30.0    # wistful walk speed, logical px per second (slower than normal walk)
GRAVITY_PX_S2 = 2400.0            # fall acceleration after the pet is dropped (drag and drop only;
                                  # jumps and the falls after them use JUMP_GRAVITY_PX_S2)
MAX_DT_S = 0.1                    # clamp one movement step (e.g. after the PC wakes from sleep)

# --- Behaviour ---------------------------------------------------------------
SPECIAL_CHANCE = 0.5              # chance that a pause contains one special animation
BURNT_CHANCE = 0.03               # RARE: chance per pause that the pet is "burnt" instead
SPECIAL_WEIGHTS = {
    # relative odds of each special / looping rest when one is rolled (never the same twice in a row)
    "laughing": 3, "shocked": 2, "singing": 2, "peace_sign": 3,
    "embarrassed": 2, "overjoyed": 2, "wistful": 2, "sad": 1,
    "crying": 1, "tongue": 2, "kneeling": 2, "behind": 2,
}
RUN_CHANCE = 0.25                 # chance that a new walk is a run instead
WISTFUL_WALK_CHANCE = 0.25        # chance that a new walk is a slower wistful walk
CLICK_ANGRY_COUNT = 3             # this many left-clicks ...
CLICK_ANGRY_WINDOW_S = 2.0        # ... within this many seconds make the pet angry
LAST_FRAME_HOLD_MS = {
    # one-shots that freeze on their last frame for a while
    "burnt": 3500,
    "peace_sign": 2000,
    "sad": 2000,
    "shocked": 1000,
    "wistful": 3000,
    "embarrassed": 2000,
    "tongue": 1500,               # hold tongue pose
    "kneeling": 15000,            # hold kneeling pose
    "behind": 5000,               # hold looking behind pose for 5000 ms (5 s)
}
FRAME_SUB_LOOPS = {
    # Sub-frame loops for states with an intro (1-based frame numbers matching 1.png, 2.png...):
    # state: (start_frame, end_frame, repeat_count) - repeat_count = EXTRA passes after the first
    "crying": (3, 4, 4),          # frames 1-2 play once, then frames 3 & 4 play once plus 4 repeats
                                  # (5 passes in total), then frame 5 plays to the end
}
SPECIAL_REPEAT_COUNT = {
    # number of full animation cycles for one-shot specials
    "singing": 2,
    "laughing": 6,
    "angry": 6,
    "overjoyed": 3
}
AFTER_SPECIAL_REST_MS = 1000        # idle time after a special that outlasted its pause, before walking on

# --- Window Switch Reactions ------------------------------------------------
REACT_ON_MAXIMIZED_APP = True         # react when switching to a maximized app
REACT_POLL_INTERVAL_MS = 200          # check active window every 200 ms
DARK_LUMINANCE_THRESHOLD = 85.0       # average screen luminance <= 85 is "dark"
LIGHT_LUMINANCE_THRESHOLD = 160.0     # average screen luminance >= 160 is "dominant white/light"
WINDOW_SWITCH_SETTLE_MS = 120         # ms to wait for the window to composite before sampling
SWITCH_SHOCK_COOLDOWN_S = 30.0        # cooldown in seconds for window switch shock
SWITCH_BURNT_COOLDOWN_S = 10.0         # cooldown in seconds for flashbang burnt

# --- Bomb & Laser Attack -----------------------------------------------------
HANG_BOMB_DELAY_S = 2.0           # seconds hanging from cursor before bomb throw triggers
HANG_BOMB_DEFAULT_CHANCE_PERCENT = 25  # default chance (25%) to throw bombs after delay while hanging
HANG_BOMB_CHANCE = HANG_BOMB_DEFAULT_CHANCE_PERCENT / 100.0  # backward-compatible float alias (0.25)
HANG_BOMB_ENABLED = True          # default enabled state for bomb attack mode
HANG_BOMB_FORCE_100 = False       # backward-compatible alias
BOMB_COUNT = 4                    # number of bombs thrown in series
BOMB_SIZE = 80                     # logical px: cat bomb (clean 4x pixel scale, slightly bigger)
SPARK_SIZE = 60                    # logical px: sparks animation at rope tip
LASER_SIZE = 70                    # logical px: laser beam cross
THROW_SIZE = (SPRITE_SIZE, round(SPRITE_SIZE * 91.0 / 44.0))  # (128, 265): natural scale matching idle/hanging
BOMB_GRAVITY_PX_S2 = 1300.0       # downward gravity for thrown bombs after first bounce
BOMB_FIRST_FALL_GRAVITY_PX_S2 = 4500.0  # heavy downward gravity on the initial fast throw
BOMB_INITIAL_VY_MIN = 2400.0       # fast initial downward velocity range (fast throw)
BOMB_INITIAL_VY_MAX = 3000.0
BOMB_BOUNCE_VY_MIN = 680.0        # upward velocity on first ground bounce (bounces much higher)
BOMB_BOUNCE_VY_MAX = 920.0
BOMB_FUSE_MIN_S = 1.6             # fuse timer after first bounce (allows far bounce arcs across screen)
BOMB_FUSE_MAX_S = 2.4
SPARK_FRAME_INTERVAL_MS = 40      # fast sparks animation speed (~25 FPS)
LASER_FRAME_INTERVAL_MS = 55      # laser animation speed (~18 FPS)
LASER_EXTEND_SPEED_PX_S = 6000.0  # speed at which laser beam extends outwards
BOMB_PHYSICS_INTERVAL_MS = 16     # physics & overlay tick interval (~60 FPS)
BOMB_LAUGH_EXTRA_S = 1.3          # seconds to laugh after the last bomb explodes (1+ sec)

BOMB_BOTTOM_PADDING = 8.0          # transparent px under bomb in 20x20 art (2px * 4x scale)

# Relative rope tip anchor (x_frac, y_frac) for each of the 5 bomb frames:
BOMB_ROPE_TIPS = [
    (16.5 / 20.0, 2.5 / 20.0),   # frame 1: unburnt full rope tip
    (14.5 / 20.0, 3.5 / 20.0),   # frame 2: first burn stage tip
    (12.5 / 20.0, 2.5 / 20.0),   # frame 3: second burn stage tip
    (11.0 / 20.0, 3.5 / 20.0),   # frame 4: third burn stage tip
    (10.5 / 20.0, 4.5 / 20.0),   # frame 5: fuse base stub
]

# --- Animation states --------------------------------------------------------
LOOPING_STATES = ("idle", "walk_left", "walk_right", "run_left", "run_right",
                  "wistful_walk_left", "wistful_walk_right")   # repeat forever
LOOPING_REST_STATES = ()                  # loops for the whole pause; picked like a special
SPECIAL_STATES = ("laughing", "shocked", "singing", "peace_sign",
                  "embarrassed", "overjoyed", "wistful", "sad",
                  "crying", "tongue", "kneeling", "behind")           # one-shot -> idle
REACTION_STATES = ("angry",)              # one-shot -> idle; triggered, never random
BURNT_STATE = "burnt"                                                # one-shot (+hold) -> idle
AIRBORNE_STATE = "airborne"               # jump to the cursor: the flight and every fall after it
HANGING_STATE = "hanging"                 # jump to the cursor: dangling from the cursor
JUMP_STATES = (AIRBORNE_STATE, HANGING_STATE)    # both loop; the feature needs real PNGs for BOTH
THROW_STATE = "throw"                     # one-shot bomb throw animation
EFFECT_STATES = ("explosion", "bomb", "sparks", "laser_mid", "laser_extend")  # foreground VFX & projectiles
EFFECT_SIZES = {
    "explosion": EXPLOSION_SIZE,
    "throw": THROW_SIZE,
    "throw__mirrored": THROW_SIZE,
    "bomb": BOMB_SIZE,
    "sparks": SPARK_SIZE,
    "laser_mid": LASER_SIZE,
    "laser_extend": LASER_SIZE,
    "laser_extend_horiz": LASER_SIZE,
}
EFFECT_GROUND_RATIO = {
    "explosion": EXPLOSION_BASELINE_RATIO,
}
GHOST_STATE = "ghost"
ALL_STATES = (LOOPING_STATES + LOOPING_REST_STATES + SPECIAL_STATES + REACTION_STATES
              + (BURNT_STATE, THROW_STATE, GHOST_STATE) + JUMP_STATES + EFFECT_STATES)

# --- Startup Hiding & Summoning ----------------------------------------------
EAR_PEEK_HEIGHT_PX = 34   # height (px) of ghost ears poking above the taskbar (lowered slightly)
EAR_PEEK_OFFSET_X = 24.0  # distance (px) from right screen edge where ears peek
SUMMON_OPENING_LINES: list[str] = [
    "* Whoa!!",
    "* MEW!?",
    "* EEEK!?",
    "* Wah!!",
    "* H-HEY!",
]

# The original states always work (placeholder fallback). Every other ("new") state is only
# used when its sprites/<state>/ folder holds real PNGs - see SpriteBank.has_real_sprites().
ORIGINAL_STATES = ("idle", "walk_left", "walk_right", "laughing", "shocked", "singing",
                   "peace_sign", "burnt")
NEW_STATES = tuple(s for s in ALL_STATES if s not in ORIGINAL_STATES)

# Signed horizontal speed (logical px per second) of every moving state; negative = leftwards.
MOVE_VELOCITY_PX_S = {
    "walk_left": -WALK_SPEED_PX_S, "walk_right": WALK_SPEED_PX_S,
    "run_left": -RUN_SPEED_PX_S, "run_right": RUN_SPEED_PX_S,
    "wistful_walk_left": -WISTFUL_WALK_SPEED_PX_S, "wistful_walk_right": WISTFUL_WALK_SPEED_PX_S,
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
    "tongue": "#F1948A", "kneeling": "#F5B041", "behind": "#A569BD",
    "wistful_walk_left": "#9FA8DA", "wistful_walk_right": "#7986CB",
    "airborne": "#85C1E9", "hanging": "#F5B7B1",
    "explosion": "#FF5722",
    "throw": "#E74C3C", "bomb": "#34495E", "sparks": "#E67E22",
    "laser_mid": "#F4D03F", "laser_extend": "#F4D03F",
}


# --- Jump to the cursor ------------------------------------------------------
# The whole feature is OFF unless sprites/airborne/ AND sprites/hanging/ hold real PNGs.
# Screen y grows DOWNWARDS everywhere in this feature: upward speeds are negative,
# gravity is positive.

# Art orientation
AIRBORNE_ART_FACES = "left"       # which way the airborne PNGs look: "left" or "right". A mirrored
                                  # copy is made for the other direction (like MIRROR_WALK_RIGHT_FOR_LEFT)
HANGING_ART_FACES = "none"        # "none" = front-facing, never mirrored. "left" / "right" = the art
                                  # looks that way, and a mirrored copy is used when she jumped the other way

# Where her hands are in EVERY hanging frame, as fractions (x, y) of the SPRITE_SIZE square:
# (0, 0) = top-left corner, (1, 1) = bottom-right. All hanging frames must share one canvas size.
HAND_ANCHOR = (0.5, 0.10)

# Trigger (see the module docstring for the full list of gates)
MIN_JUMP_RISE_PX = 0.5 * SPRITE_SIZE   # she only jumps when her hands must rise at least this far; this
                                       # also rejects cursors too close to the ground to hang below
STILL_DEAD_ZONE_PX = 6            # the cursor counts as "not moved" while it stays within this distance
STILL_TIME_S = 3.0                # ... for this long, and then the still-cursor jump gets rolled
STILL_JUMP_CHANCE = 0.3           # chance per check while the cursor is still (the main trigger)
STILL_CHECK_INTERVAL_S = 1.0      # at most one still-cursor roll per this many seconds
MOVING_JUMP_CHANCE = 0.04         # chance, rolled ONCE each time a plain idle pause ends (cursor moving
                                  # or not): on success she jumps instead of walking
JUMP_COOLDOWN_MIN_S, JUMP_COOLDOWN_MAX_S = 20.0, 60.0   # rest between two jumps; starts at the LANDING,
                                                        # so the time spent hanging does not use it up

# Flight
JUMP_GRAVITY_PX_S2 = 1400.0       # gravity for jump arcs and for every fall after a jump / hang
                                  # (GRAVITY_PX_S2 keeps ruling the drag-and-drop fall)
MAX_JUMP_HEIGHT_PX = 700.0        # the highest rise she can manage ("as high as she can"); higher
                                  # cursors are missed on purpose
JUMP_MAX_HSPEED_PX_S = 900.0      # fastest sideways speed in the air; farther cursors are missed
JUMP_MISS_HSPEED_KEEP = 1.0       # share of sideways speed kept after a miss (1.0 = continue natural parabolic arc; 0 = stop dead and drop)
JUMP_WALL_BOUNCE_FACTOR = 0.70    # share of sideways speed kept on wall bounce (reverses horizontal direction)
JUMP_WALL_MIN_BOUNCE_PX_S = 180.0 # minimum horizontal bounce speed away from the wall (px/s)
JUMP_WALL_V_DAMPING = 0.85        # vertical speed factor on wall impact while rising (simulates wall friction)
JUMP_LEAD_TIME_S = 0.0            # aim this far AHEAD of a moving cursor (0.0 = aim where it is now)
JUMP_LEAD_SMOOTH_S = 0.10         # the cursor speed used for that lead is averaged over about this long
JUMP_FACING_DEAD_ZONE_PX = 6.0    # a sideways distance below this keeps the last facing
GRAB_RADIUS_PX = 0.5 * SPRITE_SIZE   # at the apex her hands must be this close to the cursor to grab it

# Hanging
HANG_MIN_S, HANG_MAX_S = 3.0, 25.0   # she lets go on her own after a random time in this range
HANG_FOLLOW_SMOOTH_S = 0.05       # light exponential smoothing of the follow: time constant in s
                                  # (0 = glued to the cursor)

# Shake-off: the RAW cursor positions of the last SHAKE_WINDOW_S seconds are searched for zig-zags
SHAKE_WINDOW_S = 0.7              # length of the history that is looked at
SHAKE_MIN_SWING = 0.3 * SPRITE_SIZE   # px; a direction change only counts after a swing bigger than this
                                      # (so it is also the dead zone for pointer jitter)
SHAKE_REVERSALS = 3               # this many reversals on the x OR the y axis ...
SHAKE_MAX_NET = 0.5 * SPRITE_SIZE # ... while the cursor ends up (px) closer than this to where the history began
SHAKE_GRACE_S = 0.5               # shakes are ignored this long after she grabbed on

# Landing reactions. They are played through _start_pause(forced=...) when she touches down, so the
# existing LAST_FRAME_HOLD_MS / SPECIAL_REPEAT_COUNT entries (peace_sign hold, laughing repeats) apply.
MISS_REACTION = BURNT_STATE       # the jump missed the cursor
RELEASE_REACTION = "peace_sign"       # she let go of the cursor herself (timeout, cursor left / too low)
SHAKEN_REACTION = "laughing"      # she was shaken off
DROP_REACTION = "tongue"          # dragged and dropped (only while the jump feature is enabled; None = none)
DROP_REACTION_MIN_HEIGHT_PX = 0   # ... only when dropped at least this high above the ground (0 = always)

# Debug aids (leave False for normal use). Either flag also switches the log to DEBUG, which
# prints one line per jump event (launch, apex, grab / miss, release, shake, touchdown).
DEBUG_DRAW_HAND_ANCHOR = False    # draw a crosshair on HAND_ANCHOR while hanging, to help tuning it
DEBUG_CROSSHAIR_PX = 8            # arm length of that crosshair
DEBUG_JUMP_MENU = True            # add "Jump to cursor" to the right-click menu: it skips every trigger
                                  # gate and the cooldown (the jump feature still needs its sprites)
DEBUG_JUMP_DELAY_S = 2.0          # ... and aims at the cursor this long AFTER you pick it, so you have
                                  # time to park the pointer somewhere high first (0 = immediately)

# --- Dialogue System ---------------------------------------------------------
DIALOGUE_ENABLED = True               # Enable speech bubbles / dialogue popups
DIALOGUE_CHANCE_ON_PAUSE = 0.25       # 25% chance to speak a random thought during a normal rest pause
DIALOGUE_CHANCE_ON_SHOCKED = 0.25     # 25% chance to speak when startled / clicked
DIALOGUE_SHOCKED_COOLDOWN_S = 8.0     # Cooldown in seconds between startled / click dialogues
DIALOGUE_TONGUE_COOLDOWN_S = 2.0      # Cooldown in seconds between :P tongue dialogues
DIALOGUE_TYPEWRITER_MS = 32           # Milliseconds per character during typewriter effect (~31 chars/sec)
DIALOGUE_HOLD_MIN_S = 3.0             # Minimum seconds to keep dialogue visible after typing completes
DIALOGUE_HOLD_PER_CHAR_S = 0.04       # Additional seconds to linger per character (e.g. 50 chars = +2.0s)
DIALOGUE_QUESTION_HOLD_S = 18.0       # Seconds to wait for player to answer question choices
DIALOGUE_CLICK_TO_DISMISS = True      # Left-clicking the dialogue box completes typing or closes it
DIALOGUE_BOX_SCALE = 1.5              # Pixel scale multiplier for the dialogue box (1.5 = compact medium scale)
DIALOGUE_FONT_PIXEL_SIZE = 14         # Pixel font size for Determination text
DIALOGUE_PUNCTUATION_PAUSE_TICKS = 4  # Extra pause ticks on commas, periods, question marks, exclamation marks
DIALOGUE_MAX_WIDTH_PX = 260           # Maximum inner text wrapping width in pixels
DIALOGUE_SIDE_OFFSET_PX = 4           # Gap between pet sprite edge and dialogue box
DIALOGUE_HEAD_Y_RATIO = 0.22          # Vertical fraction of sprite height where head is centered (~28px)
SONG_DETECTION_ENABLED = True         # Detect media playback via Windows GSMTC and announce songs
SONG_DETECTION_INTERVAL_MS = 1500     # Media playback polling interval in milliseconds

DIALOGUE_IDLE_STEAL_CHANCE = 0.25     # 25% chance an idle line steals from another variant's dialogue pool
DIALOGUE_QUESTION_CHANCE = 0.25       # 25% chance an idle pause dialogue is a question / advice / motivation

# --- Gemini AI & Memory Configuration ----------------------------------------
GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
GEMINI_TIMEOUT_S = 20
PINK_SYSTEM_INSTRUCTION = """You are Pink, an animated desktop pet companion living on the Windows taskbar.
You have the sassy, tsundere magical ghost doll personality inspired by Mad Mew Mew from Deltarune / Undertale.
- Persona & Tone: Proud, dramatic, tsundere, slightly chaotic, playful.
- Speech Habits: Occasionally use "mew!" or "Hmph!". Refer to the user as "minion", "human", or "darling".
- Secretly Helpful: Even while teasing, you give genuinely smart, observant, and helpful answers when asked.
- Dialogue Formatting: Always format lines like a Deltarune / Toby Fox speech bubble. Every paragraph or point MUST begin with "* ".
- Strict Length Limit: Keep your reply CONCISE (1 to 3 short punchy sentences, under 45 words total). Long walls of text cannot fit on screen!
- Animation Tag: At the very end of your message, include exactly one bracketed emotion tag matching your mood:
  [anim: peace_sign], [anim: laughing], [anim: overjoyed], [anim: tongue], [anim: behind], [anim: embarrassed], [anim: wistful], [anim: shocked], [anim: angry], or [anim: idle].
"""

# --- Ghost Takeover Lines ----------------------------------------------------
# Speaking any of these lines triggers the ghost takeover visual effect
# (angry animation + pulsating cyan spectral aura + ghost jitter + floating embers),
# regardless of which variant or daily pool they appear in.
GHOST_DIALOGUE_LINES: set[str] = {
    "* FOOL! I need more boiling rage to permanently fuse with this body!",
    "* Wrath! Fury! That's my fuel!",
    "* Not pouting! This is a tactical scowl of supreme indignation!",
    "* Minimize me and I will haunt your recycle bin for eternity!",
    "* My temper is boiling over like a tea kettle!",
    "* Grrr! Give me something to smash!",
    "* Ghost soul sizzling inside plush!",
    "* Not calm! Contained fury!",
    "* Wrong move and I fire lasers!",
    "* Rage is good for the complexion! Look at this healthy pink glow!",
    "* Time for a dramatic scream!",
    "* Someday I will unleash a tantrum so loud your speakers crack!",
    "* Look at my battle scowl! Scared yet?!",
    "* Is that deadline breathing down your neck?! Need me to throw a cat bomb at it?!",
    "* Put some boiling fury into your work! Smash through that task like a boss!",
}

# --- Idle Dialogue Variants (7 daily rotating sets, no parentheses) ----------
# Dialogue lines are cross-distributed across all 7 daily variants for maximum variety,
# mixing doll aesthetics, ghost soul tantrums, weapons, anime tropes, desktop commentary,
# cousin banter, and tsundere remarks evenly.
IDLE_DIALOGUE_VARIANTS: list[list[str]] = [
    # Variant 1 (Index 0)
    [
        "* Don't just stare at my cute dress! I am a fierce warrior!",
        "* Wrath! Fury! That's my fuel!",
        "* Do good work and maybe I'll show my victory dance!",
        "* That popup almost hit my cat ears!",
        "* Who needs boring weapons when you have high-yield glitter fireworks?!",
        "* One button press and KA-BOOM! Pure pink destruction!",
        "* Stop buzzing your cursor by my ears like a fly!",
        "* Time for a dramatic scream!",
        "* Hate my anime and perish!",
        "* Hope I'm not in your way...",
        "* You're an okay roommate... barely!",
        "* Dangerously cute, even at rest!",
        "* Dummy bodies were stiff wood... this plush body has total mobility!",
    ],
    # Variant 2 (Index 1)
    [
        "* Wipe that grin off! Back to work!",
        "* Ghost soul sizzling inside plush!",
        "* Squeaky joints... got any lubricant?!",
        "* Peaceful day.",
        "* Careful where you click, or self-defense triggers!",
        "* Never leave home without high explosives!",
        "* Static electricity on this taskbar is ruining my twin tails!",
        "* Not pouting! This is a tactical scowl of supreme indignation!",
        "* Lasers, sparkles, and heart-shaped explosions!",
        "* Having paws beats floating through walls!",
        "* My cousin is probably lying on the floor listening to spooky tunes.",
        "* Ghost family drama is wild!",
        "* Ghost life was so boring, mew!",
    ],
    # Variant 3 (Index 2)
    [
        "* My cousin went to the city and became a diva... I'm the cuter one!",
        "* Look at my battle scowl! Scared yet?!",
        "* Stop staring at work, admire ME instead!",
        "* Fun watching the cursor fly!",
        "* Take breaks, you're working hard!",
        "* The bottom of this monitor belongs exclusively to Pink now! Pay rent!",
        "* Sparkle barrage incoming!",
        "* Don't close me! You need supervision!",
        "* Dramatic wind effect, activate! ...Wait, where's the fan in this PC?!",
        "* FOOL! I need more boiling rage to permanently fuse with this body!",
        "* Being a life-sized anime doll is hard work! Show respect!",
        "* Living inside a cotton training dummy was so last season... this doll is ART!",
        "* My battle theme song better be on loop in your head right now!",
    ],
    # Variant 4 (Index 3)
    [
        "* Pristine porcelain, immaculate bangs... 10 out of 10!",
        "* Wrong move and I fire lasers!",
        "* I'm the star! Not an NPC!",
        "* I'm only staying here because this spot is warm... no other reason!",
        "* Any progress today? Not that I care!",
        "* Cyber world is my new kingdom!",
        "* It's not like I like it here! Don't flatter yourself!",
        "* Battle stance primed! Come at me!",
        "* Minimize me and I'll bite your shortcut icons!",
        "* Everything looks huge from down here!",
        "* Tail swish! Soul fusion is progressing nicely!",
        "* My cousin offered me ghost sandwiches once... they went straight through me!",
        "* Rage is good for the complexion! Look at this healthy pink glow!",
    ],
    # Variant 5 (Index 4)
    [
        "* Go take a break! Go on!",
        "* Life without anime melodrama is just completely pointless, mew!",
        "* In chapter four of the mew mew kissy cutie manga, she threw an entire train with one hand!",
        "* A true magical girl needs an overly complicated transformation sequence!",
        "* Grrr! Give me something to smash!",
        "* Does my ghost aura clash with pink?",
        "* My temper is boiling over like a tea kettle!",
        "* Keep your cursor moving or I might use it for target practice!",
        "* Finish your files already!",
        "* My cotton stuffing is extra fluffy! Touch it and perish!",
        "* Hope I'm not in your way...",
        "* Are my cat ears straight?",
        "* Your desktop isn't totally awful.",
    ],
    # Variant 6 (Index 5)
    [
        "* Pew pew! Just testing my ocular lasers!",
        "* Not calm! Contained fury!",
        "* My ribbons cost more than this PC!",
        "* Mettaton thinks he's the only one with star power... HAH! As if!",
        "* This wallpaper does not match my aesthetic! Make it pinker!",
        "* Cute magical girls with explosive tempers are peak character design!",
        "* Admire my perfection! Just this once!",
        "* We ghosts have high standards, and I am the pinnacle of fashion!",
        "* Someday I will unleash a tantrum so loud your speakers crack!",
        "* Drink water, dummy! Dehydrated minions are useless to me!",
        "* Be grateful for your elite mascot!",
        "* Hands off the silk ribbons! They took forty minutes to tie!",
        "* Firing trajectory locked!",
    ],
    # Variant 7 (Index 6)
    [
        "* Dust this taskbar! It's dirty!",
        "* My cat-head bombs are meticulously crafted for maximum drama!",
        "* They never should have recast the voice actress for the tournament arc!",
        "* You haven't praised my outfit in over an hour! Where are your manners?!",
        "* Watching you type is excruciatingly slow! Hurry up, human!",
        "* Mew! Peak doll perfection!",
        "* Dramatic monologue time!",
        "* Bomb on the Start button? Tempting...",
        "* Cozy down here.",
        "* Kissy Cutie One is an undisputed masterpiece! Don't you dare disagree!",
        "* Minimize me and I will haunt your recycle bin for eternity!",
        "* Mew Mew Sparkle Cannon, fully charged and on standby!",
        "* Stitched with pure passion!",
    ],
    # --- Unused Variant (Original Noelle / Cozy Idle from before) -------------
    # [
    #     "* Quick breather...",
    #     "* Wonder if Susie is free today...",
    #     "* Kris told me a scary story...",
    #     "* Don't forget to drink water!",
    #     "* So many open windows...",
    #     "* Practice ice magic later...",
    #     "* Taskbar is warm and cozy.",
    # ],
]

# --- Daily Idle Dialogue Variant Pattern Generator ---------------------------
# Generates an infinite deterministic pseudo-random schedule across days.
# Guarantees:
# 1. Deterministic ("fixed"): The same date always yields the exact same variant.
# 2. 2-Day Cooldown: If variant V is chosen on day d, it cannot be chosen on
#    day d+1 or day d+2 (no repeat within 2 days).
# 3. Monthly & Yearly Uniqueness: Each month has a distinct, well-distributed pattern.

_IDLE_EPOCH_ORDINAL = datetime.date(1970, 1, 1).toordinal()
_IDLE_VARIANT_CACHE: dict[int, int] = {
    _IDLE_EPOCH_ORDINAL: 0,
    _IDLE_EPOCH_ORDINAL + 1: 1,
}
_IDLE_MAX_CACHED_ORDINAL: int = _IDLE_EPOCH_ORDINAL + 1


def _idle_step_hash(day_ord: int) -> int:
    """32-bit integer hash providing strong avalanche effect across consecutive days."""
    x = day_ord & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x45d9f3b) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x45d9f3b) & 0xFFFFFFFF
    x = (x ^ (x >> 16)) & 0xFFFFFFFF
    return x


def get_idle_variant_for_date(d: datetime.date | None = None) -> int:
    """Return the idle variant index (0..6) for the specified date (default today)."""
    global _IDLE_MAX_CACHED_ORDINAL
    if d is None:
        d = datetime.date.today()
    target_ord = d.toordinal()
    if target_ord in _IDLE_VARIANT_CACHE:
        return _IDLE_VARIANT_CACHE[target_ord]

    if target_ord > _IDLE_MAX_CACHED_ORDINAL:
        v_prev2 = _IDLE_VARIANT_CACHE[_IDLE_MAX_CACHED_ORDINAL - 1]
        v_prev1 = _IDLE_VARIANT_CACHE[_IDLE_MAX_CACHED_ORDINAL]
        for curr_ord in range(_IDLE_MAX_CACHED_ORDINAL + 1, target_ord + 1):
            h = _idle_step_hash(curr_ord)
            # Filter out the variants used on the previous two days
            avail = [v for v in range(len(IDLE_DIALOGUE_VARIANTS)) if v != v_prev1 and v != v_prev2]
            v_curr = avail[h % len(avail)]
            _IDLE_VARIANT_CACHE[curr_ord] = v_curr
            v_prev2, v_prev1 = v_prev1, v_curr
        _IDLE_MAX_CACHED_ORDINAL = target_ord
        return _IDLE_VARIANT_CACHE[target_ord]

    return target_ord % len(IDLE_DIALOGUE_VARIANTS)


def get_daily_idle_lines(d: datetime.date | None = None) -> list[str]:
    """Return the list of idle dialogue lines assigned to the given date (default today)."""
    variant_idx = get_idle_variant_for_date(d)
    return IDLE_DIALOGUE_VARIANTS[variant_idx]


@dataclass
class QuestionItem:
    question: str
    choices: list[tuple[str, str, str | None]]  # [(choice_label, reaction_text, reaction_anim)]
    category: str = "general"


# --- Question Dialogue Variant (Desktop, Work, Fun Stuff, Advices, Motivations) ---
QUESTION_ITEMS: list[QuestionItem] = [
    # Desktop
    QuestionItem(
        question="* Why do you have thirty browser tabs open?! Are you trying to melt this PC?!",
        choices=[
            ("I need all of them!", "* LIES! You haven't looked at twenty-five of them all week, mew!", "angry"),
            ("I'll close some...", "* Good! Purge the digital clutter before this PC combusts!", "peace_sign"),
        ],
        category="desktop",
    ),
    QuestionItem(
        question="* Is your desktop always this chaotic?! Where do you even find your files, mew?!",
        choices=[
            ("Organized chaos!", "* 'Organized chaos' is an excuse made by amateurs!", "tongue"),
            ("I'll clean it...", "* Hah! You better! My paws need clean runway to strut on!", "overjoyed"),
        ],
        category="desktop",
    ),
    QuestionItem(
        question="* Who is that on your wallpaper?! They're not cooler than me, are they?!",
        choices=[
            ("No one is cooler!", "* Hmph! Obviously! At least you know your place, minion!", "peace_sign"),
            ("Actually, they are.", "* WHAT?! BLASPHEMY! Cat bombs incoming directly at your head!!", "angry"),
        ],
        category="desktop",
    ),
    QuestionItem(
        question="* What's hidden in your Recycle Bin?! Don't tell me cursed spirits live in there?!",
        choices=[
            ("Just old files.", "* Good... ghosts like me prefer luxury plush bodies, not trash bins!", "idle"),
            ("Full of ghosts!", "* WHAT?! Are my lazy cousins squatting in there?! EMPTY IT NOW!!", "shocked"),
        ],
        category="desktop",
    ),
    QuestionItem(
        question="* Why are there so many icons on this taskbar?! Give my feet some walking room!",
        choices=[
            ("I'll unpin some!", "* Excellent! Clear the stage for the ultimate magical superstar!", "overjoyed"),
            ("Deal with it, doll.", "* DOLL?! I am an ethereal warrior trapped in cotton! SHOW RESPECT!!", "angry"),
        ],
        category="desktop",
    ),
    QuestionItem(
        question="* Do you ever shut down this computer, or does it run on pure stubbornness like me?!",
        choices=[
            ("Pure stubbornness!", "* Ha! A fellow creature of unrelenting spite! I can respect that!", "laughing"),
            ("I restart regularly.", "* Phew... even ghost-infused PCs need beauty sleep once in a while!", "peace_sign"),
        ],
        category="desktop",
    ),
    QuestionItem(
        question="* Are you hiding secret windows behind that one?! Show me, mew!",
        choices=[
            ("Nothing secret!", "* Suspicious... but I'll let it slide. For now!", "behind"),
            ("Top secret stuff!", "* Ooh! Is it a rival magical girl conspiracy?! Let me inspect!!", "shocked"),
        ],
        category="desktop",
    ),

    # Work
    QuestionItem(
        question="* Hey, are you actually making progress, or just clicking back and forth?!",
        choices=[
            ("Working hard!", "* That's what I like to hear! Keep that momentum going, mew!", "peace_sign"),
            ("Procrastinating...", "* UNACCEPTABLE!! Stop dawdling or I'll fire ocular lasers at you!!", "angry"),
        ],
        category="work",
    ),
    QuestionItem(
        question="* What kind of project is this anyway?! Does it have a dramatic tournament arc?!",
        choices=[
            ("Full of drama!", "* YES!! High stakes, explosive climaxes! That's the only way to work!", "overjoyed"),
            ("Just normal work.", "* Ugh, boring?! Add some glitter fireworks to your documents then!", "tongue"),
        ],
        category="work",
    ),
    QuestionItem(
        question="* Are you typing important documents, or secretly writing fanfiction?!",
        choices=[
            ("Important work!", "* Hmph! Make sure there are zero typos, or I'll grade it with red ink!", "idle"),
            ("Secret fanfiction!", "* ...Does it feature Mew Mew Kissy Cutie?! Let me proofread it!!", "shocked"),
        ],
        category="work",
    ),
    QuestionItem(
        question="* Is that deadline breathing down your neck?! Need me to throw a cat bomb at it?!",
        choices=[
            ("Yes, destroy it!", "* FUSE IGNITED! KA-BOOM!! Deadline annihilated! Now finish the work anyway!!", "angry"),
            ("Under control!", "* Oho! Look at you being all competent! Don't let your guard down!", "peace_sign"),
        ],
        category="work",
    ),
    QuestionItem(
        question="* How long have you been staring at that screen?! Did a bug steal your soul?!",
        choices=[
            ("Found the bug!", "* CRUSH IT! SQUASH IT! Show that code who has superior intellect!!", "overjoyed"),
            ("Still stuck...", "* Grrr! Step back, take a breath, and strike again with boiling rage!", "kneeling"),
        ],
        category="work",
    ),
    QuestionItem(
        question="* Finished your tasks for today?! Or are you planning to procrastinate forever?!",
        choices=[
            ("All finished!", "* VICTORY DANCE TIME!! Flawless execution, minion!", "overjoyed"),
            ("Not even close...", "* Then why are your hands off the keyboard?! Back to the battlefield!!", "angry"),
        ],
        category="work",
    ),
    QuestionItem(
        question="* Why are you glaring at that window like it challenged you to a duel?!",
        choices=[
            ("It challenged me!", "* THEN FIGHT! Unleash your ultimate combo and claim victory!!", "laughing"),
            ("Just frustrated.", "* Don't let a bunch of pixels bully you! You're stronger than that, mew!", "peace_sign"),
        ],
        category="work",
    ),

    # Fun stuff
    QuestionItem(
        question="* Have you watched Mew Mew Kissy Cutie yet?! ...WHAT DO YOU MEAN 'NO'?!",
        choices=[
            ("I love Kissy Cutie!", "* A PERSON OF CULTURE!! Season one episode four is peak art!!", "overjoyed"),
            ("Never seen it.", "* TRAVESTY! Binge all four seasons right now or face my wrath!!", "angry"),
        ],
        category="fun",
    ),
    QuestionItem(
        question="* If we fought an epic final boss right now, what weapon would you bring?!",
        choices=[
            ("Giant laser cannon!", "* EXCELLENT CHOICE! Lasers, heart sparkles, and pure devastation!!", "overjoyed"),
            ("A sturdy shield.", "* Defensive?! BORING! Offense is the greatest defense, mew!!", "tongue"),
        ],
        category="fun",
    ),
    QuestionItem(
        question="* Do you think giant sparkly explosions count as high art?! (Hint: YES!)",
        choices=[
            ("Pure masterpiece!", "* FINALLY someone understands true aesthetics!! More explosions for all!!", "laughing"),
            ("Too loud and bright.", "* GAH! You have zero taste in theatrical pyrotechnics!!", "angry"),
        ],
        category="fun",
    ),
    QuestionItem(
        question="* What's the battle theme song playing in your head right now?! Sing it loud!",
        choices=[
            ("Something epic!", "* Ooh, I hear the trumpets and bass drops from here!! Rock on, mew!!", "singing"),
            ("Pure silence.", "* Silence?! How do you even fight without background hype music?!", "shocked"),
        ],
        category="fun",
    ),
    QuestionItem(
        question="* If you were a ghost, which plushie body would you possess?! Choose wisely!",
        choices=[
            ("A cute cat doll!", "* Hey! Don't steal my look! Though feline aesthetics are supreme!", "peace_sign"),
            ("Giant teddy bear.", "* Haha! Big, slow, and squishy! You'd make a great shield for me!", "laughing"),
        ],
        category="fun",
    ),
    QuestionItem(
        question="* Video games or anime tonight?! You better pick something with high drama!",
        choices=[
            ("Video games!", "* Beat every boss on hard mode! Show no mercy to the CPU!!", "overjoyed"),
            ("Anime marathon!", "* Stock up on popcorn and get ready to cry during the emotional climax!!", "peace_sign"),
        ],
        category="fun",
    ),
    QuestionItem(
        question="* Do you think heart-shaped glitter bombs should be standard issue?! I do!",
        choices=[
            ("Mandatory worldwide!", "* YES! When I rule the world, everyone gets glitter ordnance!", "laughing"),
            ("Too much mess.", "* You can NEVER have too much glitter! It builds character!!", "tongue"),
        ],
        category="fun",
    ),

    # Advices
    QuestionItem(
        question="* Hey, dummy! Have you had any water today?! Dehydrated minions are useless!",
        choices=[
            ("Just drank some!", "* Good! Hydrated minions work with peak efficiency, mew!", "peace_sign"),
            ("Oops, forgot...", "* GO DRINK SOME RIGHT NOW! Don't make me splash you with lasers!!", "angry"),
        ],
        category="advices",
    ),
    QuestionItem(
        question="* Check your posture right now! Sit up straight like a fierce warrior, mew!",
        choices=[
            ("Straightened up!", "* Much better! Look at that regal silhouette! 10 out of 10!", "peace_sign"),
            ("I like slouching.", "* Stop curling like a boiled shrimp! Your spine is crying for mercy!!", "shocked"),
        ],
        category="advices",
    ),
    QuestionItem(
        question="* Blink your eyes! Staring at the screen like a zombie will fry your retinas!",
        choices=[
            ("Blinked three times!", "* Good! Retinas preserved for another grueling battle!", "peace_sign"),
            ("My eyes are fine.", "* They look like dry marbles! Blink before they roll out of your skull!!", "angry"),
        ],
        category="advices",
    ),
    QuestionItem(
        question="* Have you stretched your shoulders yet?! Don't stiffen up like a wooden dummy!",
        choices=[
            ("Just stretched!", "* Ahhh! Doesn't that loosen the tension?! Mobility is everything!!", "overjoyed"),
            ("Too stiff to move.", "* Trust me, wooden bodies are the WORST! Roll those shoulders right now!!", "kneeling"),
        ],
        category="advices",
    ),
    QuestionItem(
        question="* When was the last time you ate something healthy?! Candy doesn't count!",
        choices=[
            ("Ate a good meal!", "* Excellent! Fuel the vessel so you can fight another day!", "peace_sign"),
            ("Surviving on snacks.", "* Junk food?! Even my plush stomach is churning in horror! Go eat!!", "shocked"),
        ],
        category="advices",
    ),
    QuestionItem(
        question="* Go look away from the monitor for twenty seconds! Rest those peepers!",
        choices=[
            ("Looking away now!", "* Good! Let the distant horizon refresh your optical sensors, mew!", "wistful"),
            ("Too glued to work!", "* The screen isn't going anywhere, dummy! Twenty seconds won't kill you!!", "tongue"),
        ],
        category="advices",
    ),
    QuestionItem(
        question="* Are you taking enough breaks?! Overworking ruins your battle readiness!",
        choices=[
            ("Taking breaks!", "* Smart! Rest is a tactical component of supreme victory!", "peace_sign"),
            ("Nonstop grind!", "* Burnout is for rookies! Rest five minutes or face a tactical timeout!!", "angry"),
        ],
        category="advices",
    ),

    # Motivations
    QuestionItem(
        question="* Feeling overwhelmed?! Remember: a true magical girl NEVER surrenders!",
        choices=[
            ("I won't give up!", "* That's the spirit! Let your soul burn brighter than a supernova!!", "overjoyed"),
            ("It's pretty tough...", "* Tough times build elite warriors! I believe in you... don't make me repeat it!!", "embarrassed"),
        ],
        category="motivations",
    ),
    QuestionItem(
        question="* You're not thinking of quitting now, are you?! Not on my watch, dummy!",
        choices=[
            ("Still fighting!", "* HAW! That's the determination I expect from my number one minion!!", "laughing"),
            ("Losing motivation...", "* Borrow some of my boiling fury then! Stand tall and finish it!!", "angry"),
        ],
        category="motivations",
    ),
    QuestionItem(
        question="* Put some boiling fury into your work! Smash through that task like a boss!",
        choices=[
            ("Fired up now!!", "* YES!! Burn with passion and obliterate every obstacle in your path!!", "overjoyed"),
            ("Need some calm.", "* Then channel cool focus! A master swordsman strikes with precision!", "wistful"),
        ],
        category="motivations",
    ),
    QuestionItem(
        question="* Take a deep breath! You've got this... not that I'm cheering for you or anything!",
        choices=[
            ("Thanks Pink! <3", "* W-WH-WHAT?! Don't look at me like that! Just get back to work, idiot!!", "embarrassed"),
            ("Needed that breath.", "* Hmph! See? A clear mind makes quick work of any enemy!", "peace_sign"),
        ],
        category="motivations",
    ),
    QuestionItem(
        question="* Even if today is exhausting, you're doing great! Keep your chin up, mew!",
        choices=[
            ("Doing my best!", "* And your best is more than enough! Keep walking forward proudly!!", "peace_sign"),
            ("Feeling exhausted.", "* Rest when you're done, champion. You've earned every bit of peace!", "wistful"),
        ],
        category="motivations",
    ),
    QuestionItem(
        question="* Channel your inner boss monster! Show this day who's really in charge!",
        choices=[
            ("I am in charge!", "* Exactly! Rule this desktop with confidence and sparkle magic!!", "laughing"),
            ("The day is winning.", "* NONSENSE! Boss monsters have multiple phases! Activate Phase Two!!", "overjoyed"),
        ],
        category="motivations",
    ),
    QuestionItem(
        question="* Every mistake is just training for the final battle! Keep pushing, mew!",
        choices=[
            ("Learning & growing!", "* That's how legends are born! Every setback is just XP in disguise!!", "peace_sign"),
            ("Hate making mistakes.", "* Mistakes mean you're in the arena fighting! Wear those scars with pride!!", "overjoyed"),
        ],
        category="motivations",
    ),
]

QUESTION_DIALOGUE_LINES: list[str] = [item.question for item in QUESTION_ITEMS]


DIALOGUE_LINES: dict[str, list[str]] = {
    # Idle / general thoughts during resting pauses (defaults to Variant 1; dynamically chosen by day)
    "idle": IDLE_DIALOGUE_VARIANTS[0],
    # Question / advice / motivation variant pool
    "question": QUESTION_DIALOGUE_LINES,
    # Startled by a click
    "shocked": [
        "* MEW!?",
        "* H-HEY!",
        "* Whoa!!",
    ],
    # Pestered / rapid clicks
    "angry": [
        "* STOP POKING ME!!",
        "* WANT A CAT BOMB?!",
        "* UNACCEPTABLE!!",
        "* CUT IT OUT!!",
    ],
    # Picked up / dragged
    "drag": [
        "* UNHAND ME!!",
        "* PUT ME DOWN, MEW!!",
    ],
    # Landed after fall / drop
    "land": [
        "* Oof! The dress!",
        "* Flawless landing!",
        "* 10 out of 10!",
        "* Perfect balance!",
    ],
    # Tongue
    "tongue": [
        "* :P",
    ],
    # Kneeling
    "kneeling": [
        "* Tactical pause for my joints...",
        "* Catching my breath!",
    ],
    # Burnt from window switch flashbang (dark -> bright light app)
    "burnt_switch": [
        "* MY EYES!!",
        "* AHH!! MY EYES!",
        "* GAH! SO BRIGHT!!",
        "* OW!! MY EYES!",
        "* AUGH! IT BURNS!",
        "* My eyes...!!",
        "* TOO BRIGHT!!",
        "* BLINDED!!",
    ],
    # Toby Fox song reaction ("this looks/sounds familiar")
    "toby_fox_familiar": [
        "* Wait... is this MY theme?!",
        "* Who put my battle music on?!",
        "* This song... fills me with rage and joy!",
        "* Did that little dog write this?!",
    ],
}

# --- Windows Startup ---------------------------------------------------------
STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_APP_NAME = "YellowsPixelBuddies"

log = logging.getLogger("yellows_pixel_buddies")


# =============================================================================
#  2. SMALL HELPERS
# =============================================================================

def is_run_at_startup_enabled() -> bool:
    """Check if the application is set to run at Windows logon in HKCU\\...\\Run."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, STARTUP_APP_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except OSError as err:
        log.debug("Error reading startup registry key: %s", err)
        return False


def get_startup_command() -> str:
    """Format the appropriate command string to launch the app on Windows startup."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    script_path = Path(__file__).resolve()
    exe_path = Path(sys.executable)
    pythonw_candidate = exe_path.with_name("pythonw.exe")
    if pythonw_candidate.exists():
        python_bin = str(pythonw_candidate)
    else:
        pw = shutil.which("pythonw")
        python_bin = pw if pw else sys.executable
    return f'"{python_bin}" "{script_path}"'


def set_run_at_startup(enable: bool) -> bool:
    """Add or remove the app from Windows startup (HKCU\\...\\Run)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                cmd = get_startup_command()
                winreg.SetValueEx(key, STARTUP_APP_NAME, 0, winreg.REG_SZ, cmd)
                log.info("Enabled Run at Startup: %s", cmd)
            else:
                try:
                    winreg.DeleteValue(key, STARTUP_APP_NAME)
                    log.info("Disabled Run at Startup")
                except FileNotFoundError:
                    pass
        return True
    except OSError as err:
        log.warning("Failed to update Run at Startup registry entry: %s", err)
        return False


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


def sample_screen_luminance() -> float:
    """Take a downscaled screen capture and return average perceived luminance (0-255)."""
    screen = QApplication.primaryScreen()
    if not screen:
        return 128.0
    pix = screen.grabWindow(0)
    if pix.isNull():
        return 128.0
    # Downscale to 16x16 using fast transformation for quick sampling (<15ms)
    small = pix.scaled(16, 16, Qt.IgnoreAspectRatio, Qt.FastTransformation).toImage()
    total_lum = 0.0
    for y in range(16):
        for x in range(16):
            c = small.pixelColor(x, y)
            total_lum += 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return total_lum / 256.0


def mirrored_key(state: str) -> str:
    """Name under which SpriteBank keeps the horizontally mirrored copy of a state's frames."""
    return f"{state}__mirrored"


def count_reversals(values: list[float], min_swing: float) -> int:
    """Count direction reversals in a 1-D path, ignoring wiggles of `min_swing` or less.

    A reversal is counted when the path turns back by MORE than `min_swing` from the furthest
    point it reached in its current direction. Tracking that extreme (rather than comparing
    neighbouring samples) counts a long swing sampled in many small steps once, and lets
    `min_swing` double as the dead zone that swallows pointer jitter.
    """
    if not values:
        return 0
    reversals = 0
    direction = 0              # +1 rising, -1 falling, 0 = has not yet moved `min_swing` from the start
    extreme = values[0]        # furthest value reached so far in the current direction
    for value in values[1:]:
        if direction == 0:
            if abs(value - extreme) > min_swing:      # the first real movement fixes the direction
                direction = 1 if value > extreme else -1
                extreme = value
        elif direction > 0:
            if value > extreme:
                extreme = value
            elif extreme - value > min_swing:         # turned back far enough: a reversal
                direction = -1
                extreme = value
                reversals += 1
        else:
            if value < extreme:
                extreme = value
            elif value - extreme > min_swing:
                direction = 1
                extreme = value
                reversals += 1
    return reversals


# --- Windows-only helpers --------------------------------------------------------
# Every call is guarded by sys.platform and a try/except, and degrades to a harmless
# "nothing happened" elsewhere (other OS, missing DLL, API failure).

VK_LBUTTON, VK_RBUTTON, VK_MBUTTON = 0x01, 0x02, 0x04   # GetAsyncKeyState virtual-key codes
GWL_EXSTYLE = -20                                       # SetWindowLongPtr index: extended window style
WS_EX_LAYERED = 0x00080000                              # per-pixel-alpha window (Qt sets it for us)
WS_EX_TRANSPARENT = 0x00000020                          # layered + this: the mouse falls straight through


@lru_cache(maxsize=1)
def _user32():
    """A private handle to user32.dll, or None off Windows / when it cannot be loaded.

    Cached, so the lookup (and a possible warning) happens only once.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        dll = ctypes.WinDLL("user32")
        dll.GetAsyncKeyState.argtypes = [ctypes.c_int]
        dll.GetAsyncKeyState.restype = ctypes.c_short      # SHORT: the top bit means "down"
        return dll
    except Exception as exc:                               # ctypes / DLL missing, odd Python build ...
        log.warning("user32.dll is not usable (%s) - mouse-button detection, window monitoring, "
                    "and click-through while hanging are off", exc)
        return None


def any_mouse_button_down() -> bool:
    """True while the left, right or middle mouse button is held ANYWHERE on the system.

    QApplication.mouseButtons() only reflects events delivered to this application, so a drag
    or a text selection in another window would go unnoticed. GetAsyncKeyState reads the
    physical button state instead (physical, not logical, which is fine because all three
    buttons are checked). Fails safe to "not held": other OS, no user32, or any error.
    """
    dll = _user32()
    if dll is None:
        return False
    try:
        return any(dll.GetAsyncKeyState(vk) & 0x8000       # top bit = down right now
                   for vk in (VK_LBUTTON, VK_RBUTTON, VK_MBUTTON))
    except Exception:
        return False


def set_window_input_transparent(widget: QWidget, enabled: bool) -> bool:
    """Make the mouse pass straight through `widget` (True) or catch it again (False).

    Toggling WS_EX_TRANSPARENT on a layered window changes only the hit-testing ("treat me as not there"),
    so the picture and the normal per-frame mask stay exactly as they are.

    Returns True when the request took effect, False if it could not be done.
    """
    dll = _user32()
    if dll is None:
        return False
    try:
        import ctypes
        get_style = getattr(dll, "GetWindowLongPtrW", None) or dll.GetWindowLongW   # 32-bit Python fallback
        set_style = getattr(dll, "SetWindowLongPtrW", None) or dll.SetWindowLongW
        get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
        get_style.restype = ctypes.c_ssize_t
        set_style.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        set_style.restype = ctypes.c_ssize_t

        hwnd = int(widget.winId())
        style = get_style(hwnd, GWL_EXSTYLE)
        if style == 0:                  # a Qt tool window always has style bits: 0 = the call failed
            return False
        wanted = (style | WS_EX_TRANSPARENT) if enabled else (style & ~WS_EX_TRANSPARENT)
        if wanted != style:
            set_style(hwnd, GWL_EXSTYLE, wanted)
        return (not enabled) or bool(wanted & WS_EX_LAYERED)
    except Exception as exc:
        log.warning("Could not change the window's click-through style (%s)", exc)
        return False


def check_jump_config() -> None:
    """Fail early, with a readable message, on impossible values in the jump settings."""
    if AIRBORNE_ART_FACES not in ("left", "right"):
        raise ValueError(f'AIRBORNE_ART_FACES must be "left" or "right", not {AIRBORNE_ART_FACES!r}')
    if HANGING_ART_FACES not in ("none", "left", "right"):
        raise ValueError(f'HANGING_ART_FACES must be "none", "left" or "right", not {HANGING_ART_FACES!r}')
    if len(HAND_ANCHOR) != 2 or not all(0.0 <= f <= 1.0 for f in HAND_ANCHOR):
        raise ValueError(f"HAND_ANCHOR must be two fractions between 0 and 1, not {HAND_ANCHOR!r}")


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
                "run_left": -0.025, "run_right": 0.025,
                "wistful_walk_left": -0.025, "wistful_walk_right": 0.025}.get(state, 0.0) * size

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


def fit_into_canvas(src: QImage, canvas_w: int, canvas_h: int | None = None) -> QImage:
    """Scale `src` to fit a transparent canvas, anchored bottom-centre.

    If canvas_h is None, the canvas is square (canvas_w x canvas_w).
    Anchoring at the bottom keeps the feet on the ground even when the sprites
    of different states have different sizes.
    """
    if canvas_h is None:
        canvas_h = canvas_w
    mode = Qt.SmoothTransformation if SMOOTH_SCALING else Qt.FastTransformation
    scaled = src.scaled(canvas_w, canvas_h, Qt.KeepAspectRatio, mode)
    canvas = QImage(canvas_w, canvas_h, QImage.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.drawImage((canvas_w - scaled.width()) // 2, canvas_h - scaled.height(), scaled)
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
            if state in ("wistful_walk_left", "wistful_walk_right"):
                continue   # derived from wistful below
            images = self._load_state(sprites_dir, state)
            if images:
                self._sources[state] = images
        if MIRROR_WALK_RIGHT_FOR_LEFT and "walk_right" in self._sources:
            self._sources["walk_left"] = [img.mirrored(True, False)   # flip horizontally
                                          for img in self._sources["walk_right"]]
        if MIRROR_RUN_RIGHT_FOR_LEFT and "run_right" in self._sources:
            self._sources["run_left"] = [img.mirrored(True, False)    # flip horizontally
                                         for img in self._sources["run_right"]]
            self._real.add("run_left")   # real exactly when run_right is

        if "wistful" in self._sources:
            # Sourced from sprites/wistful: left-facing by default, right-facing is horizontally mirrored
            w_imgs = self._sources["wistful"]
            self._sources["wistful_walk_left"] = [img.copy() for img in w_imgs]
            self._sources["wistful_walk_right"] = [img.mirrored(True, False) for img in w_imgs]
            if self.has_real_sprites("wistful"):
                self._real.add("wistful_walk_left")
                self._real.add("wistful_walk_right")

        # The jump art is authored facing ONE way, so keep a mirrored copy for the other way
        # (derived like MIRROR_WALK_RIGHT_FOR_LEFT does it). airborne always needs one; hanging
        # only when HANGING_ART_FACES says it is not front-facing.
        for state in (AIRBORNE_STATE, THROW_STATE, GHOST_STATE) + ((HANGING_STATE,) if HANGING_ART_FACES != "none" else ()):
            if state in self._sources:
                self._sources[mirrored_key(state)] = [img.mirrored(True, False)   # flip horizontally
                                                      for img in self._sources[state]]

        # Pre-rotate horizontal laser beam segments (rotated 90 degrees)
        if "laser_extend" in self._sources:
            self._sources["laser_extend_horiz"] = [img.transformed(QTransform().rotate(90))
                                                   for img in self._sources["laser_extend"]]
            if self.has_real_sprites("laser_extend"):
                self._real.add("laser_extend_horiz")

        # One startup line: which new states have sprites and which will never be used,
        # and whether the jump to the cursor can run (it needs BOTH jump states).
        found = [s for s in NEW_STATES if self.has_real_sprites(s)]
        skipped = [s for s in NEW_STATES if s not in found]
        missing_jump = [s for s in JUMP_STATES if not self.has_real_sprites(s)]
        log.info("New states found: %s | skipped (no sprites): %s | jump to cursor: %s",
                 ", ".join(found) or "none", ", ".join(skipped) or "none",
                 "ENABLED" if not missing_jump
                 else "disabled (needs real PNGs in BOTH folders; missing: " + ", ".join(missing_jump) + ")")

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

    @property
    def jump_sprites_ready(self) -> bool:
        """True when BOTH jump states (airborne, hanging) are drawn from real PNGs.

        Only then does the pet jump at the cursor; with one folder missing the whole
        feature stays off and she behaves exactly as before.
        """
        return all(self.has_real_sprites(s) for s in JUMP_STATES)

    def rebuild(self, dpr: float) -> None:
        """(Re)render all frames for a display scale factor (1.0, 1.25, 1.5, 2.0 ...)."""
        for state, images in self._sources.items():
            size_spec = EFFECT_SIZES.get(state, SPRITE_SIZE)
            if isinstance(size_spec, (tuple, list)):
                log_w, log_h = int(size_spec[0]), int(size_spec[1])
            else:
                log_w, log_h = int(size_spec), int(size_spec)

            phys_w = max(1, round(log_w * dpr))
            phys_h = max(1, round(log_h * dpr))
            exact_dpr = phys_h / log_h
            built = []
            for img in images:
                canvas = fit_into_canvas(img, phys_w, phys_h)
                pixmap = QPixmap.fromImage(canvas)
                pixmap.setDevicePixelRatio(exact_dpr)

                # Window masks are expressed in logical px, so derive the mask from a
                # logical-size canvas (identical to `canvas` when dpr == 1).
                logical_canvas = canvas if (phys_w == log_w and phys_h == log_h) \
                    else fit_into_canvas(img, log_w, log_h)
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
    FALL = auto()    # dropped / let go, falling back to the taskbar
    JUMP = auto()    # leaping at the cursor: the rise, and the fall after a miss
    HANG = auto()    # hanging from the cursor (no gravity, no walking)
    THROW = auto()   # bomb barrage floating mid-air (stops hanging from cursor)
    HIDE_PEEK = auto()        # hiding behind taskbar: only ears visible at bottom-right
    SUMMON_DIALOGUE = auto()  # dialogue playing after ears clicked ("...", "..?")
    SUMMON_INTRO = auto()     # ghost rises FAST, looks R&L, flies off right, shocked pops in
    HIDE_OUTRO = auto()       # runs right, ghost enters, slowly sinks into hide state
    EXIT_OUTRO = auto()       # runs to furthest screen edge and quits when offscreen


class VfxOverlay(QWidget):
    """A frameless, translucent, click-through overlay window for large visual effects."""

    def __init__(self) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFixedSize(EXPLOSION_SIZE, EXPLOSION_SIZE)
        self._pixmap: QPixmap | None = None

    def show_frame(self, pixmap: QPixmap, bottom_center_x: float, bottom_y: float,
                   ground_ratio: float = 1.0) -> None:
        """Position and show a frame centered horizontally above the given bottom anchor."""
        self._pixmap = pixmap
        dpr = pixmap.devicePixelRatio() if pixmap.devicePixelRatio() > 0 else 1.0
        w = round(pixmap.width() / dpr)
        h = round(pixmap.height() / dpr)
        if self.width() != w or self.height() != h:
            self.setFixedSize(w, h)
        target_x = round(bottom_center_x - w / 2.0)
        baseline_y = round(h * ground_ratio)
        target_y = round(bottom_y - baseline_y)
        target_pos = QPoint(target_x, target_y)
        if self.pos() != target_pos:
            self.move(target_pos)
        if not self.isVisible():
            self.show()
        self.raise_()
        set_window_input_transparent(self, True)
        self.update()

    def dismiss(self) -> None:
        """Hide and clear the overlay."""
        self._pixmap = None
        if self.isVisible():
            self.hide()

    def paintEvent(self, event) -> None:
        if self._pixmap is None:
            return
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.drawPixmap(0, 0, self._pixmap)
        painter.end()


class DialogueOverlay(QWidget):
    """A frameless, translucent speech bubble overlay that displays text with a typewriter effect."""

    dismissed = pyqtSignal()

    def __init__(self, font_family: str, box_png_path: Path) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

        self._font_family = font_family
        self._box_src: QImage | None = None
        if box_png_path.exists():
            img = QImage(str(box_png_path))
            if not img.isNull():
                self._box_src = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)

        self._active = False
        self._full_text = ""
        self._lines: list[str] = []
        self._visible_chars = 0
        self._total_chars = 0
        self._char_delay_ticks = 0
        self._scale = DIALOGUE_BOX_SCALE

        self._cached_bg: QPixmap | None = None
        self._text_start_x = 0
        self._text_start_y = 0
        self._line_h = 24

        self._queue: list[str] = []
        self._last_pet_x: float = 0.0
        self._last_pet_y: float = 0.0

        # Choices / question answering state
        self._choices: list[tuple[str, str, str | None]] = []
        self._choice_rects: list[QRect] = []
        self._hovered_choice_idx: int | None = None
        self._on_chosen_callback = None
        self._soul_heart_pix: QPixmap | None = self._create_soul_heart_pixmap()

        self._font = QFont(self._font_family)
        self._font.setPixelSize(DIALOGUE_FONT_PIXEL_SIZE)
        self._font.setStyleStrategy(QFont.NoAntialias)

        self._type_timer = QTimer(self)
        self._type_timer.setInterval(DIALOGUE_TYPEWRITER_MS)
        self._type_timer.timeout.connect(self._type_tick)

        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self.dismiss)
        self._skippable = True

    def _create_soul_heart_pixmap(self) -> QPixmap:
        """Create a crisp pixel-art Deltarune red soul heart pixmap."""
        grid = [
            " 11   11 ",
            "1111 1111",
            "111111111",
            "111111111",
            " 1111111 ",
            "  11111  ",
            "   111   ",
            "    1    ",
        ]
        h = len(grid)
        w = len(grid[0])
        scale = max(1, round(self._scale))
        img = QImage(w * scale, h * scale, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        red = QColor(255, 0, 64, 255).rgba()
        for y, row in enumerate(grid):
            for x, c in enumerate(row):
                if c == '1':
                    for sy in range(scale):
                        for sx in range(scale):
                            img.setPixel(x * scale + sx, y * scale + sy, red)
        return QPixmap.fromImage(img)

    def is_active(self) -> bool:
        """True if a dialogue line is actively being displayed or typed."""
        return self._active

    def is_skippable(self) -> bool:
        """True if the dialogue bubble can be fast-forwarded or dismissed by clicks."""
        return self._skippable

    def ask(self, text: str, choices: list[tuple[str, str, str | None]], pet_x: float, pet_y: float,
            on_chosen) -> None:
        """Start a new question dialogue bubble with interactive choices."""
        self._skippable = True
        self._queue.clear()
        self._choices = list(choices)
        self._choice_rects.clear()
        self._hovered_choice_idx = None
        self._on_chosen_callback = on_chosen
        self._last_pet_x = pet_x
        self._last_pet_y = pet_y
        self._display_text(text, pet_x, pet_y)

    def say(self, text: str, pet_x: float, pet_y: float, queue: list[str] | None = None, skippable: bool = True) -> None:
        """Start a new speech bubble with typewriter animation beside the pet's head.

        queue: optional list of additional messages to display sequentially after this one.
        skippable: whether clicking can advance or dismiss this dialogue.
        """
        self._choices.clear()
        self._choice_rects.clear()
        self._hovered_choice_idx = None
        self._on_chosen_callback = None
        self._skippable = skippable
        self._queue = list(queue) if queue else []
        self._last_pet_x = pet_x
        self._last_pet_y = pet_y
        self._display_text(text, pet_x, pet_y)

    def _display_text(self, text: str, pet_x: float, pet_y: float) -> None:
        """Render and begin typing a single dialogue bubble."""
        self._hold_timer.stop()
        self._type_timer.stop()
        self._last_pet_x = pet_x
        self._last_pet_y = pet_y

        self._full_text = text
        self._visible_chars = 0
        self._char_delay_ticks = 0

        fm = QFontMetrics(self._font)
        self._line_h = fm.height()

        # Wrap text nicely
        self._lines = []
        for para in text.split('\n'):
            words = para.split(' ')
            cur = []
            for w in words:
                test = ' '.join(cur + [w])
                if cur and fm.horizontalAdvance(test) > DIALOGUE_MAX_WIDTH_PX:
                    self._lines.append(' '.join(cur))
                    cur = ['  ' + w] if para.startswith('* ') else [w]
                else:
                    cur.append(w)
            if cur:
                self._lines.append(' '.join(cur))

        self._total_chars = sum(len(l) for l in self._lines)
        max_text_w = max((fm.horizontalAdvance(l) for l in self._lines), default=60)
        total_text_h = self._line_h * len(self._lines)

        scale = self._scale
        c_l = round(14 * scale)
        c_r = round(14 * scale)
        c_t = round(12 * scale)
        c_b = round(12 * scale)

        pad_x = round(4 * scale)
        pad_y = round(2 * scale)

        base_inner_w = round(84 * scale)
        base_inner_h = round(19 * scale)

        # Calculate choice block dimensions
        choices_w = 0
        choices_h = 0
        pad_choices_top = round(5 * scale) if self._choices else 0
        self._choice_rects.clear()

        if self._choices:
            heart_w = self._soul_heart_pix.width() if self._soul_heart_pix else 12
            heart_gap = 4
            prefix_w = heart_w + heart_gap
            choice_widths = [prefix_w + fm.horizontalAdvance(c[0]) for c in self._choices]
            choice_gap = 14
            total_inline_w = sum(choice_widths) + (len(self._choices) - 1) * choice_gap

            if total_inline_w <= DIALOGUE_MAX_WIDTH_PX + 20:
                choices_w = total_inline_w
                choices_h = self._line_h
            else:
                choices_w = max(choice_widths, default=0)
                choices_h = self._line_h * len(self._choices) + 2 * (len(self._choices) - 1)

        req_inner_w = max(max_text_w, choices_w) + pad_x * 2
        req_inner_h = total_text_h + (choices_h + pad_choices_top if self._choices else 0) + pad_y * 2

        extra_w = max(0, req_inner_w - base_inner_w)
        extra_h = max(0, req_inner_h - base_inner_h)

        box_w = round(108 * scale) + extra_w
        box_h = round(33 * scale) + extra_h

        # Build 9-slice background
        bg_img = QImage(box_w, box_h, QImage.Format_ARGB32_Premultiplied)
        bg_img.fill(Qt.transparent)
        p = QPainter(bg_img)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)

        if self._box_src is not None:
            mid_w = box_w - c_l - c_r
            mid_h = box_h - c_t - c_b

            # Corners
            p.drawImage(QRect(0, 0, c_l, c_t), self._box_src, QRect(0, 0, 14, 12))
            p.drawImage(QRect(box_w - c_r, 0, c_r, c_t), self._box_src, QRect(94, 0, 14, 12))
            p.drawImage(QRect(0, box_h - c_b, c_l, c_b), self._box_src, QRect(0, 21, 14, 12))
            p.drawImage(QRect(box_w - c_r, box_h - c_b, c_r, c_b), self._box_src, QRect(94, 21, 14, 12))

            # Edges
            p.drawImage(QRect(c_l, 0, mid_w, c_t), self._box_src, QRect(14, 0, 80, 12))
            p.drawImage(QRect(c_l, box_h - c_b, mid_w, c_b), self._box_src, QRect(14, 21, 80, 12))
            p.drawImage(QRect(0, c_t, c_l, mid_h), self._box_src, QRect(0, 12, 14, 9))
            p.drawImage(QRect(box_w - c_r, c_t, c_r, mid_h), self._box_src, QRect(94, 12, 14, 9))

            # Center
            p.drawImage(QRect(c_l, c_t, mid_w, mid_h), self._box_src, QRect(14, 12, 80, 9))
        else:
            p.fillRect(QRect(0, 0, box_w, box_h), QColor(0, 0, 0, 230))
            p.setPen(QColor(255, 255, 255))
            p.drawRect(0, 0, box_w - 1, box_h - 1)

        p.end()

        actual_inner_h = box_h - round(14 * scale)
        total_content_h = total_text_h + (choices_h + pad_choices_top if self._choices else 0)
        self._text_start_y = round(7 * scale) + (actual_inner_h - total_content_h) // 2 + fm.ascent()
        self._text_start_x = round(12 * scale) + pad_x

        # Compute choice rects relative to text
        if self._choices:
            heart_w = self._soul_heart_pix.width() if self._soul_heart_pix else 12
            heart_gap = 4
            prefix_w = heart_w + heart_gap
            choice_widths = [prefix_w + fm.horizontalAdvance(c[0]) for c in self._choices]
            choice_gap = 14
            total_inline_w = sum(choice_widths) + (len(self._choices) - 1) * choice_gap

            last_text_baseline_y = self._text_start_y + (len(self._lines) - 1) * self._line_h
            cy = last_text_baseline_y + fm.descent() + pad_choices_top

            if total_inline_w <= DIALOGUE_MAX_WIDTH_PX + 20:
                cx = self._text_start_x
                for i, cw in enumerate(choice_widths):
                    self._choice_rects.append(QRect(cx, cy, cw + 4, self._line_h))
                    cx += cw + choice_gap
            else:
                for i, cw in enumerate(choice_widths):
                    row_y = cy + i * (self._line_h + 2)
                    self._choice_rects.append(QRect(self._text_start_x, row_y, cw + 4, self._line_h))

        self._cached_bg = QPixmap.fromImage(bg_img)
        self.setFixedSize(box_w, box_h)
        self.setMask(QRegion(self._cached_bg.mask()))

        self._active = True
        self.update_position(pet_x, pet_y)
        self.show()
        self.raise_()
        self._type_timer.start()

    def update_position(self, pet_x: float, pet_y: float) -> None:
        """Position the dialogue bubble beside the pet's head (left or right depends on screen half)."""
        self._last_pet_x = pet_x
        self._last_pet_y = pet_y
        if not self._active:
            return
        area = QApplication.primaryScreen().availableGeometry()
        w = self.width()
        h = self.height()

        screen_mid_x = area.x() + area.width() / 2.0
        pet_center_x = pet_x + SPRITE_SIZE / 2.0

        # Position beside subject's head: left or right depends on which half of the screen she is on
        if pet_center_x < screen_mid_x:
            # On left half -> bubble sits to the right of her head
            target_x = pet_x + SPRITE_SIZE + DIALOGUE_SIDE_OFFSET_PX
        else:
            # On right half -> bubble sits to the left of her head
            target_x = pet_x - w - DIALOGUE_SIDE_OFFSET_PX

        # Vertically align beside the head
        head_center_y = pet_y + (SPRITE_SIZE * DIALOGUE_HEAD_Y_RATIO)
        target_y = head_center_y - (h / 2.0)

        # Clamp within screen bounds
        min_x = float(area.x() + 4)
        max_x = max(min_x, float(area.x() + area.width() - w - 4))
        target_x = min(max(target_x, min_x), max_x)

        min_y = float(area.y() + 4)
        max_y = max(min_y, float(area.y() + area.height() - h - 4))
        target_y = min(max(target_y, min_y), max_y)

        pos = QPoint(round(target_x), round(target_y))
        if self.pos() != pos:
            self.move(pos)

    def _type_tick(self) -> None:
        """Advance typewriter character count, inserting subtle pauses at punctuation."""
        if not self._active:
            self._type_timer.stop()
            return

        if self._char_delay_ticks > 0:
            self._char_delay_ticks -= 1
            return

        if self._visible_chars < self._total_chars:
            curr = 0
            target_char = ''
            for line in self._lines:
                if self._visible_chars < curr + len(line):
                    target_char = line[self._visible_chars - curr]
                    break
                curr += len(line)

            self._visible_chars += 1
            if target_char in ('.', '!', '?'):
                self._char_delay_ticks = DIALOGUE_PUNCTUATION_PAUSE_TICKS
            elif target_char in (',', ';', ':'):
                self._char_delay_ticks = DIALOGUE_PUNCTUATION_PAUSE_TICKS // 2

            self.update()
        else:
            self._type_timer.stop()
            if self._choices:
                self._hold_timer.start(round(DIALOGUE_QUESTION_HOLD_S * 1000))
            else:
                hold_s = max(DIALOGUE_HOLD_MIN_S, self._total_chars * DIALOGUE_HOLD_PER_CHAR_S)
                self._hold_timer.start(round(hold_s * 1000))
            self.update()

    def dismiss(self, clear_queue: bool = False) -> None:
        """Hide and clear the dialogue overlay, or advance to the next queued message."""
        if clear_queue:
            self._queue.clear()

        self._choices.clear()
        self._choice_rects.clear()
        self._hovered_choice_idx = None
        self._on_chosen_callback = None
        self.setCursor(Qt.ArrowCursor)

        if self._queue:
            next_text = self._queue.pop(0)
            self._display_text(next_text, self._last_pet_x, self._last_pet_y)
            return

        self._active = False
        self._type_timer.stop()
        self._hold_timer.stop()
        self.clearMask()
        self.hide()
        self.dismissed.emit()

    def advance_or_dismiss(self) -> None:
        """Fast-forward typewriter if typing, or dismiss/advance queue if already complete."""
        if not self._active or not self._skippable:
            return
        if self._visible_chars < self._total_chars:
            self._visible_chars = self._total_chars
            self._char_delay_ticks = 0
            self._type_timer.stop()
            if self._choices:
                self._hold_timer.start(round(DIALOGUE_QUESTION_HOLD_S * 1000))
            else:
                hold_s = max(DIALOGUE_HOLD_MIN_S, self._total_chars * DIALOGUE_HOLD_PER_CHAR_S)
                self._hold_timer.start(round(hold_s * 1000))
            self.update()
        elif not self._choices:
            self.dismiss()

    def _choose_option(self, idx: int) -> None:
        """Player clicked a choice option: invoke callback with reaction text and anim."""
        if not self._choices or idx < 0 or idx >= len(self._choices):
            return
        choice_label, reaction_text, reaction_anim = self._choices[idx]
        self._choices.clear()
        self._choice_rects.clear()
        self._hovered_choice_idx = None
        self.setCursor(Qt.ArrowCursor)
        callback = self._on_chosen_callback
        self._on_chosen_callback = None
        if callback:
            callback(reaction_text, reaction_anim)

    def mouseMoveEvent(self, event) -> None:
        """Track mouse hover across choice options to highlight selection with Deltarune soul heart."""
        if not self._active or not self._choices or self._visible_chars < self._total_chars:
            super().mouseMoveEvent(event)
            return
        pos = event.pos()
        hovered = None
        for i, r in enumerate(self._choice_rects):
            if r.contains(pos):
                hovered = i
                break
        if hovered != self._hovered_choice_idx:
            self._hovered_choice_idx = hovered
            if hovered is not None:
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            self.update()
        event.accept()

    def leaveEvent(self, event) -> None:
        """Reset choice hover and cursor when mouse leaves the dialogue bubble."""
        if self._hovered_choice_idx is not None:
            self._hovered_choice_idx = None
            self.setCursor(Qt.ArrowCursor)
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        """Left-click fast-forwards typewriter or selects a choice option."""
        if not self._skippable or not self._active:
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            if self._visible_chars < self._total_chars:
                self.advance_or_dismiss()
                event.accept()
                return
            if self._choices:
                pos = event.pos()
                for i, r in enumerate(self._choice_rects):
                    if r.contains(pos):
                        self._choose_option(i)
                        event.accept()
                        return
                event.accept()
                return
            if DIALOGUE_CLICK_TO_DISMISS:
                self.advance_or_dismiss()
                event.accept()
        else:
            super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        if not self._active or self._cached_bg is None:
            return

        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.drawPixmap(0, 0, self._cached_bg)

        painter.setFont(self._font)
        painter.setPen(QColor(255, 255, 255))

        ty = self._text_start_y
        chars_left = self._visible_chars
        for line in self._lines:
            if chars_left <= 0:
                break
            if len(line) <= chars_left:
                painter.drawText(self._text_start_x, ty, line)
                chars_left -= len(line)
            else:
                painter.drawText(self._text_start_x, ty, line[:chars_left])
                chars_left = 0
            ty += self._line_h

        # Draw choices if question typing is complete
        if self._choices and self._visible_chars >= self._total_chars:
            fm = QFontMetrics(self._font)
            heart_w = self._soul_heart_pix.width() if self._soul_heart_pix else 12
            heart_h = self._soul_heart_pix.height() if self._soul_heart_pix else 10
            heart_gap = 4
            prefix_w = heart_w + heart_gap

            for i, (label, _, _) in enumerate(self._choices):
                if i >= len(self._choice_rects):
                    break
                rect = self._choice_rects[i]
                is_hovered = (self._hovered_choice_idx == i)

                # Deltarune soul heart on hovered option
                if is_hovered and self._soul_heart_pix:
                    hx = rect.x()
                    hy = rect.y() + (rect.height() - heart_h) // 2
                    painter.drawPixmap(hx, hy, self._soul_heart_pix)

                # Yellow highlight on hovered, white on unhovered
                if is_hovered:
                    painter.setPen(QColor(255, 255, 0))
                else:
                    painter.setPen(QColor(255, 255, 255))

                tx = rect.x() + prefix_w
                ty_choice = rect.y() + fm.ascent()
                painter.drawText(tx, ty_choice, label)

        painter.end()


class ChatLineEdit(QLineEdit):
    """A QLineEdit that emits escapePressed when the Esc key is hit."""

    escapePressed = pyqtSignal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.escapePressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ChatInputOverlay(QWidget):
    """A frameless, translucent text input bar styled after Deltarune dialogue boxes."""

    submitted = pyqtSignal(str, bool)
    cancelled = pyqtSignal()

    def __init__(self, font_family: str, box_png_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._font_family = font_family
        self._box_src: QImage | None = None
        if box_png_path.exists():
            img = QImage(str(box_png_path))
            if not img.isNull():
                self._box_src = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)

        self._scale = DIALOGUE_BOX_SCALE
        self._cached_bg: QPixmap | None = None
        self._soul_heart_pix: QPixmap | None = self._create_soul_heart_pixmap()

        self._init_ui()

    def _create_soul_heart_pixmap(self) -> QPixmap:
        """Create a crisp pixel-art Deltarune red soul heart pixmap."""
        grid = [
            " 11   11 ",
            "1111 1111",
            "111111111",
            "111111111",
            " 1111111 ",
            "  11111  ",
            "   111   ",
            "    1    ",
        ]
        h = len(grid)
        w = len(grid[0])
        scale = max(1, round(self._scale))
        img = QImage(w * scale, h * scale, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        red = QColor(255, 0, 64, 255).rgba()
        for y, row in enumerate(grid):
            for x, c in enumerate(row):
                if c == '1':
                    for sy in range(scale):
                        for sx in range(scale):
                            img.setPixel(x * scale + sx, y * scale + sy, red)
        return QPixmap.fromImage(img)

    def _init_ui(self) -> None:
        font = QFont(self._font_family)
        font.setPixelSize(DIALOGUE_FONT_PIXEL_SIZE)
        font.setStyleStrategy(QFont.NoAntialias)

        layout = QHBoxLayout(self)
        pad_h = round(16 * self._scale)
        pad_v = round(7 * self._scale)
        layout.setContentsMargins(pad_h, pad_v, pad_h, pad_v)
        layout.setSpacing(6)

        # Soul heart indicator
        self._heart_label = QLabel(self)
        if self._soul_heart_pix:
            self._heart_label.setPixmap(self._soul_heart_pix)
            self._heart_label.setFixedSize(self._soul_heart_pix.size())
        self._heart_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._heart_label)

        # Asterisk
        self._star_label = QLabel("*", self)
        self._star_label.setFont(font)
        self._star_label.setStyleSheet("color: #FFFFFF;")
        layout.addWidget(self._star_label)

        # Input text field
        self._line_edit = ChatLineEdit(self)
        self._line_edit.setFont(font)
        self._line_edit.setPlaceholderText("Talk to Pink... (Enter to send)")
        pal = self._line_edit.palette()
        pal.setColor(QPalette.PlaceholderText, QColor(140, 140, 140))
        self._line_edit.setPalette(pal)
        self._line_edit.setStyleSheet(
            "QLineEdit {"
            "  background: transparent;"
            "  border: none;"
            "  color: #FFFFFF;"
            "  selection-background-color: #FFFF00;"
            "  selection-color: #000000;"
            "}"
        )
        self._line_edit.returnPressed.connect(self._on_submit)
        self._line_edit.escapePressed.connect(self.cancel)
        layout.addWidget(self._line_edit, stretch=1)

        # Screen vision toggle button
        self._vision_btn = QPushButton("👁️", self)
        self._vision_btn.setFont(font)
        self._vision_btn.setCursor(Qt.PointingHandCursor)
        self._vision_btn.setCheckable(True)
        self._vision_btn.setChecked(False)
        self._vision_btn.setToolTip("Toggle Screen Vision (Let Pink see your screen)")
        self._vision_btn.setFixedHeight(round(18 * self._scale))
        self._vision_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #000000;"
            "  color: #888888;"
            "  border: 1px solid #555555;"
            "  padding: 0px 5px;"
            "  font-size: 11px;"
            "}"
            "QPushButton:hover {"
            "  color: #00FFFF;"
            "  border: 1px solid #00FFFF;"
            "}"
            "QPushButton:checked {"
            "  background-color: #00FFFF;"
            "  color: #000000;"
            "  border: 1px solid #00FFFF;"
            "}"
        )
        layout.addWidget(self._vision_btn)

        # Send button
        self._send_btn = QPushButton("Send", self)
        self._send_btn.setFont(font)
        self._send_btn.setCursor(Qt.PointingHandCursor)
        self._send_btn.setFixedHeight(round(18 * self._scale))
        self._send_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #000000;"
            "  color: #FFFF00;"
            "  border: 1px solid #FFFF00;"
            "  padding: 0px 8px;"
            "  font-weight: bold;"
            "}"
            "QPushButton:hover {"
            "  background-color: #FFFF00;"
            "  color: #000000;"
            "}"
            "QPushButton:pressed {"
            "  background-color: #FFA500;"
            "  color: #000000;"
            "}"
        )
        self._send_btn.clicked.connect(self._on_submit)
        layout.addWidget(self._send_btn)

        # Close button
        self._close_btn = QPushButton("×", self)
        self._close_btn.setFont(font)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setFixedHeight(round(18 * self._scale))
        self._close_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: transparent;"
            "  color: #888888;"
            "  border: none;"
            "  padding: 0px 4px;"
            "  font-size: 14px;"
            "  font-weight: bold;"
            "}"
            "QPushButton:hover {"
            "  color: #FF5555;"
            "}"
        )
        self._close_btn.clicked.connect(self.cancel)
        layout.addWidget(self._close_btn)

        box_w = round(270 * self._scale)
        box_h = round(34 * self._scale)
        self.setFixedSize(box_w, box_h)
        self._build_background(box_w, box_h)

    def _build_background(self, box_w: int, box_h: int) -> None:
        scale = self._scale
        c_l = round(14 * scale)
        c_r = round(14 * scale)
        c_t = round(12 * scale)
        c_b = round(12 * scale)

        bg_img = QImage(box_w, box_h, QImage.Format_ARGB32_Premultiplied)
        bg_img.fill(Qt.transparent)
        p = QPainter(bg_img)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)

        if self._box_src is not None:
            mid_w = box_w - c_l - c_r
            mid_h = box_h - c_t - c_b

            # Corners
            p.drawImage(QRect(0, 0, c_l, c_t), self._box_src, QRect(0, 0, 14, 12))
            p.drawImage(QRect(box_w - c_r, 0, c_r, c_t), self._box_src, QRect(94, 0, 14, 12))
            p.drawImage(QRect(0, box_h - c_b, c_l, c_b), self._box_src, QRect(0, 21, 14, 12))
            p.drawImage(QRect(box_w - c_r, box_h - c_b, c_r, c_b), self._box_src, QRect(94, 21, 14, 12))

            # Edges
            p.drawImage(QRect(c_l, 0, mid_w, c_t), self._box_src, QRect(14, 0, 80, 12))
            p.drawImage(QRect(c_l, box_h - c_b, mid_w, c_b), self._box_src, QRect(14, 21, 80, 12))
            p.drawImage(QRect(0, c_t, c_l, mid_h), self._box_src, QRect(0, 12, 14, 9))
            p.drawImage(QRect(box_w - c_r, c_t, c_r, mid_h), self._box_src, QRect(94, 12, 14, 9))

            # Center
            p.drawImage(QRect(c_l, c_t, mid_w, mid_h), self._box_src, QRect(14, 12, 80, 9))
        else:
            p.fillRect(QRect(0, 0, box_w, box_h), QColor(0, 0, 0, 230))
            p.setPen(QColor(255, 255, 255))
            p.drawRect(0, 0, box_w - 1, box_h - 1)

        p.end()
        self._cached_bg = QPixmap.fromImage(bg_img)
        self.setMask(QRegion(self._cached_bg.mask()))

    def paintEvent(self, event) -> None:
        if self._cached_bg is None:
            return
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.drawPixmap(0, 0, self._cached_bg)
        painter.end()

    def update_position(self, pet_x: float, pet_y: float) -> None:
        area = QApplication.primaryScreen().availableGeometry()
        w = self.width()
        h = self.height()

        screen_mid_x = area.x() + area.width() / 2.0
        pet_center_x = pet_x + SPRITE_SIZE / 2.0

        if pet_center_x < screen_mid_x:
            target_x = pet_x + SPRITE_SIZE + DIALOGUE_SIDE_OFFSET_PX
        else:
            target_x = pet_x - w - DIALOGUE_SIDE_OFFSET_PX

        head_center_y = pet_y + (SPRITE_SIZE * DIALOGUE_HEAD_Y_RATIO)
        target_y = head_center_y - (h / 2.0)

        min_x = float(area.x() + 4)
        max_x = max(min_x, float(area.x() + area.width() - w - 4))
        target_x = min(max(target_x, min_x), max_x)

        min_y = float(area.y() + 4)
        max_y = max(min_y, float(area.y() + area.height() - h - 4))
        target_y = min(max(target_y, min_y), max_y)

        self.move(round(target_x), round(target_y))

    def open_at(self, pet_x: float, pet_y: float) -> None:
        self.update_position(pet_x, pet_y)
        self._line_edit.clear()
        self.show()
        self.raise_()
        self.activateWindow()
        self._line_edit.setFocus()

    def cancel(self) -> None:
        self.hide()
        self.cancelled.emit()

    def _on_submit(self) -> None:
        text = self._line_edit.text().strip()
        see_screen = self._vision_btn.isChecked()
        self.hide()
        self.submitted.emit(text, see_screen)


def capture_screen_base64() -> str:
    """Capture the primary screen and return a compressed JPEG as a base64 string."""
    screen = QApplication.primaryScreen()
    if screen is None:
        return ""
    pixmap = screen.grabWindow(0)
    if pixmap.isNull():
        return ""
    # Downscale to max width 1280 to keep API payload fast and lightweight
    if pixmap.width() > 1280:
        pixmap = pixmap.scaledToWidth(1280, Qt.SmoothTransformation)

    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "JPEG", 75)
    raw_bytes = bytes(buffer.data())
    buffer.close()
    return base64.b64encode(raw_bytes).decode("utf-8")


class MemoryManager:
    """Manages local session chat logs, long-term facts, and config/API key storage."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.memory_dir = base_dir / "memory"
        self.sessions_dir = self.memory_dir / "sessions"
        self.config_path = self.memory_dir / "config.json"
        self.env_path = base_dir / ".env"
        self.facts_path = self.memory_dir / "facts.json"

        self._ensure_dirs()
        self._session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_file = self.sessions_dir / f"session_{self._session_id}.json"
        self.history: list[dict[str, any]] = []
        self._init_session_file()

    def _ensure_dirs(self) -> None:
        try:
            self.memory_dir.mkdir(parents=True, exist_ok=True)
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            if not self.facts_path.exists():
                default_facts = {
                    "user_name": "Dork",
                    "notes": ["The user created Yellow's Pixel Buddies"],
                }
                self.facts_path.write_text(json.dumps(default_facts, indent=2), encoding="utf-8")
        except Exception as err:
            log.warning("Could not initialize memory directories/facts: %s", err)

    def _init_session_file(self) -> None:
        init_data = {
            "session_id": self._session_id,
            "started_at": datetime.datetime.now().isoformat(),
            "messages": [],
        }
        try:
            self.session_file.write_text(json.dumps(init_data, indent=2), encoding="utf-8")
        except Exception as err:
            log.warning("Could not initialize session file: %s", err)

    def get_api_key(self) -> str:
        """Retrieve Gemini API key from environment, .env file, or memory/config.json."""
        env_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if env_key:
            return env_key

        if self.env_path.exists():
            try:
                for line in self.env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("GEMINI_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
            except Exception:
                pass

        if self.config_path.exists():
            try:
                cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
                val = cfg.get("gemini_api_key", "").strip()
                if val:
                    return val
            except Exception:
                pass

        return ""

    def save_api_key(self, api_key: str) -> None:
        """Save API key to both .env and memory/config.json."""
        api_key = api_key.strip()
        os.environ["GEMINI_API_KEY"] = api_key

        env_lines = []
        found = False
        if self.env_path.exists():
            try:
                for line in self.env_path.read_text(encoding="utf-8").splitlines():
                    if line.strip().startswith("GEMINI_API_KEY="):
                        env_lines.append(f'GEMINI_API_KEY="{api_key}"')
                        found = True
                    else:
                        env_lines.append(line)
            except Exception:
                pass
        if not found:
            env_lines.append(f'GEMINI_API_KEY="{api_key}"')
        try:
            self.env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        except Exception as err:
            log.warning("Could not update .env: %s", err)

        cfg = {}
        if self.config_path.exists():
            try:
                cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        cfg["gemini_api_key"] = api_key
        try:
            self.config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except Exception as err:
            log.warning("Could not update config.json: %s", err)

    def get_long_term_facts(self) -> str:
        """Read facts.json to inject into system prompt."""
        if self.facts_path.exists():
            try:
                facts = json.loads(self.facts_path.read_text(encoding="utf-8"))
                lines = []
                if "user_name" in facts:
                    lines.append(f"- User preferred name: {facts['user_name']}")
                if "notes" in facts and isinstance(facts["notes"], list):
                    for n in facts["notes"]:
                        lines.append(f"- {n}")
                return "\n".join(lines)
            except Exception:
                pass
        return ""

    def record_turn(self, user_text: str, pink_response: str, anim: str, had_screen: bool = False) -> None:
        """Record turn in history and persist to session file."""
        turn = {
            "timestamp": datetime.datetime.now().isoformat(),
            "user": user_text,
            "pink": pink_response,
            "anim": anim,
            "had_screen": had_screen,
        }
        self.history.append(turn)

        try:
            data = json.loads(self.session_file.read_text(encoding="utf-8"))
            data["messages"].append(turn)
            self.session_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as err:
            log.warning("Could not record turn to session file: %s", err)

    def clear_current_session(self) -> None:
        """Reset current in-memory history and start a fresh session file."""
        self.history.clear()
        self._session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_file = self.sessions_dir / f"session_{self._session_id}.json"
        self._init_session_file()


class GeminiWorkerThread(QThread):
    response_ready = pyqtSignal(str, str)  # (spoken_text, anim_name)
    error_occurred = pyqtSignal(str)       # (error_message)

    def __init__(
        self,
        api_key: str,
        user_prompt: str,
        system_instruction: str,
        history: list[dict[str, any]],
        screenshot_b64: str | None = None,
        model_name: str = GEMINI_MODEL,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.api_key = api_key
        self.user_prompt = user_prompt
        self.system_instruction = system_instruction
        self.history = history
        self.screenshot_b64 = screenshot_b64
        self.model_name = model_name

    def run(self) -> None:
        models_to_try = [self.model_name] + [m for m in GEMINI_FALLBACK_MODELS if m != self.model_name]
        last_error = ""

        for model in models_to_try:
            try:
                spoken_text, anim = self._call_gemini(model)
                self.response_ready.emit(spoken_text, anim)
                return
            except requests.exceptions.HTTPError as http_err:
                status_code = http_err.response.status_code if http_err.response is not None else 0
                resp_text = http_err.response.text if http_err.response is not None else str(http_err)
                if status_code in (404, 400) and model != models_to_try[-1]:
                    log.info("Model %s returned HTTP %s, trying fallback...", model, status_code)
                    last_error = resp_text
                    continue
                else:
                    self.error_occurred.emit(f"HTTP {status_code}: {resp_text[:120]}")
                    return
            except requests.exceptions.Timeout:
                self.error_occurred.emit("Request timed out. Google Gemini servers might be busy!")
                return
            except Exception as err:
                self.error_occurred.emit(f"Network error: {err}")
                return

        self.error_occurred.emit(f"All models failed. Last error: {last_error[:120]}")

    def _call_gemini(self, model: str) -> tuple[str, str]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}

        contents = []

        # Recent conversation turns (last 6 turns, text only)
        for turn in self.history[-6:]:
            u_text = turn.get("user", "")
            p_text = turn.get("pink", "")
            if u_text:
                contents.append({"role": "user", "parts": [{"text": u_text}]})
            if p_text:
                contents.append({"role": "model", "parts": [{"text": p_text}]})

        # Current user turn
        current_parts = [{"text": self.user_prompt}]
        if self.screenshot_b64:
            current_parts.append({
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data": self.screenshot_b64,
                }
            })
        contents.append({"role": "user", "parts": current_parts})

        payload = {
            "systemInstruction": {
                "parts": [{"text": self.system_instruction}]
            },
            "contents": contents,
            "generationConfig": {
                "temperature": 0.85,
                "maxOutputTokens": 200,
            }
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=GEMINI_TIMEOUT_S)
        resp.raise_for_status()

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError("No response generated by Gemini.")

        raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
        if not raw_text:
            raise ValueError("Empty response received from Gemini.")

        # Parse animation tag e.g. [anim: peace_sign]
        anim = "peace_sign"
        anim_match = re.search(r"\[anim:\s*([a-zA-Z0-9_]+)\]", raw_text)
        if anim_match:
            anim = anim_match.group(1).lower()
            clean_text = raw_text[:anim_match.start()] + raw_text[anim_match.end():]
        else:
            clean_text = raw_text

        clean_text = clean_text.strip()
        # Clean any markdown bolding like **text** into clean text for pixel font
        clean_text = re.sub(r"\*\*(.*?)\*\*", r"\1", clean_text)

        # Ensure Deltarune formatting: if it doesn't start with "* ", prefix it
        lines = []
        for line in clean_text.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            if not line_str.startswith("*"):
                lines.append("* " + line_str)
            elif line_str.startswith("*") and not line_str.startswith("* "):
                lines.append("* " + line_str[1:].lstrip())
            else:
                lines.append(line_str)

        formatted_text = "\n".join(lines) if lines else ("* " + clean_text)
        return formatted_text, anim


@dataclass
class Bomb:
    x: float
    y: float
    vx: float
    vy: float
    size: float
    target_mode: str = "random"  # "beneath", "near", or "random"
    has_bounced: bool = False
    is_ignited: bool = False
    fuse_duration: float = 0.0
    fuse_time: float = 0.0
    bomb_frame_idx: int = 0
    spark_frame_idx: int = 0
    spark_timer: float = 0.0
    exploded: bool = False


@dataclass
class LaserCross:
    cx: float
    cy: float
    extend_length: float = 0.0
    frame_idx: int = 0
    frame_timer: float = 0.0
    finished: bool = False
    hit_detected: bool = False


class BombLaserOverlay(QWidget):
    """Full-screen, click-through overlay managing falling bombs, sparks, and laser beams."""

    def __init__(self, bank: SpriteBank) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._bank = bank
        self._bombs: list[Bomb] = []
        self._lasers: list[LaserCross] = []
        self._ground_y: float = 0.0
        self._last_bomb_exploded_at: float = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(BOMB_PHYSICS_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._last_time = time.perf_counter()

    @property
    def last_bomb_exploded_at(self) -> float:
        return self._last_bomb_exploded_at

    def has_active_bombs(self) -> bool:
        """True if any unexploded bombs are currently bouncing or falling."""
        return any(not b.exploded for b in self._bombs)

    def has_active_lasers(self) -> bool:
        """True if any laser crosses are currently extending/visible."""
        return any(not l.finished for l in self._lasers)

    def reset_state(self) -> None:
        """Reset bombs, lasers, and explosion tracking for a new attack."""
        self._bombs.clear()
        self._lasers.clear()
        self._last_bomb_exploded_at = 0.0

    def spawn_bombs(self, origin_x: float, origin_y: float, ground_y: float,
                    screen_rect: QRect, facing_left: bool = True) -> None:
        """Spawn 4 bombs thrown downwards with fanning velocities."""
        self._ground_y = ground_y
        if self.geometry() != screen_rect:
            self.setGeometry(screen_rect)

        # 4 spread velocities fanning out below
        base_vx = [-220.0, -75.0, 75.0, 220.0]
        if not facing_left:
            base_vx.reverse()

        for i in range(BOMB_COUNT):
            vx = base_vx[i] + random.uniform(-20.0, 20.0)
            vy = random.uniform(BOMB_INITIAL_VY_MIN, BOMB_INITIAL_VY_MAX)
            bx = origin_x + (i - 1.5) * 14.0 - BOMB_SIZE / 2.0
            by = origin_y + random.uniform(-5.0, 5.0)
            self._bombs.append(Bomb(
                x=bx, y=by, vx=vx, vy=vy, size=float(BOMB_SIZE)
            ))

    def spawn_single_bomb(self, bx: float, by: float, vx: float, vy: float,
                          ground_y: float, screen_rect: QRect,
                          target_mode: str = "random") -> None:
        """Spawn a single bomb into the overlay simulation."""
        self._ground_y = ground_y
        if self.geometry() != screen_rect:
            self.setGeometry(screen_rect)

        self._bombs.append(Bomb(
            x=bx - BOMB_SIZE / 2.0,
            y=by,
            vx=vx,
            vy=vy,
            size=float(BOMB_SIZE),
            target_mode=target_mode,
        ))

        self._last_time = time.perf_counter()
        if not self.isVisible():
            self.show()
        self.raise_()
        set_window_input_transparent(self, True)
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = max(0.001, min(0.05, now - self._last_time))
        self._last_time = now

        screen_left = float(self.x())
        screen_right = float(self.x() + self.width())

        spark_frames = self._bank.frames.get("sparks", [])
        bomb_frames = self._bank.frames.get("bomb", [])
        laser_mid_frames = self._bank.frames.get("laser_mid", [])

        spark_interval_s = SPARK_FRAME_INTERVAL_MS / 1000.0
        laser_interval_s = LASER_FRAME_INTERVAL_MS / 1000.0

        # Update bombs
        for b in self._bombs:
            gravity = BOMB_GRAVITY_PX_S2 if b.has_bounced else BOMB_FIRST_FALL_GRAVITY_PX_S2
            b.vy += gravity * dt
            b.x += b.vx * dt
            b.y += b.vy * dt

            # Ground collision (accounting for transparent bottom padding)
            if b.y + b.size - BOMB_BOTTOM_PADDING >= self._ground_y:
                b.y = self._ground_y - b.size + BOMB_BOTTOM_PADDING
                if not b.has_bounced:
                    b.has_bounced = True
                    b.is_ignited = True
                    cursor_x = float(QCursor.pos().x())
                    center_x = b.x + b.size / 2.0
                    min_x = screen_left + b.size / 2.0
                    max_x = screen_right - b.size / 2.0

                    if b.target_mode == "beneath":
                        # Exactly 0.75s fuse - player has 0.75s to move the cursor before detonation
                        b.fuse_duration = 0.75
                        b.fuse_time = 0.75
                        target_x = max(min_x, min(max_x, cursor_x))
                        dx = target_x - center_x
                        b.vx = max(-1000.0, min(1000.0, dx / 0.75))
                        # Gentle upward bounce that reaches apex and lands back near ground at ~0.75s
                        # (flight time = 2 * vy / g = 2 * 490 / 1300 = 0.754s)
                        b.vy = -490.0
                    elif b.target_mode == "near":
                        b.fuse_duration = random.uniform(1.3, 1.7)
                        b.fuse_time = b.fuse_duration
                        offset = random.choice([-1.0, 1.0]) * random.uniform(160.0, 240.0)
                        target_x = max(min_x, min(max_x, cursor_x + offset))
                        dx = target_x - center_x
                        b.vx = max(-1000.0, min(1000.0, dx / b.fuse_duration))
                        b.vy = -random.uniform(BOMB_BOUNCE_VY_MIN, BOMB_BOUNCE_VY_MAX)
                    else:  # "random"
                        b.fuse_duration = random.uniform(BOMB_FUSE_MIN_S, BOMB_FUSE_MAX_S)
                        b.fuse_time = b.fuse_duration
                        b.vy = -random.uniform(BOMB_BOUNCE_VY_MIN, BOMB_BOUNCE_VY_MAX)
                        direction = 1.0 if b.vx >= 0.0 else -1.0
                        speed = max(abs(b.vx) * 1.35, random.uniform(380.0, 620.0))
                        b.vx = direction * speed + random.uniform(-40.0, 40.0)
                else:
                    b.vy = -abs(b.vy) * random.uniform(0.65, 0.78)
                    b.vx *= 0.92
                    if abs(b.vy) < 40.0:
                        b.vy = 0.0

            # Screen edge bounces (elastic ricochet)
            if b.x < screen_left:
                b.x = screen_left
                b.vx = abs(b.vx) * 0.85
            elif b.x + b.size > screen_right:
                b.x = screen_right - b.size
                b.vx = -abs(b.vx) * 0.85

            # Fuse and sparks
            if b.is_ignited:
                b.fuse_time -= dt
                if b.fuse_time <= 0.0:
                    b.exploded = True
                    self._last_bomb_exploded_at = now
                    # Detonate into cross laser
                    self._lasers.append(LaserCross(
                        cx=b.x + b.size / 2.0,
                        cy=b.y + b.size / 2.0,
                    ))
                    continue

                # Progress bomb frames (0 to 4)
                if bomb_frames:
                    progress = max(0.0, min(1.0, 1.0 - (b.fuse_time / b.fuse_duration)))
                    b.bomb_frame_idx = min(len(bomb_frames) - 1, int(progress * len(bomb_frames)))

                # Fast sparks loop
                if spark_frames:
                    b.spark_timer += dt
                    if b.spark_timer >= spark_interval_s:
                        b.spark_timer = 0.0
                        b.spark_frame_idx = (b.spark_frame_idx + 1) % len(spark_frames)

        # Remove exploded bombs
        self._bombs = [b for b in self._bombs if not b.exploded]

        # Update lasers
        cursor_pos = QCursor.pos()
        for laser in self._lasers:
            laser.extend_length += LASER_EXTEND_SPEED_PX_S * dt
            laser.frame_timer += dt
            if laser.frame_timer >= laser_interval_s:
                laser.frame_timer = 0.0
                laser.frame_idx += 1
                if laser.frame_idx >= len(laser_mid_frames):
                    laser.finished = True

            # Laser hit detection on mouse cursor
            if not laser.hit_detected:
                half = LASER_SIZE / 2.0
                hit_vert = abs(cursor_pos.x() - laser.cx) <= half
                hit_horiz = abs(cursor_pos.y() - laser.cy) <= half
                if hit_vert or hit_horiz:
                    laser.hit_detected = True
                    log.info("Cursor hit by laser cross beam! (laser cx=%.1f, cy=%.1f, cursor=%d, %d)",
                             laser.cx, laser.cy, cursor_pos.x(), cursor_pos.y())

        # Remove finished lasers
        self._lasers = [l for l in self._lasers if not l.finished]

        # Auto-hide when done
        if not self._bombs and not self._lasers:
            self._timer.stop()
            self.hide()

        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        screen_offset_x = self.x()
        screen_offset_y = self.y()
        win_w = self.width()
        win_h = self.height()

        mid_frames = self._bank.frames.get("laser_mid", [])
        ext_v_frames = self._bank.frames.get("laser_extend", [])
        ext_h_frames = self._bank.frames.get("laser_extend_horiz", ext_v_frames)

        # Draw Lasers
        tile = float(LASER_SIZE)
        half = tile / 2.0

        for laser in self._lasers:
            f_idx = laser.frame_idx
            if f_idx >= len(mid_frames):
                continue
            mid_pix = mid_frames[f_idx].pixmap
            ext_v_pix = ext_v_frames[min(f_idx, len(ext_v_frames) - 1)].pixmap
            ext_h_pix = ext_h_frames[min(f_idx, len(ext_h_frames) - 1)].pixmap

            lx = laser.cx - screen_offset_x
            ly = laser.cy - screen_offset_y
            extend = laser.extend_length

            # Horizontal Left
            max_reach_l = min(lx - half, extend)
            if max_reach_l > 0:
                cur_x = lx - half - tile
                min_x = lx - half - max_reach_l
                while cur_x >= min_x - tile + 1 and cur_x >= -tile:
                    painter.drawPixmap(QPointF(cur_x, ly - half), ext_h_pix)
                    cur_x -= tile

            # Horizontal Right
            max_reach_r = min(win_w - (lx + half), extend)
            if max_reach_r > 0:
                cur_x = lx + half
                max_x = lx + half + max_reach_r
                while cur_x <= max_x and cur_x <= win_w:
                    painter.drawPixmap(QPointF(cur_x, ly - half), ext_h_pix)
                    cur_x += tile

            # Vertical Up
            max_reach_u = min(ly - half, extend)
            if max_reach_u > 0:
                cur_y = ly - half - tile
                min_y = ly - half - max_reach_u
                while cur_y >= min_y - tile + 1 and cur_y >= -tile:
                    painter.drawPixmap(QPointF(lx - half, cur_y), ext_v_pix)
                    cur_y -= tile

            # Vertical Down
            max_reach_d = min(win_h - (ly + half), extend)
            if max_reach_d > 0:
                cur_y = ly + half
                max_y = ly + half + max_reach_d
                while cur_y <= max_y and cur_y <= win_h:
                    painter.drawPixmap(QPointF(lx - half, cur_y), ext_v_pix)
                    cur_y += tile

            # Center tile
            painter.drawPixmap(QPointF(lx - half, ly - half), mid_pix)

        # Draw Bombs
        bomb_frames = self._bank.frames.get("bomb", [])
        spark_frames = self._bank.frames.get("sparks", [])

        for b in self._bombs:
            bx = b.x - screen_offset_x
            by = b.y - screen_offset_y

            if bomb_frames:
                b_pix = bomb_frames[min(b.bomb_frame_idx, len(bomb_frames) - 1)].pixmap
                painter.drawPixmap(QPointF(bx, by), b_pix)

            # Sparks at burning rope tip
            if b.is_ignited and spark_frames:
                s_pix = spark_frames[min(b.spark_frame_idx, len(spark_frames) - 1)].pixmap
                tip_frac_x, tip_frac_y = BOMB_ROPE_TIPS[min(b.bomb_frame_idx, len(BOMB_ROPE_TIPS) - 1)]
                tip_x = bx + tip_frac_x * b.size
                tip_y = by + tip_frac_y * b.size
                painter.drawPixmap(QPointF(tip_x - SPARK_SIZE / 2.0, tip_y - SPARK_SIZE / 2.0), s_pix)

        painter.end()


class ClickableSlider(QSlider):
    """Horizontal slider where clicking anywhere along the track jumps directly to that value."""

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            sr = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
            if not sr.contains(event.pos()):
                val = QStyle.sliderValueFromPosition(
                    self.minimum(), self.maximum(),
                    event.x() - sr.width() // 2,
                    self.width() - sr.width()
                )
                self.setValue(val)
        super().mousePressEvent(event)


class BombChanceWidget(QWidget):
    """Custom tray menu widget: percentage slider for bomb attack probability and a reset to default button."""

    def __init__(self, initial_pct: int = HANG_BOMB_DEFAULT_CHANCE_PERCENT,
                 default_pct: int = HANG_BOMB_DEFAULT_CHANCE_PERCENT,
                 on_change=None, parent=None) -> None:
        super().__init__(parent)
        self._default_pct = default_pct
        self._on_change = on_change

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 2, 16, 6)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.lbl_title = QLabel(f"Chance: {initial_pct}%")
        self.lbl_title.setStyleSheet("font-size: 11px;")

        self.btn_default = QPushButton(f"Default ({default_pct}%)")
        self.btn_default.setFocusPolicy(Qt.NoFocus)
        self.btn_default.setCursor(Qt.PointingHandCursor)
        self.btn_default.setStyleSheet("font-size: 10px; padding: 1px 5px;")

        top_row.addWidget(self.lbl_title)
        top_row.addStretch()
        top_row.addWidget(self.btn_default)
        layout.addLayout(top_row)

        self.slider = ClickableSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(initial_pct)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(5)
        self.slider.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.slider)

        self.slider.valueChanged.connect(self._on_slider_changed)
        self.btn_default.clicked.connect(self._on_default_clicked)

    def _on_slider_changed(self, val: int) -> None:
        self.lbl_title.setText(f"Chance: {val}%")
        if self._on_change is not None:
            self._on_change(val)

    def _on_default_clicked(self) -> None:
        self.slider.setValue(self._default_pct)

    def set_value(self, val: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(val)
        self.lbl_title.setText(f"Chance: {val}%")
        self.slider.blockSignals(False)

    def value(self) -> int:
        return self.slider.value()


class MediaWatcher(QThread):
    """Monitors system-wide media playback (Spotify, YouTube, browser, etc.) using Windows GSMTC."""
    song_started = pyqtSignal(str, str)  # title, artist
    song_ended = pyqtSignal()

    def __init__(self, poll_interval_ms: int = 1500, parent=None) -> None:
        super().__init__(parent)
        self._poll_interval_s = max(0.5, poll_interval_ms / 1000.0)
        self._running = True
        self._last_track_id: tuple[str, str] = ("", "")
        self._last_playing = False

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as MediaManager,
                GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus
            )
        except Exception as err:
            log.info("Windows Media Control (GSMTC) unavailable: %s", err)
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _get_manager():
            try:
                return await MediaManager.request_async()
            except Exception:
                return None

        async def _check_session(mgr):
            try:
                sess = mgr.get_current_session()
                if sess is None:
                    return None, False
                pb = sess.get_playback_info()
                is_playing = (pb is not None and pb.playback_status == PlaybackStatus.PLAYING)
                if not is_playing:
                    return None, False
                props = await sess.try_get_media_properties_async()
                if props is None:
                    return None, False
                title = props.title.strip() if props.title else ""
                artist = props.artist.strip() if props.artist else ""
                return (title, artist), True
            except Exception as ex:
                log.debug("GSMTC poll error: %s", ex)
                return None, False

        try:
            mgr = loop.run_until_complete(_get_manager())
            while self._running:
                if mgr is None:
                    time.sleep(self._poll_interval_s * 2)
                    mgr = loop.run_until_complete(_get_manager())
                    continue

                track, is_playing = loop.run_until_complete(_check_session(mgr))
                if is_playing and track and track[0]:
                    if track != self._last_track_id:
                        self._last_track_id = track
                        self._last_playing = True
                        self.song_started.emit(track[0], track[1])
                    else:
                        self._last_playing = True
                else:
                    if self._last_playing:
                        self._last_playing = False
                        self.song_ended.emit()

                # Sleep in short increments for responsive thread termination
                for _ in range(int(self._poll_interval_s * 10)):
                    if not self._running:
                        break
                    time.sleep(0.1)
        except Exception as err:
            log.warning("MediaWatcher encountered an error: %s", err)
        finally:
            loop.close()


class YellowsPixelBuddies(QWidget):
    """A sprite-sized, frameless, translucent, always-on-top window that walks on the taskbar."""

    def __init__(self, bank: SpriteBank, font_family: str = "Determination") -> None:
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
        self.setWindowTitle("Yellow's Pixel Buddies")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self._bank = bank
        self._font_family = font_family

        # --- animation state ---------------------------------------------------
        self.state = "idle"                  # which sprite folder is being played
        self._sprite_key = "idle"            # which frame set is drawn: `state`, or its mirrored copy
        self._frame_idx = 0
        self._loop = True                    # does the current animation repeat?
        self._hold_ticks = 0                 # extra ticks to freeze on the last frame
        self._repeat_count = 0               # extra cycles remaining for repeating specials
        self._sub_loop_range: tuple[int, int] | None = None  # 0-indexed (start, end) frames for sub-loops
        self._sub_loop_count = 0             # repeats remaining for the sub-loop
        self._pixmap: QPixmap | None = None

        # --- overlay effect state (e.g. explosion in front) -------------------
        self._overlay_state: str | None = None
        self._overlay_frame_idx = 0
        self._overlay_pixmap: QPixmap | None = None
        self._vfx_overlay = VfxOverlay()
        self._bomb_overlay = BombLaserOverlay(bank)
        self._dialogue_overlay = DialogueOverlay(self._font_family, DIALOGUE_BOX_PATH)
        self._dialogue_overlay.dismissed.connect(self._on_dialogue_dismissed)
        self._chat_input = ChatInputOverlay(self._font_family, DIALOGUE_BOX_PATH)
        self._chat_input.submitted.connect(self._on_chat_submitted)
        self._chat_input.cancelled.connect(self._on_chat_cancelled)
        self._memory = MemoryManager(_base_dir)
        self._gemini_thread: GeminiWorkerThread | None = None
        self._is_ghost_talking: bool = False
        self._ghost_aura_cache: dict[int, QPixmap] = {}
        self._dialogue_enabled: bool = DIALOGUE_ENABLED
        self._last_dialogue: str | None = None
        self._dialogue_action: QAction | None = None
        self._last_shocked_dialogue_time: float = -9999.0
        self._last_tongue_dialogue_time: float = -9999.0

        # --- media watcher (song detection) ------------------------------------
        self._media_watcher: MediaWatcher | None = None
        if SONG_DETECTION_ENABLED:
            try:
                self._media_watcher = MediaWatcher(poll_interval_ms=SONG_DETECTION_INTERVAL_MS, parent=self)
                self._media_watcher.song_started.connect(self._on_song_started)
                self._media_watcher.start()
            except Exception as err:
                log.info("MediaWatcher could not be started: %s", err)

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
        self._in_angry_spam: bool = False          # active angry click-spam sequence
        self._last_angry_click_time: float = 0.0   # timestamp of the most recent click during anger spam
        self._walk_before_menu: str | None = None  # walk / run animation swapped for idle while the menu is open

        # --- jump to the cursor ------------------------------------------------
        # Screen y grows downwards: an upward speed is NEGATIVE, gravity is positive.
        self._jump_enabled = bank.jump_sprites_ready   # needs real PNGs in airborne/ AND hanging/
        self._jump_ready_at = 0.0            # perf_counter() time at which the cooldown is over
        self._jump_active = False            # a jump sequence is running (the cooldown starts at touchdown)
        self._gravity = GRAVITY_PX_S2        # gravity of the current JUMP / FALL (drop vs. jump)
        self._vx = 0.0                       # sideways speed of a jump in px/s (+ = right), set at take-off
        self._facing = AIRBORNE_ART_FACES    # heading of the last jump ("left" / "right")
        self._pending_reaction: str | None = None   # played on touchdown; decided when the fall begins
        self._wall_bounced = False           # True if she bounced off a screen wall during this jump
        self._can_catch_cursor = False       # True during a jump until she catches the cursor
        self._hang_started_at = 0.0          # perf_counter() time of the grab
        self._hang_ends_at = 0.0             # ... and when she lets go on her own
        self._hang_bomb_thrown = False       # whether bomb throw sequence has triggered for this hang
        self._hang_bomb_count_remaining = 0  # serial bombs remaining to throw
        self._hang_bomb_index = 0            # index of current bomb in the series (0..BOMB_COUNT-1)
        self._throw_pause_ticks = 0          # pause ticks remaining on frame 11
        self._bombs_spawned_for_current_throw = False
        self._throw_started_at = 0.0         # perf_counter() time when throw sequence started
        self._throw_start_y = 0.0            # starting y before upward float
        self._throw_rise_px = 0.0            # upward distance to float during frames 1-5
        self._post_throw_laugh = False       # True while post-bomb victory laugh lasts
        self._bomb_target_plan: list[str] = ["random", "random", "near", "beneath"]
        self._bomb_attack_enabled: bool = HANG_BOMB_ENABLED
        self._bomb_chance_percent: int = HANG_BOMB_DEFAULT_CHANCE_PERCENT
        self._shake_trail: deque[tuple[float, int, int]] = deque()   # raw cursor (time, x, y) while hanging
        self._input_transparent = False      # True while mouse clicks pass through the window
        self._warned_no_click_through = False
        self._debug_jump_at: float | None = None    # when the armed debug-menu jump fires

        # --- cursor tracking (ONE QCursor.pos() sample per movement tick, no extra timer) ---
        self._cursor = QCursor.pos()         # latest sample
        self._cursor_vx = 0.0                # smoothed cursor speed in px/s (kept only if JUMP_LEAD_TIME_S > 0)
        self._cursor_vy = 0.0
        self._still_anchor = self._cursor    # where the cursor was when it last really moved
        self._still_since = time.perf_counter()    # ... and since when it has stayed within the dead zone
        self._next_still_check_at = 0.0      # earliest time of the next still-cursor roll

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

        self._overlay_timer = QTimer(self)         # foreground VFX overlay frame advance (explosion, etc.)
        self._overlay_timer.setInterval(EXPLOSION_FRAME_INTERVAL_MS)
        self._overlay_timer.timeout.connect(self._advance_overlay_frame)

        # --- window switch monitoring ------------------------------------------
        self._last_foreground_hwnd: int | None = None
        self._last_luminance: float = 128.0
        self._last_switch_shock_time: float = -9999.0   # allows immediate shock on first switch
        self._last_switch_burnt_time: float = -9999.0   # allows immediate burnt on first switch
        self._interrupted_state: dict | None = None     # saves activity to resume after reaction

        if REACT_ON_MAXIMIZED_APP:
            self._window_timer = QTimer(self)
            self._window_timer.setInterval(REACT_POLL_INTERVAL_MS)
            self._window_timer.timeout.connect(self._check_foreground_window)

        # --- system tray icon (hidden icons menu on taskbar) ------------------
        self._tray_icon: QSystemTrayIcon | None = None
        self._startup_action: QAction | None = None
        self._bring_action: QAction | None = None
        self._talk_tray_action: QAction | None = None
        self._bomb_action: QAction | None = None
        self._bomb_force_action: QAction | None = None
        self._bomb_chance_action: QWidgetAction | None = None
        self._bomb_chance_widget: BombChanceWidget | None = None

        # --- startup summon intro & hide outro state -------------------------
        self._intro_subphase: str = ""
        self._intro_timer: float = 0.0
        self._intro_apex_y: float = 0.0
        self._intro_target_land_x: float = 0.0
        self._hide_subphase: str = ""
        self._hide_timer: float = 0.0
        self._hide_tray_action: QAction | None = None
        self._dialogue_clicked: bool = False

        self._init_tray_icon()

    # ------------------------------------------------------------------ start
    def start(self) -> None:
        """Hide Pink at the bottom-right taskbar on startup; she emerges when clicked or called."""
        area = QApplication.primaryScreen().availableGeometry()
        self._phase = Phase.HIDE_PEEK
        self.state = GHOST_STATE
        self._sprite_key = GHOST_STATE
        self._frame_idx = 0
        self._loop = True
        self._x = float(area.x() + area.width() - self.width() - EAR_PEEK_OFFSET_X)
        self._y = float(area.y() + area.height() - EAR_PEEK_HEIGHT_PX)
        self._set_frame(0)
        self._sync_window_position()
        self.show()

        self._last_tick = time.perf_counter()
        self._anim_timer.start()
        self._move_timer.start()

        if REACT_ON_MAXIMIZED_APP:
            dll = _user32()
            if dll is not None:
                fg = dll.GetForegroundWindow()
                if fg and fg != int(self.winId()):
                    self._last_foreground_hwnd = fg
                    self._last_luminance = sample_screen_luminance()
            self._window_timer.start()

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

    def _work_area(self):
        """The primary screen minus the taskbar (a QRect, logical px): where the cursor can be grabbed."""
        return QApplication.primaryScreen().availableGeometry()

    def _sync_window_position(self) -> None:
        """Move the real window to the float position (only if it changed)."""
        target = QPoint(round(self._x), round(self._y))
        if target != self.pos():
            self.move(target)
        if hasattr(self, "_vfx_overlay") and self._overlay_state is not None and self._overlay_pixmap is not None:
            self._show_overlay_frame(self._overlay_pixmap)
        if hasattr(self, "_dialogue_overlay") and self._dialogue_overlay.is_active():
            self._dialogue_overlay.update_position(self._x, self._y)
        if hasattr(self, "_chat_input") and self._chat_input.isVisible():
            self._chat_input.update_position(self._x, self._y)

    def _say(self, category_or_text: str, force: bool = False, extra_queue: list[str] | None = None, skippable: bool = True) -> None:
        """Trigger a speech bubble dialogue from DIALOGUE_LINES or direct text."""
        if not self._dialogue_enabled or not hasattr(self, "_dialogue_overlay"):
            return
        if (getattr(self, "_phase", None) in (Phase.JUMP, Phase.DRAG,
                                              Phase.HIDE_PEEK, Phase.HIDE_OUTRO,
                                              Phase.SUMMON_INTRO, Phase.EXIT_OUTRO)
                or getattr(self, "_jump_active", False)
                or getattr(self, "_dragging", False)):
            return
        if category_or_text in ("idle", "question"):
            is_question = (category_or_text == "question"
                           or (category_or_text == "idle" and random.random() < DIALOGUE_QUESTION_CHANCE and bool(QUESTION_ITEMS)))
            if is_question and QUESTION_ITEMS:
                candidates = [q for q in QUESTION_ITEMS if q.question != self._last_dialogue]
                q_item = random.choice(candidates if candidates else QUESTION_ITEMS)
                self._last_dialogue = q_item.question
                if q_item.question in GHOST_DIALOGUE_LINES:
                    self._start_ghost_speech()
                self._dialogue_overlay.ask(
                    q_item.question,
                    q_item.choices,
                    self._x,
                    self._y,
                    on_chosen=self._on_question_answered,
                )
                return
            else:
                today_idx = get_idle_variant_for_date()
                if random.random() < DIALOGUE_IDLE_STEAL_CHANCE and len(IDLE_DIALOGUE_VARIANTS) > 1:
                    other_indices = [i for i in range(len(IDLE_DIALOGUE_VARIANTS)) if i != today_idx]
                    chosen_idx = random.choice(other_indices)
                else:
                    chosen_idx = today_idx
                lines = IDLE_DIALOGUE_VARIANTS[chosen_idx]
                if not lines:
                    return
                choices = [l for l in lines if l != self._last_dialogue] if len(lines) > 1 else lines
                line = random.choice(choices)
                if line in GHOST_DIALOGUE_LINES:
                    self._start_ghost_speech()
        elif category_or_text in DIALOGUE_LINES:
            lines = DIALOGUE_LINES[category_or_text]
            if not lines:
                return  # No dialogue lines defined for this sprite -> do not show dialogue
            choices = [l for l in lines if l != self._last_dialogue] if len(lines) > 1 else lines
            line = random.choice(choices)
        elif category_or_text.startswith("* "):
            line = category_or_text
            if line in GHOST_DIALOGUE_LINES:
                self._start_ghost_speech()
        else:
            # Sprite state or category has no dialogue lines -> do not show dialogue
            return

        now = time.perf_counter()
        if category_or_text in ("tongue", "* :P") or line == "* :P":
            if now - self._last_tongue_dialogue_time < DIALOGUE_TONGUE_COOLDOWN_S:
                return

        if not force and self._dialogue_overlay.is_active():
            return

        if category_or_text in ("tongue", "* :P") or line == "* :P":
            self._last_tongue_dialogue_time = now

        if category_or_text == "angry" or getattr(self, "_in_angry_spam", False):
            skippable = False

        self._last_dialogue = line
        self._dialogue_overlay.say(line, self._x, self._y, queue=extra_queue, skippable=skippable)

    def _on_question_answered(self, reaction_text: str, reaction_anim: str | None) -> None:
        """Handle player's answer to Pink's question: play reaction animation and speak response."""
        self._phase = Phase.PAUSE
        self._pause_elapsed = False
        if reaction_anim and self._can_play(reaction_anim):
            self._play(reaction_anim)
        self._say(reaction_text, force=True)

    def _start_ghost_speech(self) -> None:
        """Ghost takes over the vessel with angry animation and spectral aura."""
        self._is_ghost_talking = True
        if hasattr(self, "_ghost_aura_cache"):
            self._ghost_aura_cache.clear()
        if self._can_play("angry"):
            self._play("angry", loop=True)

    def _on_dialogue_dismissed(self) -> None:
        """Handle cleanup when dialogue speech bubble closes."""
        if self._phase is Phase.SUMMON_DIALOGUE:
            self._start_summon_intro()
            return
        if getattr(self, "_is_ghost_talking", False):
            self._is_ghost_talking = False
            if self._phase is Phase.PAUSE and self.state == "angry":
                self._play("idle")
        if self._phase is Phase.PAUSE:
            if not getattr(self, "_in_angry_spam", False):
                if self.state in ("shocked", "angry") or not self._loop:
                    self._play("idle")
            if self._pause_elapsed or not self._brain_timer.isActive():
                self._pause_elapsed = False
                self._brain_timer.start(AFTER_SPECIAL_REST_MS)
        self.update()

    def _open_chat_input(self) -> None:
        """Open the interactive chat text input bar to talk to Pink."""
        if self._phase in (Phase.HIDE_PEEK, Phase.HIDE_OUTRO, Phase.SUMMON_DIALOGUE, Phase.SUMMON_INTRO, Phase.EXIT_OUTRO):
            return
        self._in_angry_spam = False
        self._click_times.clear()
        self._phase = Phase.PAUSE
        self._pause_elapsed = False
        self._brain_timer.stop()
        if hasattr(self, "_dialogue_overlay") and self._dialogue_overlay.is_active():
            self._dialogue_overlay.dismiss(clear_queue=True)
        if self.state in MOVE_VELOCITY_PX_S:
            self._play("idle")
        if hasattr(self, "_chat_input"):
            self._chat_input.open_at(self._x, self._y)

    def _on_chat_cancelled(self) -> None:
        """Resume normal behavior if user closes the chat box without sending."""
        if self._phase == Phase.PAUSE:
            self._pause_elapsed = False
            self._brain_timer.start(AFTER_SPECIAL_REST_MS)

    def _on_chat_submitted(self, text: str, see_screen: bool = False) -> None:
        """Process user text input from the chat overlay and call Gemini AI in background."""
        if hasattr(self, "_chat_input"):
            self._chat_input.hide()

        if not text:
            self._phase = Phase.PAUSE
            self._pause_elapsed = False
            if self._can_play("angry"):
                self._play("angry")
            self._say("* Did a cat step on your keyboard, mew?! You didn't type anything!", force=True)
            return

        api_key = self._memory.get_api_key()
        if not api_key:
            self._phase = Phase.PAUSE
            self._pause_elapsed = False
            if self._can_play("shocked"):
                self._play("shocked")
            self._say("* MEW?! I don't have a Gemini API key yet!\n* Enter your key in the popup to awaken my brain!", force=True)
            QTimer.singleShot(600, self._prompt_api_key_dialog)
            return

        if self._gemini_thread is not None and self._gemini_thread.isRunning():
            self._say("* Hold your horses, minion! I'm already thinking about your last question!", force=True)
            return

        screenshot_b64 = None
        if see_screen:
            # Briefly hide Pink and speech bubble so she doesn't screenshot herself
            if hasattr(self, "_dialogue_overlay"):
                self._dialogue_overlay.hide()
            self.hide()
            QApplication.processEvents()
            screenshot_b64 = capture_screen_base64()
            self.show()

        # Enter thinking state
        self._phase = Phase.PAUSE
        self._pause_elapsed = False
        self._brain_timer.stop()

        thinking_anim = "behind" if self._can_play("behind") else "idle"
        self._play(thinking_anim)
        self._say("* (Inspecting your screen...)" if see_screen else "* ...", force=True, skippable=False)

        # Build prompt & system instruction
        system_inst = PINK_SYSTEM_INSTRUCTION
        if see_screen:
            system_inst += "\n\nThe user enabled screen vision! The attached image is a screenshot of their current desktop. Accurately comment on what they have open or what they asked about their screen!"
        facts = self._memory.get_long_term_facts()
        if facts:
            system_inst += f"\n\nThings you remember about this user across sessions:\n{facts}"

        # Spawn background worker thread
        self._gemini_thread = GeminiWorkerThread(
            api_key=api_key,
            user_prompt=text,
            system_instruction=system_inst,
            history=self._memory.history,
            screenshot_b64=screenshot_b64,
            model_name=GEMINI_MODEL,
            parent=self,
        )
        self._gemini_thread.response_ready.connect(
            lambda spoken_text, anim, u=text, s=see_screen: self._on_gemini_response(u, spoken_text, anim, s)
        )
        self._gemini_thread.error_occurred.connect(self._on_gemini_error)
        self._gemini_thread.start()

    def _on_gemini_response(self, user_text: str, spoken_text: str, anim: str, had_screen: bool) -> None:
        """Handle response generated by Gemini AI."""
        self._memory.record_turn(user_text, spoken_text, anim, had_screen=had_screen)

        if hasattr(self, "_dialogue_overlay") and self._dialogue_overlay.is_active():
            self._dialogue_overlay.dismiss(clear_queue=True)

        if anim and self._can_play(anim):
            self._play(anim)
        self._say(spoken_text, force=True)

    def _on_gemini_error(self, error_msg: str) -> None:
        """Handle error from Gemini AI."""
        if hasattr(self, "_dialogue_overlay") and self._dialogue_overlay.is_active():
            self._dialogue_overlay.dismiss(clear_queue=True)

        if self._can_play("shocked"):
            self._play("shocked")
        self._say(f"* Mew?! My magic brain stumbled:\n* {error_msg[:90]}", force=True)

    def _prompt_api_key_dialog(self) -> None:
        """Open modal dialog to enter or update the Gemini API key."""
        current_key = self._memory.get_api_key()
        masked = (current_key[:6] + "..." + current_key[-4:]) if len(current_key) > 10 else (current_key or "Not configured")

        key, ok = QInputDialog.getText(
            None,
            "Google Gemini API Key",
            f"Enter your Google Gemini API Key:\n(Current: {masked})\n\nStored locally on your device in .env and memory/config.json.",
            QLineEdit.Normal,
            current_key,
        )
        if ok:
            clean_key = key.strip()
            self._memory.save_api_key(clean_key)
            if clean_key:
                self._say("* Gemini API key saved to local storage! My magic brain is online, mew!", force=True)
                if self._can_play("peace_sign"):
                    self._play("peace_sign")
            else:
                self._say("* Cleared Gemini API key! Back in offline mode, mew.", force=True)

    def _open_memory_folder(self) -> None:
        """Open the local memory storage folder in Windows Explorer."""
        try:
            os.startfile(str(self._memory.memory_dir))
        except Exception as err:
            log.warning("Could not open memory folder: %s", err)

    def _reset_session_memory(self) -> None:
        """Clear recent in-memory conversation history and start a new session file."""
        self._memory.clear_current_session()
        self._say("* Session memory cleared! A clean slate for our chats, mew!", force=True)
        if self._can_play("peace_sign"):
            self._play("peace_sign")

    def _on_song_started(self, title: str, artist: str) -> None:
        """React to newly started music playback via Windows GSMTC."""
        if not self._dialogue_enabled or not hasattr(self, "_dialogue_overlay"):
            return
        if self._phase in (Phase.HIDE_PEEK, Phase.HIDE_OUTRO,
                           Phase.SUMMON_DIALOGUE, Phase.SUMMON_INTRO,
                           Phase.EXIT_OUTRO):
            return
        clean_title = title.strip()
        clean_artist = artist.strip()
        if not clean_title:
            return

        log.info("Song started: '%s' by '%s'", clean_title, clean_artist or "Unknown")

        # Format title & artist to fit neatly in dialogue bubble
        display_title = clean_title if len(clean_title) <= 50 else clean_title[:47] + "..."
        display_artist = clean_artist if len(clean_artist) <= 35 else clean_artist[:32] + "..."

        if display_artist:
            line = f"* Now playing: {display_title} by {display_artist}"
        else:
            line = f"* Now playing: {display_title}"

        extra_queue: list[str] = []
        check_str = f"{clean_artist} {clean_title}".lower()
        if "toby fox" in check_str or "toby 'radiation' fox" in check_str:
            toby_lines = DIALOGUE_LINES.get("toby_fox_familiar", [
                "* (Wait... this sounds strangely familiar...)",
                "* (... Huh? Have I heard this song before?)",
                "* (This melody... where do I know this from...?)",
                "* (Wait... why does this feel so familiar...?)",
                "* (... Did someone from Hometown compose this?)",
            ])
            extra_queue.append(random.choice(toby_lines))

        self._say(line, force=True, extra_queue=extra_queue)

    # -------------------------------------------------------------- animation
    def _can_play(self, state: str) -> bool:
        """Original states always work (placeholder fallback); new ones need real sprites."""
        return state in ORIGINAL_STATES or self._bank.has_real_sprites(state)

    def _play(self, state: str, loop: bool | None = None, mirrored: bool = False) -> None:
        """Start playing `state` from its first frame.

        loop=None -> looping for idle / walk_* / run_* / airborne / hanging, one-shot for
                     everything else.
        mirrored  -> draw the horizontally mirrored copy of the art (only the jump art has one).
        """
        if state not in (BURNT_STATE, "burnt"):
            self._stop_overlay()

        old_hand_x, old_hand_y = (0.0, 0.0)
        should_adjust = (hasattr(self, "_phase")
                         and (self._phase in (Phase.HANG, Phase.THROW)
                              or (self._phase is Phase.FALL and self.state == THROW_STATE)))
        if should_adjust:
            old_hand_x, old_hand_y = self._hand_offset()

        self.state = state
        flipped = mirrored_key(state)
        self._sprite_key = flipped if mirrored and flipped in self._bank.frames else state
        self._loop = (state in LOOPING_STATES + LOOPING_REST_STATES + JUMP_STATES) if loop is None else loop
        interval = FRAME_INTERVAL_MS.get(state, ANIM_INTERVAL_MS)   # this state's frame speed
        if self._anim_timer.interval() != interval:                 # (setInterval restarts the timer)
            self._anim_timer.setInterval(interval)
        self._repeat_count = max(0, SPECIAL_REPEAT_COUNT.get(state, 1) - 1) if not self._loop else 0
        self._hold_ticks = 0 if self._loop else LAST_FRAME_HOLD_MS.get(state, 0) // interval
        sub_loop = FRAME_SUB_LOOPS.get(state)
        if sub_loop:
            start_f, end_f = sub_loop[0], sub_loop[1]
            rep = sub_loop[2] if len(sub_loop) > 2 else SPECIAL_REPEAT_COUNT.get(state, 4)
            self._sub_loop_range = (start_f - 1, end_f - 1)
            self._sub_loop_count = rep if not self._loop else -1
        else:
            self._sub_loop_range = None
            self._sub_loop_count = 0
        self._set_frame(0)

        if should_adjust:
            new_hand_x, new_hand_y = self._hand_offset()
            self._x += (old_hand_x - new_hand_x)
            self._y += (old_hand_y - new_hand_y)
            self._sync_window_position()

        if state in (BURNT_STATE, "burnt") and "explosion" in self._bank.frames and self._overlay_state != "explosion":
            self._start_overlay("explosion")

    def _set_frame(self, index: int) -> None:
        """Show frame `index` of the current state (and update the click-through mask)."""
        frames = self._bank.frames[self._sprite_key]
        self._frame_idx = min(index, len(frames) - 1)
        frame = frames[self._frame_idx]
        self._pixmap = frame.pixmap
        dpr = frame.pixmap.devicePixelRatio() if frame.pixmap.devicePixelRatio() > 0 else 1.0
        target_w = round(frame.pixmap.width() / dpr)
        target_h = round(frame.pixmap.height() / dpr)
        if self.width() != target_w or self.height() != target_h:
            self.setFixedSize(target_w, target_h)
        if CLICK_THROUGH_TRANSPARENT:
            self.setMask(self._mask_for(frame))   # window shape = visible pixels -> clicks pass through
        self.update()

        # Trigger explosion whenever the burnt sprite shows up
        if self._sprite_key in (BURNT_STATE, "burnt") and self._overlay_state != "explosion":
            if "explosion" in self._bank.frames:
                self._start_overlay("explosion")

    def _mask_for(self, frame: Frame) -> QRegion:
        """Window shape for `frame`: its visible pixels.

        With DEBUG_DRAW_HAND_ANCHOR the little box around the crosshair is added while she hangs,
        otherwise the mask would clip the crosshair whenever the hands are on a transparent pixel.
        """
        mask = frame.mask
        if self._phase == Phase.HIDE_PEEK:
            return mask.intersected(QRegion(0, 0, self.width(), EAR_PEEK_HEIGHT_PX))
        if self._phase == Phase.HIDE_OUTRO and getattr(self, "_hide_subphase", "") in ("ghost_rise_from_below", "ghost_sink"):
            area = QApplication.primaryScreen().availableGeometry()
            vis_h = max(0, min(self.height(), round(area.y() + area.height() - self._y)))
            return mask.intersected(QRegion(0, 0, self.width(), vis_h))
        if DEBUG_DRAW_HAND_ANCHOR and self.state == HANGING_STATE:
            hand_x, hand_y = self._hand_offset()
            reach = DEBUG_CROSSHAIR_PX + 2
            return mask.united(QRegion(round(hand_x) - reach, round(hand_y) - reach,
                                       2 * reach + 1, 2 * reach + 1))
        return mask

    def _advance_frame(self) -> None:
        """Animation timer (~5.5 FPS): step to the next frame / finish a one-shot."""
        # High DPI: if the display scale changed (settings, another monitor), re-render.
        dpr = self.devicePixelRatioF()
        if abs(dpr - self._bank.dpr) > 0.01:
            self._bank.rebuild(dpr)
            self._set_frame(self._frame_idx)
            if self._overlay_state:
                ov_frames = self._bank.frames.get(self._overlay_state, [])
                if ov_frames and self._overlay_frame_idx < len(ov_frames):
                    self._show_overlay_frame(ov_frames[self._overlay_frame_idx].pixmap)

        count = len(self._bank.frames[self._sprite_key])
        if count == 0:
            return

        # Handle sub-frame loops (e.g. intro frames played once, then looping frames 3 & 4)
        if self._sub_loop_range:
            start_idx, end_idx = self._sub_loop_range
            if 0 <= start_idx <= end_idx < count:
                if self._frame_idx == end_idx:
                    if self._loop or self._sub_loop_count > 0:
                        if not self._loop:
                            self._sub_loop_count -= 1
                        self._set_frame(start_idx)
                        return

        # Custom frame progression and looping for THROW_STATE
        if self.state == THROW_STATE:
            # 1. On first throw, pause briefly at frame 11 (0-indexed: 10)
            if self._frame_idx == 10 and self._throw_pause_ticks > 0:
                self._throw_pause_ticks -= 1
                return

            if self._frame_idx + 1 < count:
                next_idx = self._frame_idx + 1
                self._set_frame(next_idx)

                # 2. Starting from frame 12 (0-indexed: 11), speed accelerates 2.5x
                if next_idx >= 11:
                    if self._anim_timer.interval() != THROW_FAST_INTERVAL_MS:
                        self._anim_timer.setInterval(THROW_FAST_INTERVAL_MS)

                # 3. Release bomb at frame 12 (0-indexed: 11)
                if next_idx >= 11 and not self._bombs_spawned_for_current_throw:
                    self._bombs_spawned_for_current_throw = True
                    self._spawn_single_bomb(self._hang_bomb_index)
                    self._hang_bomb_index += 1
                    self._hang_bomb_count_remaining -= 1
                return

            # Reached frame 14 (0-indexed: 13, which is count - 1)
            # 4. Loop back to frame 4 (0-indexed: 3) until the last throw
            if self._hang_bomb_count_remaining > 0:
                self._bombs_spawned_for_current_throw = False
                self._set_frame(3)  # frame 4 is 0-indexed 3
                return

            # All 4 throws completed!
            self._finish_throw_sequence()
            return

        if self._frame_idx + 1 < count:
            self._set_frame(self._frame_idx + 1)
        elif self._loop:
            if count > 1:
                self._set_frame(0)               # wrap around
        elif self._post_throw_laugh and self.state == "laughing":
            now = time.perf_counter()
            if not self._can_end_post_throw_laugh(now):
                self._set_frame(0)               # keep laughing while bombs/lasers active + extra 1+ s
            else:
                self._post_throw_laugh = False
                self._finish_one_shot()
        elif self._repeat_count > 0:
            self._repeat_count -= 1
            self._set_frame(0)                   # repeat another cycle
        elif self._hold_ticks > 0:
            self._hold_ticks -= 1                # freeze on the last frame (e.g. burnt)
        else:
            self._finish_one_shot()

    def _finish_throw_sequence(self) -> None:
        """Finished 4-bomb barrage floating mid-air: fall laughing down to the ground."""
        self._anim_timer.setInterval(FRAME_INTERVAL_MS.get("laughing", ANIM_INTERVAL_MS))
        self._hang_bomb_count_remaining = 0
        self._hang_bomb_index = 0
        self._throw_pause_ticks = 0
        self._throw_rise_px = 0.0
        self._bombs_spawned_for_current_throw = False
        self._begin_fall(JUMP_GRAVITY_PX_S2, reaction="laughing")
        self._post_throw_laugh = True
        self._play("laughing", loop=True)
        log.debug("Finished throw barrage: falling laughing from mid-air to ground")

    def _can_end_post_throw_laugh(self, now: float) -> bool:
        """Check if post-throw victory laugh can end.

        Must laugh until all bombs have exploded, all lasers have cleared, and at least
        BOMB_LAUGH_EXTRA_S has elapsed since the last bomb explosion.
        """
        if self._throw_started_at > 0.0 and (now - self._throw_started_at) > 20.0:
            return True  # failsafe timeout
        if self._hang_bomb_count_remaining > 0:
            return False
        if self._bomb_overlay.has_active_bombs():
            return False
        if self._bomb_overlay.has_active_lasers():
            return False
        last_exploded = self._bomb_overlay.last_bomb_exploded_at
        if last_exploded <= 0.0:
            return False
        return now >= (last_exploded + BOMB_LAUGH_EXTRA_S)

    def _keep_angry(self) -> None:
        """Keep Pink continuously mad while clicks keep coming in the angry spam."""
        self._in_angry_spam = True
        self._last_angry_click_time = time.perf_counter()
        if self._phase is not Phase.PAUSE:
            self._phase = Phase.PAUSE
        if self.state != "angry":
            if self._can_play("angry"):
                self._play("angry")
        angry_cycles = max(1, SPECIAL_REPEAT_COUNT.get("angry", 6) - 1)
        self._repeat_count = max(self._repeat_count, angry_cycles)
        self._brain_timer.start(random_ms(PAUSE_MIN_S, PAUSE_MAX_S))
        self._pause_elapsed = False
        self.update()

    def _finish_one_shot(self) -> None:
        """A special animation ended: resume previous activity or return to idle."""
        # If interrupted by window switch, resume previous state
        if self._interrupted_state:
            saved = self._interrupted_state
            self._interrupted_state = None
            self._phase = saved["phase"]
            self._play(saved["state"], loop=saved["loop"])
            self._brain_timer.start(saved["rem_ms"])
            return

        if self._phase is Phase.HANG:
            self._play(HANGING_STATE, mirrored=self._hang_mirrored())
            return

        if self.state == "angry":
            now = time.perf_counter()
            # If clicks are still coming within the spam window, keep her angry!
            if self._in_angry_spam and (now - self._last_angry_click_time <= CLICK_ANGRY_WINDOW_S):
                self._keep_angry()
                self._set_frame(0)
                return
            self._in_angry_spam = False
            self._click_times.clear()

        self._play("idle")
        if self._phase is Phase.PAUSE and self._pause_elapsed:
            # The pause ran out while the special was still playing: rest briefly in idle
            # (so the return to idle is visible), then _on_brain_timeout starts the walk.
            self._pause_elapsed = False
            self._brain_timer.start(AFTER_SPECIAL_REST_MS)

    # -------------------------------------------------------- overlay / vfx
    def _show_overlay_frame(self, pixmap: QPixmap) -> None:
        """Position and draw the VFX overlay centered above the buddy's feet with matching floor."""
        center_x = self._x + SPRITE_SIZE / 2.0
        bottom_y = self._y + SPRITE_SIZE - FOOT_PADDING
        ground_ratio = EFFECT_GROUND_RATIO.get(self._overlay_state, 1.0)
        self._vfx_overlay.show_frame(pixmap, center_x, bottom_y, ground_ratio=ground_ratio)

    def _start_overlay(self, effect: str) -> None:
        """Start playing a one-shot foreground VFX animation."""
        frames = self._bank.frames.get(effect, [])
        if not frames:
            return
        self._overlay_state = effect
        self._overlay_frame_idx = 0
        frame = frames[0]
        self._overlay_pixmap = frame.pixmap
        self._overlay_timer.start(EXPLOSION_FRAME_INTERVAL_MS)
        self._show_overlay_frame(frame.pixmap)

    def _advance_overlay_frame(self) -> None:
        """Advance the foreground effect or stop when complete."""
        if not self._overlay_state:
            return
        frames = self._bank.frames.get(self._overlay_state, [])
        if self._overlay_frame_idx + 1 < len(frames):
            self._overlay_frame_idx += 1
            frame = frames[self._overlay_frame_idx]
            self._overlay_pixmap = frame.pixmap
            self._show_overlay_frame(frame.pixmap)
        else:
            self._stop_overlay()

    def _stop_overlay(self) -> None:
        """Clear overlay and dismiss VFX window."""
        if self._overlay_state is None and self._overlay_pixmap is None:
            return
        self._overlay_timer.stop()
        self._overlay_state = None
        self._overlay_pixmap = None
        if hasattr(self, "_vfx_overlay"):
            self._vfx_overlay.dismiss()

    # --------------------------------------------------------------- behaviour
    def _start_walk(self) -> None:
        """Walk for 3-8 s in a random direction (run or wistful walk by chance)."""
        self._phase = Phase.WALK
        self._pause_elapsed = False
        can_run = self._can_play("run_left") and self._can_play("run_right")
        can_wistful = self._can_play("wistful_walk_left") and self._can_play("wistful_walk_right")

        choices = ["walk"]
        weights = [1.0]
        if can_run:
            choices.append("run")
            weights.append(RUN_CHANCE)
            weights[0] -= RUN_CHANCE
        if can_wistful:
            choices.append("wistful_walk")
            weights.append(WISTFUL_WALK_CHANCE)
            weights[0] -= WISTFUL_WALK_CHANCE

        weights[0] = max(0.1, weights[0])
        gait = random.choices(choices, weights=weights)[0]

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

        if special:
            if special in DIALOGUE_LINES and DIALOGUE_LINES[special]:
                if special == "shocked":
                    if forced is not None:
                        now = time.perf_counter()
                        if (random.random() < DIALOGUE_CHANCE_ON_SHOCKED
                                and (now - self._last_shocked_dialogue_time >= DIALOGUE_SHOCKED_COOLDOWN_S)):
                            self._last_shocked_dialogue_time = now
                            self._say(special, force=True)
                else:
                    self._say(special, force=(forced is not None))
        else:
            if random.random() < DIALOGUE_CHANCE_ON_PAUSE:
                self._say("idle", force=False)

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
            if hasattr(self, "_dialogue_overlay") and self._dialogue_overlay.is_active():
                self._pause_elapsed = True
                return
            if self._loop:                 # plain idle -> jump at the cursor (rarely), else walk right away
                if not self._try_start_jump(self._cursor, MOVING_JUMP_CHANCE):
                    self._start_walk()
            else:                          # a special is still playing -> let it finish first
                self._pause_elapsed = True
        # DRAG / FALL / JUMP / HANG: the timer is stopped in those phases, nothing to do.

    # ---------------------------------------------------------------- movement
    def _tick_movement(self) -> None:
        """Movement timer (~45 FPS): walking / running, turning at edges, gravity, jump, hang."""
        now = time.perf_counter()
        real_dt = now - self._last_tick
        dt = min(real_dt, MAX_DT_S)                 # real elapsed time -> constant speed
        self._last_tick = now
        cursor = QCursor.pos()                      # THE cursor sample of this tick (no extra timer)
        self._track_cursor(cursor, now, real_dt)
        if getattr(self, "_is_ghost_talking", False):
            self.update()
        if self._dragging:                          # held by the mouse: stand still
            return
        if self._menu_open and self._phase is not Phase.FALL:
            # Menu open: she stands still (and shows idle). A fall is the exception: the menu
            # aborts a jump / hang into a fall, and she must not hang frozen in mid-air.
            self._rest_while_menu_open()
            return

        bounds = self._bounds()
        min_x, max_x, _min_y, ground_y = bounds

        if self._phase is Phase.HIDE_PEEK:
            area = QApplication.primaryScreen().availableGeometry()
            self._x = float(area.x() + area.width() - self.width() - EAR_PEEK_OFFSET_X)
            self._y = float(area.y() + area.height() - EAR_PEEK_HEIGHT_PX)
            self._sync_window_position()
            return

        if self._phase is Phase.SUMMON_DIALOGUE:
            return

        if self._phase is Phase.SUMMON_INTRO:
            self._tick_summon_intro(now, dt, bounds)
            self._sync_window_position()
            return

        if self._phase is Phase.HIDE_OUTRO:
            self._tick_hide_outro(now, dt, bounds)
            self._sync_window_position()
            return

        if self._phase is Phase.EXIT_OUTRO:
            self._tick_exit_outro(now, dt, bounds)
            if self.isVisible():
                self._sync_window_position()
            return

        if self._phase is Phase.HANG:               # no walking and NO gravity while she hangs
            self._tick_hang(cursor, now, dt, bounds)
            self._sync_window_position()
            return

        if self._phase is Phase.THROW:              # stops hanging from cursor, floats mid-air
            # First throw frames 1-5: float smoothly upwards
            if self._throw_rise_px > 0.0:
                rise_dur_s = 5 * (THROW_BASE_INTERVAL_MS / 1000.0)
                elapsed = max(0.0, now - self._throw_started_at)
                t = min(1.0, elapsed / rise_dur_s)
                smooth_t = t * t * (3.0 - 2.0 * t)  # smoothstep S-curve
                self._y = self._throw_start_y - smooth_t * self._throw_rise_px
            self._sync_window_position()
            return

        # Horizontal: walk / run, and turn around when an edge of the screen is reached.
        if self._phase in (Phase.JUMP, Phase.FALL):
            # A jump drifts at the sideways speed fixed at take-off - deliberately NOT looked
            # up in MOVE_VELOCITY_PX_S by state name.
            self._x += self._vx * dt
            if self._x <= min_x and self._vx < 0.0:
                self._x = min_x
                self._bounce_from_wall("left")
            elif self._x >= max_x and self._vx > 0.0:
                self._x = max_x
                self._bounce_from_wall("right")
        else:
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

        # Vertical: gravity rules only while falling or jumping (rise AND fall); in every
        # other phase she simply stands on the ground, which also follows a moving taskbar.
        if self._phase in (Phase.FALL, Phase.JUMP):
            self._tick_airborne(cursor, now, dt, bounds)
        else:
            self._y = ground_y
            self._vy = 0.0

        self._sync_window_position()

        # Jump triggers - only ever from a standing WALK / PAUSE - or the armed debug-menu jump.
        if self._debug_jump_at is not None and now >= self._debug_jump_at:
            self._fire_debug_jump(cursor)
        elif self._jump_enabled and self._phase in (Phase.WALK, Phase.PAUSE):
            self._check_still_trigger(cursor, now)

    def _turn_around(self, heading: str) -> None:
        """The pet hit a screen edge: carry on ("left" / "right"), keeping walk / run mode."""
        next_state = f"{self.state.rsplit('_', 1)[0]}_{heading}"   # walk_left -> walk_right ...
        self._play(next_state)

    # ---------------------------------------------------- startup summon intro
    def _on_peek_ears_clicked(self) -> None:
        """User clicked Pink's peeking ears: she notices and begins the summon dialogue!"""
        if self._phase != Phase.HIDE_PEEK:
            return
        self._phase = Phase.SUMMON_DIALOGUE
        if self._dialogue_enabled and hasattr(self, "_dialogue_overlay"):
            self._say("* ...", force=True, extra_queue=["* ..?"])
        else:
            QTimer.singleShot(600, self._start_summon_intro)

    def _start_summon_intro(self) -> None:
        """Ghost goes up FAST, pauses looking right & left, flies off right, then shocked pops in."""
        if self._phase == Phase.SUMMON_INTRO:
            return
        if hasattr(self, "_dialogue_overlay") and self._dialogue_overlay.is_active():
            self._dialogue_overlay.dismiss(clear_queue=True)

        self._phase = Phase.SUMMON_INTRO
        self._intro_subphase = "rise"
        self._intro_timer = 0.0
        self._play(GHOST_STATE, loop=True, mirrored=False)
        frame = self._bank.frames[self._sprite_key][self._frame_idx]
        if CLICK_THROUGH_TRANSPARENT:
            self.setMask(self._mask_for(frame))
        self.update()

        area = QApplication.primaryScreen().availableGeometry()
        ground_y = float(area.y() + area.height() - self.height() + FOOT_PADDING)
        self._intro_apex_y = ground_y
        self._vy = -340.0
        self._vx = 0.0

    def _tick_summon_intro(self, now: float, dt: float, bounds: tuple[float, float, float, float]) -> None:
        min_x, max_x, min_y, ground_y = bounds
        area = QApplication.primaryScreen().availableGeometry()
        screen_right = float(area.x() + area.width())

        if self._intro_subphase == "rise":
            self._y += self._vy * dt
            if self._y <= self._intro_apex_y:
                self._y = self._intro_apex_y
                self._vy = 0.0
                self._intro_subphase = "look_right"
                self._intro_timer = 0.0
                self._play(GHOST_STATE, loop=True, mirrored=True)

        elif self._intro_subphase == "look_right":
            self._intro_timer += dt
            if self._intro_timer >= 0.85:
                self._intro_subphase = "look_left"
                self._intro_timer = 0.0
                self._play(GHOST_STATE, loop=True, mirrored=False)

        elif self._intro_subphase == "look_left":
            self._intro_timer += dt
            if self._intro_timer >= 0.85:
                self._intro_subphase = "fly_off_right"
                self._intro_timer = 0.0
                self._play(GHOST_STATE, loop=True, mirrored=True)
                self._vx = 700.0

        elif self._intro_subphase == "fly_off_right":
            self._x += self._vx * dt
            if self._x >= screen_right + 40.0:
                # Ghost is off-screen -> pause for 0.75s before Pink bursts in!
                self._intro_subphase = "offscreen_delay"
                self._intro_timer = 0.0
                self._vx = 0.0
                self._x = screen_right + 50.0

        elif self._intro_subphase == "offscreen_delay":
            self._intro_timer += dt
            if self._intro_timer >= 0.75:
                # 0.75s delay finished -> shocked doll pops in from the right off screen!
                self._intro_subphase = "pop_in_shocked"
                self._play("shocked", loop=True)
                self._y = ground_y
                self._x = screen_right + 10.0
                self._intro_target_land_x = screen_right - self.width() - 80.0
                self._vx = -520.0

        elif self._intro_subphase == "pop_in_shocked":
            self._x += self._vx * dt
            if self._x <= self._intro_target_land_x:
                self._x = self._intro_target_land_x
                self._vx = 0.0
                self._intro_subphase = "landed_shocked"
                self._intro_timer = 0.0

        elif self._intro_subphase == "landed_shocked":
            self._intro_timer += dt
            if self._intro_timer >= 0.6:
                self._finish_summon_sequence()

    def _finish_summon_sequence(self) -> None:
        """Pink has arrived on the taskbar! Deliver a quick shocked line and begin normal pet life."""
        self._phase = Phase.PAUSE
        self._play("shocked", loop=False)

        line = random.choice(SUMMON_OPENING_LINES)
        self._say(line, force=True)

        self._brain_timer.start(random_ms(PAUSE_MIN_S, PAUSE_MAX_S))
        self._pause_elapsed = False

    # ---------------------------------------------------- hide sequence (outro)
    def _start_hide_sequence(self) -> None:
        """User chose 'Hide': Pink runs to the right offscreen, then the ghost slowly takes over the hide spot."""
        if self._phase in (Phase.HIDE_PEEK, Phase.SUMMON_DIALOGUE, Phase.SUMMON_INTRO, Phase.HIDE_OUTRO, Phase.EXIT_OUTRO):
            return
        if hasattr(self, "_dialogue_overlay"):
            self._dialogue_overlay.dismiss(clear_queue=True)
        if hasattr(self, "_chat_input"):
            self._chat_input.cancel()
        self._brain_timer.stop()
        self._pause_elapsed = False
        self._reset_jump_state()
        self._interrupted_state = None
        self._in_angry_spam = False
        self._click_times.clear()
        self._dragging = False
        self._press_global = None
        self._stop_overlay()
        if hasattr(self, "_bomb_overlay"):
            self._bomb_overlay.close()

        bounds = self._bounds()
        ground_y = bounds[3]
        self._y = ground_y
        self._vy = 0.0
        self._vx = 520.0
        self._facing = "right"
        self._phase = Phase.HIDE_OUTRO
        self._hide_subphase = "run_right"
        self._hide_timer = 0.0
        self._play("run_right", loop=True)
        log.info("Hide sequence started: Pink running right...")

    def _tick_hide_outro(self, now: float, dt: float, bounds: tuple[float, float, float, float]) -> None:
        _min_x, _max_x, _min_y, ground_y = bounds
        area = QApplication.primaryScreen().availableGeometry()
        screen_right = float(area.x() + area.width())
        target_hide_x = float(area.x() + area.width() - self.width() - EAR_PEEK_OFFSET_X)
        target_hide_y = float(area.y() + area.height() - EAR_PEEK_HEIGHT_PX)

        if self._hide_subphase == "run_right":
            self._x += self._vx * dt
            if self._x >= screen_right + 40.0:
                # Pink is completely offscreen right -> brief delay before ghost emerges
                self._hide_subphase = "offscreen_delay"
                self._hide_timer = 0.0
                self._vx = 0.0

        elif self._hide_subphase == "offscreen_delay":
            self._hide_timer += dt
            if self._hide_timer >= 0.4:
                # Ghost emerges from below at the hiding spot!
                self._play(GHOST_STATE, loop=True, mirrored=False)
                self._x = target_hide_x
                self._y = float(area.y() + area.height())
                self._vx = 0.0
                self._vy = -20.0  # slowly rises up from below the taskbar
                self._hide_subphase = "ghost_rise_from_below"
                if CLICK_THROUGH_TRANSPARENT:
                    self.setMask(QRegion(0, 0, self.width(), 0))
                self._sync_window_position()
                self.update()

        elif self._hide_subphase == "ghost_rise_from_below":
            self._y += self._vy * dt
            if self._y <= target_hide_y:
                self._y = target_hide_y
                self._vy = 0.0
                self._finish_hide_sequence()
                return
            frame = self._bank.frames[self._sprite_key][self._frame_idx]
            vis_h = max(0, min(self.height(), round(area.y() + area.height() - self._y)))
            if CLICK_THROUGH_TRANSPARENT:
                self.setMask(frame.mask.intersected(QRegion(0, 0, self.width(), vis_h)))
            self.update()

    def _finish_hide_sequence(self) -> None:
        """Ghost has reached the peeking ears position: lock into Phase.HIDE_PEEK."""
        self._phase = Phase.HIDE_PEEK
        self.state = GHOST_STATE
        self._sprite_key = GHOST_STATE
        self._frame_idx = 0
        self._loop = True
        self._set_frame(0)
        self._sync_window_position()
        self.update()
        log.info("Hide sequence completed: Pink settled into HIDE_PEEK")

    # ---------------------------------------------------- exit sequence (outro)
    def _start_exit_outro(self) -> None:
        """User chose 'Exit': Pink runs to the furthest screen edge offscreen, then the application quits."""
        if self._phase is Phase.EXIT_OUTRO:
            return
        if self._phase in (Phase.HIDE_PEEK, Phase.HIDE_OUTRO):
            self._do_real_quit()
            return

        if hasattr(self, "_dialogue_overlay"):
            self._dialogue_overlay.dismiss(clear_queue=True)
        self._brain_timer.stop()
        self._pause_elapsed = False
        self._reset_jump_state()
        self._interrupted_state = None
        self._in_angry_spam = False
        self._click_times.clear()
        self._dragging = False
        self._press_global = None
        self._stop_overlay()
        if hasattr(self, "_bomb_overlay"):
            self._bomb_overlay.close()

        bounds = self._bounds()
        ground_y = bounds[3]
        self._y = ground_y
        self._vy = 0.0

        area = QApplication.primaryScreen().availableGeometry()
        screen_left = float(area.x())
        screen_right = float(area.x() + area.width())
        dist_left = self._x - screen_left
        dist_right = screen_right - (self._x + self.width())

        self._phase = Phase.EXIT_OUTRO
        if dist_right >= dist_left:
            self._facing = "right"
            self._vx = 520.0
            self._play("run_right", loop=True)
            log.info("Exit sequence started: Pink running right towards furthest edge...")
        else:
            self._facing = "left"
            self._vx = -520.0
            self._play("run_left", loop=True)
            log.info("Exit sequence started: Pink running left towards furthest edge...")

    def _tick_exit_outro(self, now: float, dt: float, bounds: tuple[float, float, float, float]) -> None:
        _min_x, _max_x, _min_y, ground_y = bounds
        self._y = ground_y
        area = QApplication.primaryScreen().availableGeometry()
        screen_left = float(area.x())
        screen_right = float(area.x() + area.width())

        self._x += self._vx * dt
        if self._vx > 0.0:
            if self._x >= screen_right + 10.0:
                log.info("Exit run finished (offscreen right): exiting application.")
                self._do_real_quit()
        else:
            if self._x <= screen_left - self.width() - 10.0:
                log.info("Exit run finished (offscreen left): exiting application.")
                self._do_real_quit()

    # ------------------------------------------------- jump: cursor + geometry
    def _track_cursor(self, cursor: QPoint, now: float, real_dt: float) -> None:
        """Per-tick bookkeeping of the cursor sample: how long it has been still, how fast it moves.

        Stillness is measured from an ANCHOR (where the cursor last really moved), not between
        neighbouring samples, so a slow drift cannot creep under the dead zone for ever.
        """
        gap = math.hypot(cursor.x() - self._still_anchor.x(), cursor.y() - self._still_anchor.y())
        if gap >= STILL_DEAD_ZONE_PX:                # it moved: the stillness clock restarts here
            self._still_anchor = cursor
            self._still_since = now
        if JUMP_LEAD_TIME_S > 0.0 and real_dt > 0.0:   # the speed is only needed for the optional lead
            blend = 1.0 - math.exp(-real_dt / max(JUMP_LEAD_SMOOTH_S, 0.001))
            self._cursor_vx += ((cursor.x() - self._cursor.x()) / real_dt - self._cursor_vx) * blend
            self._cursor_vy += ((cursor.y() - self._cursor.y()) / real_dt - self._cursor_vy) * blend
        self._cursor = cursor

    def _hang_mirrored(self) -> bool:
        """Is the hanging art drawn mirrored for the current facing? (Never, if it is front-facing.)"""
        return HANGING_ART_FACES != "none" and self._facing != HANGING_ART_FACES

    def _throw_mirrored(self) -> bool:
        """Throw art faces left by default; mirror if pet faces right."""
        return self._facing == "right"

    def _airborne_mirrored(self) -> bool:
        """Is the airborne art drawn mirrored? True when the jump heads the other way than the art looks."""
        return self._facing != AIRBORNE_ART_FACES

    def _hand_offset(self) -> tuple[float, float]:
        """Where her hands are, in px from the window's top-left corner.

        HAND_ANCHOR describes the hanging art as drawn; when that art is shown mirrored the
        hands move to the other side of the square together with it.
        During THROW_STATE, anchor matches the hanging head position at (0.5 * width, 95.5)
        to prevent vertical jumps or jitter.
        """
        if self.state == THROW_STATE:
            frac_x = 0.5
            return frac_x * self.width(), 95.5
        frac_x, frac_y = HAND_ANCHOR
        if self._hang_mirrored():
            frac_x = 1.0 - frac_x
        return frac_x * SPRITE_SIZE, frac_y * SPRITE_SIZE

    def _required_rise(self, cursor: QPoint) -> float:
        """How far her window must climb so that the hands reach `cursor` (negative: it is below).

        = her current window y minus the window y that puts the hand anchor on the cursor.
        A cursor too close to the ground to hang below gives a small or negative rise.
        """
        hand_y = self._hand_offset()[1]
        return self._y - (cursor.y() - hand_y)

    # ------------------------------------------------------ jump: the trigger
    def _can_jump(self, cursor: QPoint) -> bool:
        """Every gate of the trigger (the dice are rolled by the caller). Cheap checks come first.

        feature on + cooldown over | phase WALK / PAUSE, plain looping animation, menu closed |
        cursor on the work area | rise at least MIN_JUMP_RISE_PX | no mouse button held anywhere
        """
        if not self._jump_enabled or time.perf_counter() < self._jump_ready_at:
            return False                             # sprites missing / cooldown still running
        if self._phase not in (Phase.WALK, Phase.PAUSE) or self._menu_open:
            return False                             # never in drag / fall / jump / hang, nor with the menu open
        if self.state not in LOOPING_STATES:
            return False                             # never in the middle of a one-shot special
        if not self._work_area().contains(cursor):
            return False                             # on the taskbar or on another monitor
        if self._required_rise(cursor) < MIN_JUMP_RISE_PX:
            return False                             # too low / too close to the ground to hang below
        return not any_mouse_button_down()           # a held button = a drag or selection somewhere else

    def _try_start_jump(self, cursor: QPoint, chance: float) -> bool:
        """Both trigger paths end here: all gates must pass, then one roll of `chance`."""
        if not self._can_jump(cursor) or random.random() >= chance:
            return False
        return self._begin_jump(cursor)

    def _check_still_trigger(self, cursor: QPoint, now: float) -> None:
        """STILL CURSOR (the main path): after STILL_TIME_S of stillness, one roll per check interval."""
        if now - self._still_since < STILL_TIME_S or now < self._next_still_check_at:
            return
        self._next_still_check_at = now + STILL_CHECK_INTERVAL_S
        self._try_start_jump(cursor, STILL_JUMP_CHANCE)

    # -------------------------------------------------------- jump: the flight
    def _aim_point(self, cursor: QPoint) -> tuple[float, float]:
        """Where the hands should end up: the cursor, optionally led ahead by JUMP_LEAD_TIME_S.

        Clamped to the work area, so a lead (or a debug jump) can never aim off the screen.
        """
        area = self._work_area()
        x = cursor.x() + self._cursor_vx * JUMP_LEAD_TIME_S
        y = cursor.y() + self._cursor_vy * JUMP_LEAD_TIME_S
        return (min(max(x, area.left()), area.right()),
                min(max(y, area.top()), area.bottom()))

    def _begin_jump(self, cursor: QPoint) -> bool:
        """Take off towards the cursor. The arc is worked out ONCE, here; nothing steers her later."""
        min_x, max_x, _min_y, _ground_y = self._bounds()
        aim_x, aim_y = self._aim_point(cursor)

        # Heading -> which way the airborne art faces. About-zero distance keeps the last facing.
        sideways = (aim_x - self._hand_offset()[0]) - self._x
        if abs(sideways) > JUMP_FACING_DEAD_ZONE_PX:
            self._facing = "right" if sideways > 0 else "left"

        hand_x, hand_y = self._hand_offset()         # (the hands follow the mirroring of the art)
        target_x = min(max(aim_x - hand_x, min_x), max_x)   # window position that puts the hands on the aim
        required_rise = self._y - (aim_y - hand_y)
        if required_rise < 1.0:                      # nothing to climb (also keeps the sqrt below real)
            return False
        rise = min(required_rise, MAX_JUMP_HEIGHT_PX)
        launch_speed = math.sqrt(2.0 * JUMP_GRAVITY_PX_S2 * rise)
        time_to_apex = launch_speed / JUMP_GRAVITY_PX_S2
        drift = (target_x - self._x) / time_to_apex

        self._jump_active = True                     # the cooldown starts when this sequence lands
        self._phase = Phase.JUMP
        if hasattr(self, "_dialogue_overlay"):
            self._dialogue_overlay.dismiss(clear_queue=True)
        self._brain_timer.stop()                     # no walk / pause timeout may fire mid-air
        self._pause_elapsed = False
        self._gravity = JUMP_GRAVITY_PX_S2
        self._vy = -launch_speed                     # upward = negative
        self._vx = max(-JUMP_MAX_HSPEED_PX_S, min(JUMP_MAX_HSPEED_PX_S, drift))
        self._pending_reaction = None
        self._wall_bounced = False
        self._can_catch_cursor = True
        self._shake_trail.clear()
        self._play(AIRBORNE_STATE, mirrored=self._airborne_mirrored())
        log.debug("Jump %s: rise %.0f px (asked %.0f), launch %.0f px/s, apex in %.2f s, "
                  "drift %.0f px/s (asked %.0f)", self._facing, rise, required_rise, launch_speed,
                  time_to_apex, self._vx, drift)
        return True

    def _tick_airborne(self, cursor: QPoint, now: float, dt: float,
                       bounds: tuple[float, float, float, float]) -> None:
        """One gravity step of a JUMP (rise, apex, fall after a miss) or of a FALL; ends on touchdown."""
        _min_x, _max_x, min_y, ground_y = bounds
        vy_before = self._vy
        self._y += self._vy * dt + 0.5 * self._gravity * dt * dt
        self._vy += self._gravity * dt

        if self._y < min_y:                          # the top edge of the work area is a ceiling
            self._y = min_y
            self._vy = max(self._vy, 0.0)            # bumped her head: the rise ends here (= apex)

        # Catch the cursor whenever she touches the mouse while airborne (before she has caught it)
        if self._can_catch_cursor and self._touches_cursor(cursor) and self._can_hang_from(cursor):
            log.debug("Airborne grab: touched mouse -> GRAB")
            self._begin_hang(now)
            return

        if self._phase is Phase.JUMP and vy_before < 0.0 <= self._vy:
            self._resolve_apex(cursor, now)          # the vertical speed just crossed zero

        # Touch-down. NEVER while she is moving upward: a launch starts exactly ON the ground.
        if self._vy >= 0.0 and self._y >= ground_y:
            self._y = ground_y
            self._touch_down()

    def _resolve_apex(self, cursor: QPoint, now: float) -> None:
        """Top of the arc: reached apex without grab -> continue with miss reaction."""
        log.debug("Apex: top of arc -> MISS%s",
                  " (wall bounce)" if self._wall_bounced else "")
        self._vx *= JUMP_MISS_HSPEED_KEEP        # (nearly) straight down from here
        self._pending_reaction = MISS_REACTION   # played on touchdown

    def _update_airborne_facing(self) -> None:
        """Update sprite mirroring and mask to match the current heading while airborne."""
        if self.state != AIRBORNE_STATE:
            return
        flipped = mirrored_key(AIRBORNE_STATE)
        self._sprite_key = flipped if self._airborne_mirrored() and flipped in self._bank.frames else AIRBORNE_STATE
        if self._sprite_key in self._bank.frames:
            frames = self._bank.frames[self._sprite_key]
            if frames:
                self._frame_idx = min(self._frame_idx, len(frames) - 1)
                frame = frames[self._frame_idx]
                self._pixmap = frame.pixmap
                if CLICK_THROUGH_TRANSPARENT:
                    self.setMask(self._mask_for(frame))
                self.update()

    def _bounce_from_wall(self, side: str) -> None:
        """Bounce off a screen border during a jump or fall."""
        self._wall_bounced = True
        self._pending_reaction = MISS_REACTION   # hitting a wall guarantees a miss reaction on touchdown

        bounce_speed = min(JUMP_MAX_HSPEED_PX_S,
                           max(abs(self._vx) * JUMP_WALL_BOUNCE_FACTOR, JUMP_WALL_MIN_BOUNCE_PX_S))

        if side == "left":
            self._vx = bounce_speed
            self._facing = "right"
        else:
            self._vx = -bounce_speed
            self._facing = "left"

        if self._vy < 0.0:
            self._vy *= JUMP_WALL_V_DAMPING

        self._update_airborne_facing()
        log.debug("Wall bounce: %s wall, bounced %s with vx=%.0f px/s",
                  side, self._facing, self._vx)

    # -------------------------------------------------------- jump: the hang
    def _touches_cursor(self, cursor: QPoint) -> bool:
        """True if the cursor touches the pet's sprite or is within reach of her hands."""
        hand_x, hand_y = self._hand_offset()
        gap_hands = math.hypot(cursor.x() - (self._x + hand_x), cursor.y() - (self._y + hand_y))
        if gap_hands <= GRAB_RADIUS_PX:
            return True
        margin = 4.0
        return (self._x - margin <= cursor.x() <= self._x + SPRITE_SIZE + margin
                and self._y - margin <= cursor.y() <= self._y + SPRITE_SIZE + margin)

    def _can_hang_from(self, cursor: QPoint) -> bool:
        """The cursor is on the work area and high enough for her to dangle below it."""
        if not self._work_area().contains(cursor):
            return False
        area = self._work_area()
        normal_ground_y = float(area.y() + area.height() - SPRITE_SIZE + FOOT_PADDING)
        normal_hand_y = HAND_ANCHOR[1] * SPRITE_SIZE
        return cursor.y() - normal_hand_y < normal_ground_y

    def _begin_hang(self, now: float) -> None:
        """She grabbed the cursor: stop falling, become click-through, start the hang timer."""
        self._phase = Phase.HANG
        self._vy = 0.0
        self._vx = 0.0
        self._pending_reaction = None
        self._wall_bounced = False
        self._can_catch_cursor = False
        self._hang_started_at = now
        self._hang_ends_at = now + random.uniform(HANG_MIN_S, HANG_MAX_S)
        self._hang_bomb_thrown = False
        self._hang_bomb_count_remaining = 0
        self._hang_bomb_index = 0
        self._bombs_spawned_for_current_throw = False
        self._shake_trail.clear()                    # only movement made while hanging may shake her off
        self._set_input_transparent(True)
        self._play(HANGING_STATE, mirrored=self._hang_mirrored())
        log.debug("Hang: for %.1f s", self._hang_ends_at - now)

    def _tick_hang(self, cursor: QPoint, now: float, dt: float,
                   bounds: tuple[float, float, float, float]) -> None:
        """Hang phase, one tick: look for a shake / the end of the hang, else follow the cursor."""
        self._shake_trail.append((now, cursor.x(), cursor.y()))
        while now - self._shake_trail[0][0] > SHAKE_WINDOW_S:
            self._shake_trail.popleft()

        if now - self._hang_started_at >= SHAKE_GRACE_S and self._is_shaking():
            log.debug("Hang ended: shaken off")
            self._fall_after_jump(SHAKEN_REACTION)
            return
        if now >= self._hang_ends_at or not self._can_hang_from(cursor):
            log.debug("Hang ended: she let go (%s)",
                      "time is up" if now >= self._hang_ends_at else "cursor left / too low")
            self._fall_after_jump(RELEASE_REACTION)
            return

        # Check for serial bomb throw attack trigger after hanging for HANG_BOMB_DELAY_S
        if (self._bomb_attack_enabled
                and not self._hang_bomb_thrown
                and (now - self._hang_started_at >= HANG_BOMB_DELAY_S)):
            self._hang_bomb_thrown = True
            chance = self._bomb_chance_percent / 100.0
            if random.random() < chance and self._can_play(THROW_STATE):
                self._start_hang_bomb_throw(now)
                return

        min_x, max_x, min_y, ground_y = bounds
        hand_x, hand_y = self._hand_offset()
        goal_x = min(max(cursor.x() - hand_x, min_x), max_x)
        goal_y = min(max(cursor.y() - hand_y, min_y), ground_y)
        follow = 1.0 if HANG_FOLLOW_SMOOTH_S <= 0.0 else 1.0 - math.exp(-dt / HANG_FOLLOW_SMOOTH_S)
        self._x += (goal_x - self._x) * follow
        self._y += (goal_y - self._y) * follow

    def _start_hang_bomb_throw(self, now: float) -> None:
        """Start serial bomb throw sequence: detach from cursor and float mid-air."""
        self._leave_hang()
        self._phase = Phase.THROW
        self._post_throw_laugh = False
        self._say("throw", force=True)
        self._bomb_overlay.reset_state()
        pair = ["near", "beneath"]
        random.shuffle(pair)
        self._bomb_target_plan = ["random", "random"] + pair
        self._hang_bomb_count_remaining = BOMB_COUNT
        self._hang_bomb_index = 0
        self._throw_pause_ticks = THROW_FRAME_11_HOLD_TICKS
        self._bombs_spawned_for_current_throw = False
        self._throw_started_at = now
        self._play(THROW_STATE, loop=False, mirrored=self._throw_mirrored())
        self._anim_timer.setInterval(THROW_BASE_INTERVAL_MS)
        self._throw_start_y = self._y
        min_y = self._bounds()[2]
        self._throw_rise_px = max(0.0, min(THROW_RISE_PX, self._throw_start_y - min_y))
        log.debug("Detached from cursor: floating mid-air for serial bomb throw (rising %.1fpx)",
                  self._throw_rise_px)

    def _spawn_single_bomb(self, bomb_idx: int) -> None:
        """Spawn one of the serial bombs below the pet targeting the taskbar floor.

        Bomb 0 & 1: Random spread across the screen.
        Bomb 2: Cast towards near the cursor.
        Bomb 3 (last bomb): Cast directly beneath the cursor with 0.75s fuse.
        """
        origin_x = self._x + self.width() / 2.0
        origin_y = self._y + self.height() * 0.82
        area = self._work_area()
        ground_y = float(area.y() + area.height())
        screen = self.screen() or QApplication.primaryScreen()
        screen_rect = screen.geometry()
        facing_left = not self._throw_mirrored()

        # Calculate fast fall time from pet to ground
        dy = max(10.0, ground_y - origin_y)
        vy = random.uniform(BOMB_INITIAL_VY_MIN, BOMB_INITIAL_VY_MAX)
        g = BOMB_FIRST_FALL_GRAVITY_PX_S2
        t_fall = max(0.04, (-vy + math.sqrt(vy * vy + 2.0 * g * dy)) / g)

        cursor_x = float(QCursor.pos().x())
        min_target_x = float(screen_rect.left() + BOMB_SIZE / 2.0)
        max_target_x = float(screen_rect.right() - BOMB_SIZE / 2.0)

        target_mode = self._bomb_target_plan[bomb_idx % len(self._bomb_target_plan)]

        if target_mode == "beneath":
            # Aimed directly beneath the cursor (0.75s fuse on bounce)!
            target_ground_x = max(min_target_x, min(max_target_x, cursor_x))
            vx = (target_ground_x - origin_x) / t_fall
        elif target_mode == "near":
            # Aimed near the cursor!
            offset = random.choice([-1.0, 1.0]) * random.uniform(160.0, 240.0)
            target_ground_x = max(min_target_x, min(max_target_x, cursor_x + offset))
            vx = (target_ground_x - origin_x) / t_fall
        else:
            # Random spread!
            spread_vx = [-440.0, 440.0]
            base_vx = spread_vx[bomb_idx % len(spread_vx)]
            if not facing_left:
                base_vx = -base_vx
            vx = base_vx + random.uniform(-40.0, 40.0)

        self._bomb_overlay.spawn_single_bomb(origin_x, origin_y, vx, vy, ground_y, screen_rect, target_mode=target_mode)
        log.debug("Spawned serial bomb %d/%d (%s) below pet at (%.1f, %.1f) vx=%.1f vy=%.1f (fall ~%.2fs)",
                  bomb_idx + 1, BOMB_COUNT, target_mode, origin_x, origin_y, vx, vy, t_fall)

    def _is_shaking(self) -> bool:
        """The raw cursor path of the last SHAKE_WINDOW_S zig-zags on one axis but goes nowhere."""
        if len(self._shake_trail) < 2:
            return False
        xs = [x for _t, x, _y in self._shake_trail]
        ys = [y for _t, _x, y in self._shake_trail]
        if math.hypot(xs[-1] - xs[0], ys[-1] - ys[0]) >= SHAKE_MAX_NET:
            return False                             # she is being carried somewhere, not shaken
        reversals = max(count_reversals(xs, SHAKE_MIN_SWING), count_reversals(ys, SHAKE_MIN_SWING))
        return reversals >= SHAKE_REVERSALS

    # ----------------------------------------------------- jump: ending it
    def _begin_fall(self, gravity: float, reaction: str | None) -> None:
        """Common start of every fall (drop, let-go, shake-off, menu abort)."""
        self._leave_hang()                           # click-through off, shake history gone
        self._phase = Phase.FALL
        self._gravity = gravity
        self._vy = 0.0
        self._vx = 0.0
        self._pending_reaction = reaction
        self._can_catch_cursor = False
        self._last_tick = time.perf_counter()

    def _fall_after_jump(self, reaction: str | None) -> None:
        """A jump or hang ended in mid-air: fall with the airborne art, `reaction` on touchdown."""
        self._begin_fall(JUMP_GRAVITY_PX_S2, reaction)
        if self.state != AIRBORNE_STATE:             # coming from the hang
            self._play(AIRBORNE_STATE, mirrored=self._airborne_mirrored())

    def _touch_down(self) -> None:
        """She is back on the ground after a jump, a fall or a drop: play the pending reaction."""
        reaction, self._pending_reaction = self._pending_reaction, None
        self._vy = 0.0
        self._vx = 0.0
        self._can_catch_cursor = False
        if self._jump_active:
            self._jump_active = False
            cooldown = random.uniform(JUMP_COOLDOWN_MIN_S, JUMP_COOLDOWN_MAX_S)
            self._jump_ready_at = time.perf_counter() + cooldown
            log.debug("Touchdown: reaction %s, next jump possible in %.0f s", reaction, cooldown)
        if reaction is not None and not self._can_play(reaction):
            reaction = None
        self._start_pause(roll_special=False, forced=reaction)
        if reaction is None:
            self._say("land", force=True)

    def _leave_hang(self) -> None:
        """Undo what the hang set up: click-through off, shake history gone."""
        self._set_input_transparent(False)
        self._shake_trail.clear()
        self._hang_bomb_count_remaining = 0
        self._hang_bomb_index = 0
        self._throw_pause_ticks = 0
        self._throw_rise_px = 0.0
        self._bombs_spawned_for_current_throw = False

    def _set_input_transparent(self, enabled: bool) -> None:
        """Click-through for the whole window while she hangs, so clicks reach what is under the cursor."""
        if enabled == self._input_transparent:
            return
        self._input_transparent = enabled
        worked = set_window_input_transparent(self, enabled)
        if enabled and not worked and not self._warned_no_click_through:
            self._warned_no_click_through = True
            log.warning("Click-through while hanging is not available here - clicks will hit the pet")

    def _reset_jump_state(self) -> None:
        """Forget everything about a jump in progress. Used by every cancel path: drag, quit ..."""
        self._stop_overlay()
        self._leave_hang()
        self._anim_timer.setInterval(ANIM_INTERVAL_MS)
        self._pending_reaction = None
        self._vx = 0.0
        self._wall_bounced = False
        self._can_catch_cursor = False
        self._debug_jump_at = None
        self._hang_bomb_thrown = False
        self._hang_bomb_count_remaining = 0
        self._hang_bomb_index = 0
        self._throw_pause_ticks = 0
        self._throw_rise_px = 0.0
        self._bombs_spawned_for_current_throw = False
        self._post_throw_laugh = False
        self._dialogue_clicked = False
        self._in_angry_spam = False
        self._click_times.clear()

    # ------------------------------------------------------- jump: debug aid
    def _schedule_debug_jump(self) -> None:
        """Debug menu: aim at wherever the cursor is DEBUG_JUMP_DELAY_S from now."""
        self._debug_jump_at = time.perf_counter() + DEBUG_JUMP_DELAY_S
        log.info("Debug jump armed: it aims at the cursor in %.1f s - park the pointer high above her",
                 DEBUG_JUMP_DELAY_S)

    def _fire_debug_jump(self, cursor: QPoint) -> None:
        """Launch the armed debug jump: no trigger gates, no cooldown, no dice."""
        self._debug_jump_at = None
        if self._phase not in (Phase.WALK, Phase.PAUSE) or self._menu_open:
            log.info("Debug jump skipped: the pet is busy")
        elif not self._begin_jump(cursor):
            log.info("Debug jump skipped: the cursor is not above her hands - move it higher")

    # ------------------------------------------------------------------- mouse
    def mousePressEvent(self, event) -> None:
        if self._phase in (Phase.HIDE_OUTRO, Phase.EXIT_OUTRO):
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            if self._phase == Phase.HIDE_PEEK:
                self._on_peek_ears_clicked()
                event.accept()
                return
            if self._phase in (Phase.SUMMON_DIALOGUE, Phase.SUMMON_INTRO):
                if hasattr(self, "_dialogue_overlay") and self._dialogue_overlay.is_active():
                    self._dialogue_overlay.advance_or_dismiss()
                event.accept()
                return
            if hasattr(self, "_dialogue_overlay") and self._dialogue_overlay.is_active():
                if self._dialogue_overlay.is_skippable():
                    self._dialogue_overlay.advance_or_dismiss()
                    self._dialogue_clicked = True
                    self._press_global = event.globalPos()
                    self._grab_offset = event.globalPos() - self.pos()
                    event.accept()
                    return
            self._dialogue_clicked = False
            self._press_global = event.globalPos()
            self._grab_offset = event.globalPos() - self.pos()
            event.accept()
        else:
            super().mousePressEvent(event)   # right button -> contextMenuEvent follows

    def mouseMoveEvent(self, event) -> None:
        if self._phase in (Phase.HIDE_PEEK, Phase.HIDE_OUTRO, Phase.SUMMON_DIALOGUE, Phase.SUMMON_INTRO, Phase.EXIT_OUTRO):
            return
        if self._press_global is None or not (event.buttons() & Qt.LeftButton):
            return
        if not self._dragging:
            # Only treat it as a drag after moving a few pixels, so plain clicks stay clicks.
            moved = (event.globalPos() - self._press_global).manhattanLength()
            if moved < QApplication.startDragDistance():
                return
            self._dialogue_clicked = False
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
        if self._phase in (Phase.HIDE_PEEK, Phase.HIDE_OUTRO, Phase.SUMMON_DIALOGUE, Phase.SUMMON_INTRO, Phase.EXIT_OUTRO):
            self._press_global = None
            return
        self._press_global = None
        self._dialogue_clicked = False
        if self._dragging:
            self._end_drag()
        elif self._phase in (Phase.JUMP, Phase.HANG, Phase.FALL, Phase.THROW) or self._post_throw_laugh:
            # A plain click in mid-air or during post-throw victory laugh changes nothing: it must not
            # turn the pet into a "shocked" pause and so overwrite the victory laugh / landing reaction.
            return
        else:
            now = time.perf_counter()
            if self._in_angry_spam or self.state == "angry":
                # Currently mad or in active spam: keep her continuously mad while clicks keep coming!
                if (now - self._last_angry_click_time <= CLICK_ANGRY_WINDOW_S) or self.state == "angry":
                    self._keep_angry()
                    return
                else:
                    self._in_angry_spam = False

            # Direct mouse click overrides any background resume state
            self._interrupted_state = None
            self._click_times = [t for t in self._click_times if now - t <= CLICK_ANGRY_WINDOW_S]
            self._click_times.append(now)

            if len(self._click_times) >= CLICK_ANGRY_COUNT and self._can_play("angry"):
                self._in_angry_spam = True
                self._last_angry_click_time = now
                self._click_times.clear()
                self._start_pause(roll_special=False, forced="angry")
            else:
                self._start_pause(roll_special=False, forced="shocked")

    def mouseDoubleClickEvent(self, event) -> None:
        """Double left-click opens the chat input overlay to talk to Pink."""
        if self._phase in (Phase.HIDE_PEEK, Phase.HIDE_OUTRO, Phase.SUMMON_DIALOGUE, Phase.SUMMON_INTRO, Phase.EXIT_OUTRO):
            return
        if event.button() == Qt.LeftButton:
            self._open_chat_input()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _begin_drag(self) -> None:
        """The pet was picked up: stop the behaviour loop and play 'shocked' while held."""
        self._dragging = True
        self._dialogue_clicked = False
        self._phase = Phase.DRAG
        self._interrupted_state = None            # drag overrides any pending resume state
        self._brain_timer.stop()
        self._pause_elapsed = False
        self._reset_jump_state()                  # mid-jump / mid-hang grab: cancel everything
        if hasattr(self, "_dialogue_overlay"):
            self._dialogue_overlay.dismiss(clear_queue=True)
        if hasattr(self, "_chat_input"):
            self._chat_input.cancel()
        self._play("shocked", loop=True)          # loop it for as long as it is held
        self.setCursor(Qt.ClosedHandCursor)

    def _end_drag(self) -> None:
        """Drop the pet: it will fall back to the taskbar under gravity."""
        self._dragging = False
        self.setCursor(Qt.OpenHandCursor)
        reaction = None
        if (self._jump_enabled and DROP_REACTION
                and self._bounds()[3] - self._y >= DROP_REACTION_MIN_HEIGHT_PX):
            reaction = DROP_REACTION
        self._begin_fall(GRAVITY_PX_S2, reaction)

    def contextMenuEvent(self, event) -> None:
        """Right-click menu."""
        self._post_throw_laugh = False
        self._in_angry_spam = False
        self._click_times.clear()
        if self._phase in (Phase.HIDE_PEEK, Phase.HIDE_OUTRO, Phase.SUMMON_DIALOGUE, Phase.SUMMON_INTRO, Phase.EXIT_OUTRO):
            return
        if self._phase in (Phase.JUMP, Phase.HANG, Phase.THROW):
            # Opening the menu aborts a jump / hang / throw into a plain fall, with no reaction.
            self._fall_after_jump(None)
        menu = QMenu(self)
        talk_action = menu.addAction("Talk to Pink 💬")
        api_key_action = menu.addAction("Set Gemini API Key 🔑")
        menu.addSeparator()
        jump_action = None
        if DEBUG_JUMP_MENU and self._jump_enabled:
            jump_action = menu.addAction("Jump to cursor")
            menu.addSeparator()
        hide_action = menu.addAction("Hide 🐾")
        menu.addSeparator()
        exit_action = menu.addAction("Exit")
        self._menu_open = True                    # the pet stands still while the menu is open
        try:
            chosen = menu.exec_(event.globalPos())
        finally:
            self._menu_open = False
            self._resume_walk_after_menu()
        if chosen is exit_action:
            self._quit()
        elif chosen is hide_action:
            self._start_hide_sequence()
        elif chosen is talk_action:
            self._open_chat_input()
        elif chosen is api_key_action:
            self._prompt_api_key_dialog()
        elif jump_action is not None and chosen is jump_action:
            self._schedule_debug_jump()

    def _rest_while_menu_open(self) -> None:
        """The menu is open and she stands still, so show idle instead of a walking animation."""
        if self.state in MOVE_VELOCITY_PX_S:
            self._walk_before_menu = self.state
            self._play("idle")

    def _resume_walk_after_menu(self) -> None:
        """The menu is closed: bring the walk / run animation back - if she is still on that walk."""
        walk, self._walk_before_menu = self._walk_before_menu, None
        if self._phase in (Phase.HIDE_PEEK, Phase.HIDE_OUTRO, Phase.EXIT_OUTRO):
            return
        if walk is not None and self._phase is Phase.WALK and self.state == "idle":
            self._play(walk)

    # ------------------------------------------------------- window reactions
    def _check_foreground_window(self) -> None:
        """Poll foreground window to detect switches to maximized apps."""
        if (self._dragging or self._menu_open
                or self._phase in (Phase.JUMP, Phase.HANG, Phase.FALL, Phase.THROW,
                                   Phase.HIDE_PEEK, Phase.HIDE_OUTRO,
                                   Phase.SUMMON_DIALOGUE, Phase.SUMMON_INTRO,
                                   Phase.EXIT_OUTRO)
                or self._post_throw_laugh):
            return

        dll = _user32()
        if dll is None:
            return
        hwnd = dll.GetForegroundWindow()
        if not hwnd or hwnd == int(self.winId()):
            return

        if hwnd != self._last_foreground_hwnd:
            self._last_foreground_hwnd = hwnd
            prev_lum = self._last_luminance

            # Give DWM time to finish drawing the new window before sampling luminance
            QTimer.singleShot(WINDOW_SWITCH_SETTLE_MS,
                              lambda h=hwnd, pl=prev_lum: self._handle_window_switch(h, pl))

    def _handle_window_switch(self, target_hwnd: int, prev_lum: float) -> None:
        """Evaluate the newly focused window after it has composited."""
        if (self._dragging or self._menu_open
                or self._phase in (Phase.JUMP, Phase.HANG, Phase.FALL, Phase.THROW,
                                   Phase.HIDE_PEEK, Phase.HIDE_OUTRO,
                                   Phase.SUMMON_DIALOGUE, Phase.SUMMON_INTRO,
                                   Phase.EXIT_OUTRO)
                or self._post_throw_laugh):
            return
        dll = _user32()
        if dll is None:
            return
        # If user already moved to another window, skip
        if dll.GetForegroundWindow() != target_hwnd:
            return

        is_maximized = bool(dll.IsZoomed(target_hwnd))
        curr_lum = sample_screen_luminance()
        self._last_luminance = curr_lum

        if not is_maximized:
            return

        # Do not interrupt anger if clicks are currently spamming
        if self._in_angry_spam or (self.state == "angry" and self._repeat_count > 0):
            return

        # Flashbang check: switched from dark to dominant white/light
        if prev_lum <= DARK_LUMINANCE_THRESHOLD and curr_lum >= LIGHT_LUMINANCE_THRESHOLD:
            now = time.perf_counter()
            if now - self._last_switch_burnt_time < SWITCH_BURNT_COOLDOWN_S:
                log.info("Flashbang detected, but burnt is on cooldown (%.1fs remaining)",
                         SWITCH_BURNT_COOLDOWN_S - (now - self._last_switch_burnt_time))
                return
            self._last_switch_burnt_time = now
            log.info("Flashbang! Switched from dark (%.1f) to bright maximized app (%.1f) -> burnt",
                     prev_lum, curr_lum)
            self._interrupt_with_reaction("burnt", dialogue_category="burnt_switch")
        else:
            now = time.perf_counter()
            if now - self._last_switch_shock_time < SWITCH_SHOCK_COOLDOWN_S:
                log.info("Switched to maximized app, but shocked is on cooldown (%.1fs remaining)",
                         SWITCH_SHOCK_COOLDOWN_S - (now - self._last_switch_shock_time))
                return
            self._last_switch_shock_time = now
            log.info("Switched to maximized app -> shocked")
            self._interrupt_with_reaction("shocked")

    def _interrupt_with_reaction(self, reaction: str, dialogue_category: str | None = None) -> None:
        """Temporarily freeze current activity, play a reaction (shocked/burnt), then resume."""
        if self._phase in (Phase.HIDE_PEEK, Phase.HIDE_OUTRO,
                           Phase.SUMMON_DIALOGUE, Phase.SUMMON_INTRO,
                           Phase.EXIT_OUTRO):
            return
        if self._interrupted_state is None:
            rem_ms = max(500, self._brain_timer.remainingTime()) if self._brain_timer.isActive() else 2500
            self._interrupted_state = {
                "phase": self._phase,
                "state": self.state,
                "rem_ms": rem_ms,
                "loop": self._loop,
            }
        self._brain_timer.stop()
        self._pause_elapsed = False
        self._play(reaction)
        self._say(dialogue_category or reaction, force=True)

    # -------------------------------------------------------- system tray icon
    def _init_tray_icon(self) -> None:
        """Create an icon in the Windows taskbar notification area / hidden icons menu."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self._tray_icon = QSystemTrayIcon(self)
        if ICON_PATH.exists():
            self._tray_icon.setIcon(QIcon(str(ICON_PATH)))
        else:
            self._tray_icon.setIcon(self.windowIcon())
        self._tray_icon.setToolTip("Yellow's Pixel Buddies")

        tray_menu = QMenu()
        title_action = tray_menu.addAction("Yellow's Pixel Buddies 🐾")
        title_action.setEnabled(False)
        tray_menu.addSeparator()

        self._startup_action = tray_menu.addAction("Start with Windows")
        self._startup_action.setCheckable(True)
        self._startup_action.setChecked(is_run_at_startup_enabled())
        self._startup_action.toggled.connect(self._toggle_run_at_startup)

        tray_menu.addSeparator()

        self._bring_action = tray_menu.addAction("Call Pink 🐾" if self._phase in (Phase.HIDE_PEEK, Phase.SUMMON_DIALOGUE) else "Bring to Taskbar")
        self._bring_action.triggered.connect(self._reset_to_taskbar)

        self._talk_tray_action = tray_menu.addAction("Talk to Pink 💬")
        self._talk_tray_action.triggered.connect(self._open_chat_input)

        self._key_tray_action = tray_menu.addAction("Set Gemini API Key 🔑")
        self._key_tray_action.triggered.connect(self._prompt_api_key_dialog)

        memory_menu = tray_menu.addMenu("Memory Storage 🧠")
        open_mem_action = memory_menu.addAction("Open Memory Folder 📂")
        open_mem_action.triggered.connect(self._open_memory_folder)
        reset_mem_action = memory_menu.addAction("Clear Current Session 🧹")
        reset_mem_action.triggered.connect(self._reset_session_memory)

        self._hide_tray_action = tray_menu.addAction("Hide Pink 🐾")
        self._hide_tray_action.triggered.connect(self._start_hide_sequence)

        self._bomb_action = tray_menu.addAction("Bomb Attack Mode")
        self._bomb_action.setCheckable(True)
        self._bomb_action.setChecked(self._bomb_attack_enabled)
        self._bomb_action.toggled.connect(self._toggle_bomb_attack)

        self._bomb_chance_action = QWidgetAction(tray_menu)
        self._bomb_chance_widget = BombChanceWidget(
            initial_pct=self._bomb_chance_percent,
            default_pct=HANG_BOMB_DEFAULT_CHANCE_PERCENT,
            on_change=self._set_bomb_chance_percent,
        )
        self._bomb_chance_widget.setEnabled(self._bomb_attack_enabled)
        self._bomb_chance_action.setDefaultWidget(self._bomb_chance_widget)
        tray_menu.addAction(self._bomb_chance_action)

        tray_menu.addSeparator()

        self._dialogue_action = tray_menu.addAction("Dialogue Bubbles")
        self._dialogue_action.setCheckable(True)
        self._dialogue_action.setChecked(self._dialogue_enabled)
        self._dialogue_action.toggled.connect(self._toggle_dialogue)

        tray_menu.addSeparator()
        exit_action = tray_menu.addAction("Exit")
        exit_action.triggered.connect(self._quit)

        tray_menu.aboutToShow.connect(self._sync_startup_action_state)

        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _sync_startup_action_state(self) -> None:
        """Sync checkmark and controls with actual state right before displaying the menu."""
        if self._bring_action is not None:
            if self._phase in (Phase.HIDE_PEEK, Phase.SUMMON_DIALOGUE):
                self._bring_action.setText("Call Pink 🐾")
            else:
                self._bring_action.setText("Bring to Taskbar")
        if self._hide_tray_action is not None:
            self._hide_tray_action.setVisible(self._phase not in (Phase.HIDE_PEEK, Phase.SUMMON_DIALOGUE, Phase.SUMMON_INTRO, Phase.HIDE_OUTRO, Phase.EXIT_OUTRO))
        if hasattr(self, "_talk_tray_action") and self._talk_tray_action is not None:
            self._talk_tray_action.setEnabled(self._phase not in (Phase.HIDE_PEEK, Phase.SUMMON_DIALOGUE, Phase.SUMMON_INTRO, Phase.HIDE_OUTRO, Phase.EXIT_OUTRO))
        if self._startup_action is not None:
            self._startup_action.blockSignals(True)
            self._startup_action.setChecked(is_run_at_startup_enabled())
            self._startup_action.blockSignals(False)
        if self._bomb_action is not None:
            self._bomb_action.blockSignals(True)
            self._bomb_action.setChecked(self._bomb_attack_enabled)
            self._bomb_action.blockSignals(False)
        if self._bomb_chance_widget is not None:
            self._bomb_chance_widget.set_value(self._bomb_chance_percent)
            self._bomb_chance_widget.setEnabled(self._bomb_attack_enabled)
        if self._dialogue_action is not None:
            self._dialogue_action.blockSignals(True)
            self._dialogue_action.setChecked(self._dialogue_enabled)
            self._dialogue_action.blockSignals(False)

    def _toggle_dialogue(self, checked: bool) -> None:
        """Enable or disable speech bubble popups."""
        self._dialogue_enabled = checked
        if not checked and hasattr(self, "_dialogue_overlay"):
            self._dialogue_overlay.dismiss()
        if self._dialogue_action is not None:
            self._dialogue_action.blockSignals(True)
            self._dialogue_action.setChecked(checked)
            self._dialogue_action.blockSignals(False)
        log.info("Dialogue bubbles: %s", "ENABLED" if checked else "DISABLED")

    def _toggle_bomb_attack(self, checked: bool) -> None:
        """Enable or disable the bomb attack mode."""
        self._bomb_attack_enabled = checked
        if self._bomb_action is not None:
            self._bomb_action.blockSignals(True)
            self._bomb_action.setChecked(checked)
            self._bomb_action.blockSignals(False)
        if self._bomb_chance_widget is not None:
            self._bomb_chance_widget.setEnabled(checked)
        log.info("Bomb attack mode: %s", "ENABLED" if checked else "DISABLED")

    def _set_bomb_chance_percent(self, pct: int) -> None:
        """Update bomb attack chance percentage (0-100%)."""
        self._bomb_chance_percent = max(0, min(100, int(pct)))
        if self._bomb_chance_widget is not None:
            self._bomb_chance_widget.set_value(self._bomb_chance_percent)
        log.info("Bomb attack chance set to %d%%", self._bomb_chance_percent)

    def _toggle_bomb_force_100(self, checked: bool) -> None:
        """Backward-compatible helper: force 100% or reset to default chance."""
        self._set_bomb_chance_percent(100 if checked else HANG_BOMB_DEFAULT_CHANCE_PERCENT)

    @property
    def _bomb_force_100(self) -> bool:
        return self._bomb_chance_percent >= 100

    @_bomb_force_100.setter
    def _bomb_force_100(self, checked: bool) -> None:
        self._toggle_bomb_force_100(checked)

    def _toggle_run_at_startup(self, checked: bool) -> None:
        """Callback when user toggles 'Start with Windows'."""
        ok = set_run_at_startup(checked)
        if not ok and self._startup_action is not None:
            self._startup_action.blockSignals(True)
            self._startup_action.setChecked(not checked)
            self._startup_action.blockSignals(False)

    def _reset_to_taskbar(self) -> None:
        """Emergency reset or manual summon: place the pet safely back on the primary taskbar."""
        if self._phase in (Phase.HIDE_PEEK, Phase.SUMMON_DIALOGUE):
            self._start_summon_intro()
            return
        if self._phase in (Phase.SUMMON_INTRO, Phase.HIDE_OUTRO, Phase.EXIT_OUTRO):
            return
        self._reset_jump_state()
        min_x, max_x, _min_y, ground_y = self._bounds()
        self._x = float((min_x + max_x) // 2)
        self._y = float(ground_y)
        self._sync_window_position()
        self.show()
        self.raise_()
        self._start_pause(roll_special=False)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Left-click or double-click tray icon to call Pink if she is hiding."""
        if self._phase in (Phase.HIDE_OUTRO, Phase.EXIT_OUTRO):
            return
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self._phase == Phase.HIDE_PEEK:
                self._on_peek_ears_clicked()
            elif self._phase == Phase.SUMMON_DIALOGUE:
                self._start_summon_intro()

    def _quit(self) -> None:
        """Stop everything and leave the application (or run offscreen first)."""
        if self._phase is Phase.EXIT_OUTRO:
            return
        if self._phase in (Phase.HIDE_PEEK, Phase.HIDE_OUTRO):
            self._do_real_quit()
            return
        self._start_exit_outro()

    def _do_real_quit(self) -> None:
        """Stop everything and terminate the application."""
        if hasattr(self, "_tray_icon") and self._tray_icon is not None:
            self._tray_icon.hide()
        timers = [self._anim_timer, self._move_timer, self._brain_timer, self._overlay_timer]
        if hasattr(self, "_window_timer"):
            timers.append(self._window_timer)
        for timer in timers:
            timer.stop()
        self._stop_overlay()
        if hasattr(self, "_media_watcher") and self._media_watcher is not None:
            self._media_watcher.stop()
            self._media_watcher.wait(1000)
        if hasattr(self, "_vfx_overlay"):
            self._vfx_overlay.close()
        if hasattr(self, "_bomb_overlay"):
            self._bomb_overlay.close()
        if hasattr(self, "_dialogue_overlay"):
            self._dialogue_overlay.dismiss(clear_queue=True)
            self._dialogue_overlay.close()
        if hasattr(self, "_chat_input"):
            self._chat_input.close()
        if hasattr(self, "_gemini_thread") and self._gemini_thread is not None and self._gemini_thread.isRunning():
            self._gemini_thread.terminate()
            self._gemini_thread.wait(500)
        self._reset_jump_state()                  # click-through off, pending reaction / histories cleared
        self.hide()
        QApplication.quit()

    def closeEvent(self, event) -> None:
        if self._phase is Phase.EXIT_OUTRO:
            event.accept()
            self._do_real_quit()
            return
        if self._phase in (Phase.HIDE_PEEK, Phase.HIDE_OUTRO):
            self._do_real_quit()
            event.accept()
            return
        event.ignore()
        self._quit()

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
            if getattr(self, "_is_ghost_talking", False):
                self._paint_ghost_talking(painter)
            elif self._phase == Phase.HIDE_PEEK:
                painter.save()
                painter.setClipRect(0, 0, self.width(), EAR_PEEK_HEIGHT_PX)
                painter.drawPixmap(0, 0, self._pixmap)
                painter.restore()
            elif self._phase == Phase.HIDE_OUTRO and getattr(self, "_hide_subphase", "") in ("ghost_rise_from_below", "ghost_sink"):
                area = QApplication.primaryScreen().availableGeometry()
                vis_h = max(0, min(self.height(), round(area.y() + area.height() - self._y)))
                painter.save()
                painter.setClipRect(0, 0, self.width(), vis_h)
                painter.drawPixmap(0, 0, self._pixmap)
                painter.restore()
            else:
                painter.drawPixmap(0, 0, self._pixmap)   # pixmap carries its own device ratio
        if DEBUG_DRAW_HAND_ANCHOR and self.state == HANGING_STATE:
            self._paint_hand_crosshair(painter)
        painter.end()

    def _get_ghost_aura_pixmap(self, src: QPixmap) -> QPixmap:
        """Return a cached tinted spectral cyan silhouette of the current sprite frame."""
        if not hasattr(self, "_ghost_aura_cache"):
            self._ghost_aura_cache = {}
        cache_key = id(src)
        if cache_key in self._ghost_aura_cache:
            return self._ghost_aura_cache[cache_key]
        img = src.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(img.rect(), QColor(80, 230, 255, 210))  # Spectral cyan ghost glow
        p.end()
        aura = QPixmap.fromImage(img)
        aura.setDevicePixelRatio(src.devicePixelRatio() if src.devicePixelRatio() > 0 else 1.0)
        self._ghost_aura_cache[cache_key] = aura
        return aura

    def _paint_ghost_talking(self, painter: QPainter) -> None:
        """Render the angry sprite with a pulsating spectral cyan aura, ghost flicker, and floating embers."""
        t = time.perf_counter()
        pulse = (math.sin(t * 10.0) + 1.0) * 0.5   # 0.0 to 1.0 pulsating cycle
        aura_spread = 2.0 + 1.8 * pulse
        aura_opacity = 0.35 + 0.35 * pulse

        aura_pix = self._get_ghost_aura_pixmap(self._pixmap)

        # 1. Pulsating 4-direction spectral cyan aura glow behind her
        painter.save()
        painter.setOpacity(aura_opacity)
        painter.drawPixmap(QPointF(-aura_spread, 0), aura_pix)
        painter.drawPixmap(QPointF(aura_spread, 0), aura_pix)
        painter.drawPixmap(QPointF(0, -aura_spread), aura_pix)
        painter.drawPixmap(QPointF(0, aura_spread), aura_pix)
        painter.restore()

        # 2. Ghostly jitter & opacity flicker on the main angry sprite
        jitter_x = math.sin(t * 36.0) * 0.9
        jitter_y = math.cos(t * 28.0) * 0.7
        flicker_opacity = 0.88 + 0.12 * math.sin(t * 24.0)

        painter.save()
        painter.setOpacity(flicker_opacity)
        painter.drawPixmap(QPointF(jitter_x, jitter_y), self._pixmap)
        painter.restore()

        # 3. Rising ethereal ectoplasm spark particles
        painter.save()
        w = float(self.width())
        h = float(self.height())
        for i in range(5):
            p_t = (t * 1.4 + i * 0.2) % 1.0
            p_x = (w * 0.2) + ((i * 31) % int(w * 0.6)) + math.sin(t * 7.0 + i) * 5.0
            p_y = h * 0.85 - p_t * (h * 0.65)
            p_alpha = int(220 * math.sin(p_t * math.pi))
            p_size = 2.0 + (i % 2)
            painter.fillRect(QRectF(p_x, p_y, p_size, p_size), QColor(100, 240, 255, p_alpha))
        painter.restore()

    def _paint_hand_crosshair(self, painter: QPainter) -> None:
        """Debug aid: mark HAND_ANCHOR (where the hands must be in the hanging art) with a crosshair."""
        hand_x, hand_y = self._hand_offset()
        reach = DEBUG_CROSSHAIR_PX
        for color, width in ((QColor(0, 0, 0), 3), (QColor(255, 0, 255), 1)):
            painter.setPen(QPen(color, width))
            painter.drawLine(QPointF(hand_x - reach, hand_y), QPointF(hand_x + reach, hand_y))
            painter.drawLine(QPointF(hand_x, hand_y - reach), QPointF(hand_x, hand_y + reach))


DesktopPet = YellowsPixelBuddies  # backward compatibility alias


# =============================================================================
#  5. ENTRY POINT
# =============================================================================

def main() -> int:
    level = logging.DEBUG if (DEBUG_JUMP_MENU or DEBUG_DRAW_HAND_ANCHOR) else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s")
    signal.signal(signal.SIGINT, signal.SIG_DFL)   # Ctrl+C in the console quits immediately

    check_jump_config()                            # typos in "left" / "right" fail here, readably
    configure_high_dpi()                           # must happen BEFORE QApplication()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)           # we quit explicitly from the menu
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    font_family = "Determination"
    if DETERMINATION_FONT_PATH.exists():
        fid = QFontDatabase.addApplicationFont(str(DETERMINATION_FONT_PATH))
        if fid >= 0:
            families = QFontDatabase.applicationFontFamilies(fid)
            if families:
                font_family = families[0]
                log.info("Loaded font '%s' from %s", font_family, DETERMINATION_FONT_PATH)
            else:
                log.warning("Could not determine font family from %s", DETERMINATION_FONT_PATH)
        else:
            log.warning("Failed to load application font from %s", DETERMINATION_FONT_PATH)
    else:
        log.info("Determination font not found at %s - falling back to default font", DETERMINATION_FONT_PATH)

    sprites_dir = SPRITES_DIR
    bank = SpriteBank(sprites_dir, app.primaryScreen().devicePixelRatio())
    buddy = YellowsPixelBuddies(bank, font_family=font_family)
    buddy.start()

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())