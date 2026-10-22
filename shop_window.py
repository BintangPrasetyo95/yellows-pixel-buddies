"""Pink's Dark World Sanctuary (formerly Shop Window) for Yellow's Pixel Buddies.

Major Overhaul:
1. Character / Wardrobe: Locked because only Pink exists in this world ("There is only one of me, minion!").
2. Tasks & Alarms (2 Sub-Tabs):
   - Sub-tab 1: Tasks (Reminders board, proof-of-work screen/session verification, cash in for P$ 1 - P$ 3, scrollable).
   - Sub-tab 2: Alarms (5m, 15m, 25m Pomodoro, custom timers, active alarms list with remaining time, cancel controls, scrollable).
3. Config & Settings (2 Sub-Tabs):
   - Sub-tab 1: Edit Facts (Nickname editor, "+ Add New Fact Note", scrollable list of all permanent notes, full text card display).
   - Sub-tab 2: Toggles (Dialogue Bubbles, AI Song Commentary, Bomb Attack, Jump to Cursor).
4. Dialogue & Storyline:
   - Defeat toggle removed! Greetings & exits randomly organized from Toby Fox canon shop dialogue.
   - Serious shopkeeper dialogue ("Ask Her Something", canon topics, cat bite secret).
5. Input Bar:
   - Floating retro input container with QLineEdit, yellow retro "SEND" button, and red retro "X" cancel button.
6. Universal Scrolling & Seamless Mouse Interaction:
   - Mouse wheel scrolling on all scrollable menus.
   - Visual scroll indicators (▲ and ▼).
   - Instant single-click activation on all menus (including Talk topics, sub-tabs, and buttons).
   - Zero-lag: Pre-composited backgrounds, zero allocations per paintEvent, full mouse hover tracking.
"""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
import random
import re
import sys
import time
from enum import Enum, auto
from typing import TYPE_CHECKING, Callable, Any

from PyQt5.QtCore import (
    Qt,
    QTimer,
    QRect,
    QPoint,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QColor,
    QFont,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPixmap,
    QWheelEvent,
)
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QLineEdit,
    QPushButton,
)

if TYPE_CHECKING:
    from yellows_pixel_buddies import MemoryManager, YellowsPixelBuddies

log = logging.getLogger("yellows_pixel_buddies.shop")

# --- Directory Paths -----------------------------------------------------------
_BASE_DIR = Path(__file__).resolve().parent
SPRITES_DIR = _BASE_DIR / "sprites"
SHOP_DIR = SPRITES_DIR / "shop"
SHOP_SCENE_DIR = SHOP_DIR / "shop_scene"
SHOP_HUD_DIR = SHOP_DIR / "shop_hud"
FONTS_DIR = _BASE_DIR / "fonts" / "determination"
DETERMINATION_FONT_PATH = FONTS_DIR / "determination.ttf"
WALLET_PATH = _BASE_DIR / "memory" / "wallet.json"
FACTS_PATH = _BASE_DIR / "memory" / "facts.json"

# Native canvas dimensions
CANVAS_W = 640
CANVAS_H = 460
SCENE_NATIVE_W = 320
SCENE_NATIVE_H = 120
SCENE_RENDER_H = 240

# Timing configuration
SCENE_FRAME_INTERVAL_MS = 250
TYPEWRITER_INTERVAL_MS = 28


class ShopState(Enum):
    ROOT = auto()
    CHARACTER = auto()        # Replaces BUY (Locked: only Pink exists)
    TASKS = auto()            # Tasks & Alarms (2 sub-tabs: Tasks, Alarms)
    TASK_CONFIRM = auto()     # Stage 1 confirmation
    TASK_SECOND_CONFIRM = auto() # Stage 2 suspicion confirmation
    TALK_MENU = auto()        # Serious topics (8 items: 7 canon + Back)
    TALK_DIALOGUE = auto()    # Serious typewriter dialogue
    SETTINGS_MENU = auto()    # Config & Settings (2 tabs: Edit Facts, Toggles)
    EXITING = auto()


class PinkWallet:
    """Manages Pink Dollars (P$) and unlocked forms persisted in memory/wallet.json."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self.pink_dollars: int = 15
        self.unlocked_forms: list[str] = ["doll"]
        self.active_form: str = "doll"
        self.topic_counts: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                old_val = data.get("pink_dollars", data.get("dark_dollars", 15))
                self.pink_dollars = max(0, int(old_val))
                self.unlocked_forms = list(data.get("unlocked_forms", ["doll"]))
                self.active_form = str(data.get("active_form", "doll"))
                self.topic_counts = dict(data.get("topic_counts", {}))
                return
            except Exception as e:
                log.warning("Error reading wallet %s: %s", self._path, e)
        self.pink_dollars = 15
        self.unlocked_forms = ["doll"]
        self.active_form = "doll"
        self.topic_counts = {}
        self.save()

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "pink_dollars": self.pink_dollars,
                "unlocked_forms": self.unlocked_forms,
                "active_form": self.active_form,
                "topic_counts": self.topic_counts,
                "updated_at": time.time(),
            }
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning("Error saving wallet %s: %s", self._path, e)

    def add(self, amount: int) -> int:
        self.pink_dollars = max(0, self.pink_dollars + amount)
        self.save()
        return self.pink_dollars

    def spend(self, amount: int) -> bool:
        if self.pink_dollars >= amount:
            self.pink_dollars -= amount
            self.save()
            return True
        return False


# --- Character Forms (Only Pink exists; other forms locked) ---------------------
CHARACTER_FORMS = [
    {
        "id": "doll",
        "name": "Classic Doll (Pink)",
        "cost": 0,
        "anim": "idle",
        "desc": "The quintessential cotton Mew Mew doll body. The ONE and ONLY character in this world!",
        "locked": False,
    },
    {
        "id": "ghost",
        "name": "Spectral Ghost",
        "cost": 0,
        "anim": "angry",
        "desc": "Locked! There is only one character here, darling! You can't replace me!",
        "locked": True,
    },
    {
        "id": "burnt",
        "name": "Burnt Survivor",
        "cost": 0,
        "anim": "burnt",
        "desc": "Locked! Only Pink exists in this sanctuary. No character swaps allowed!",
        "locked": True,
    },
    {
        "id": "overjoyed",
        "name": "Cyber Joy",
        "cost": 0,
        "anim": "overjoyed",
        "desc": "Locked! One and only. You cannot switch characters, minion!",
        "locked": True,
    },
]

# --- Canon Deltarune Shop Dialogues (Organized Pools) --------------------------
CANON_GREETINGS = [
    "* The sunset...\n* It's breathtaking, isn't it?",
    "* The sunset... will it ever be this beautiful again?",
    "* Welcome back to the sanctuary.\n* Outside, the sunset is warm and golden.",
    "* Looking at the sunset... it makes you think, doesn't it?",
    "* The colors here... they shine from the back of your eyes.\n* Hee hee...",
]

CANON_EXITS = [
    "* That's right, go outside.\n* It's beautiful.",
    "* Treasure this world, won't you?",
    "* See you again soon, darling.\n* Don't stare into the sun too long.",
]

CANON_SELL_LINES = [
    "* Leave it all behind.",
    "* You're gonna give me stuff?",
    "* I could always use a knife.",
    "* A ribbon might be nice.",
]

CANON_SELL_EMPTY = "* You have nothing. Feels nice?"
CANON_SELL_SUCCESS = "* Guess it's MINE now."
CANON_SELL_REFUSE = "* Don't have second thoughts."
CANON_SELL_UNSELLABLE = "* L... like I would want that!"
CANON_SELL_SUSPICIOUS = "* Huh?"

CANON_BUY_ENTER = "* Right... this is a store."
CANON_BUY_PURCHASE = "* Enjoy. Enjoy! ENJOY!!"
CANON_BUY_BROKE = "* Ever heard of dollars?"
CANON_BUY_REFUSE = "* Save your dollars."
CANON_BUY_LOCKED = "* Locked! There is only one character here, darling!\n* Only Pink exists in this world, mew!"
CANON_TALK_ENTER = "* I guess... we could talk."

TALK_TOPICS = [
    ("What is this place?", "place"),
    ("What's your name?", "name"),
    ("Human ears?", "ears"),
    ("Other people?", "people"),
    ("Graduating", "graduating"),
    ("The Cat Bite", "egg"),
    ("Ask Something...", "ai_ask"),
    ("Back", "back"),
]


def evaluate_task_value(text: str) -> int:
    """Pink evaluates a task's worth between P$ 1 and P$ 3 based on complexity."""
    lower = text.lower()
    heavy_words = {
        "code", "project", "exam", "slides", "finals", "build", "deploy",
        "study", "calendar", "refactor", "feature", "write", "model",
        "database", "api", "shop", "algorithm", "report"
    }
    words = re.findall(r"\w+", lower)
    if any(w in lower for w in heavy_words) or len(words) >= 8:
        return 3
    elif len(words) >= 4:
        return 2
    else:
        return 1


class DeltaruneShopWindow(QWidget):
    """Pink's Dark World Sanctuary & Companion Command Center."""

    closed = pyqtSignal()

    def __init__(
        self,
        pet_ref: YellowsPixelBuddies | None = None,
        memory: MemoryManager | None = None,
        font_family: str = "Determination",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setWindowTitle("Pink's Dark World Sanctuary")

        self._pet = pet_ref
        self._memory = memory
        self._font_family = font_family
        self._wallet = PinkWallet(WALLET_PATH)

        # Scale factor & Geometry
        self._scale = 1.0
        self._calculate_target_geometry()

        # Typography
        self._font_title = QFont(self._font_family, 13, QFont.Bold)
        self._font_body = QFont(self._font_family, 12)
        self._font_small = QFont(self._font_family, 11)

        # Pre-composited backgrounds & soul heart
        self._soul_heart: QPixmap | None = self._create_soul_heart()
        self._bg_cache: dict[str, list[QPixmap]] = {"root": [], "buy": [], "talk": []}
        self._load_and_precomposite_assets()
        self._scene_frame_idx: int = 0

        # State machine
        self.state: ShopState = ShopState.ROOT
        self._selected_index: int = 0

        # Sub-tab indexing:
        # TASKS state: 0 = Tasks (Chore Board), 1 = Alarms (Focus Timers & Alarms)
        self._tasks_subtab: int = 0
        # SETTINGS_MENU state: 0 = Edit Facts, 1 = Toggles
        self._config_tab: int = 0

        # Scroll offsets
        self._tasks_scroll_offset: int = 0
        self._alarms_scroll_offset: int = 0
        self._notes_scroll_offset: int = 0

        # Random organized greeting & exit history
        self._last_greeting_idx: int = -1
        self._last_exit_idx: int = -1

        # Task selling & verification state
        self._pending_sell_reminder: str | None = None
        self._pending_sell_value: int = 1
        self._sell_has_evidence: bool = False
        self._sell_saw_on_screen: bool = False
        self._sell_evidence_kw: str = ""

        # Serious Talk Dialogue Queue
        self._dialogue_queue: list[str] = []
        self._dialogue_queue_idx: int = 0
        self._visit_graduating_count: int = 0

        # Focus Timer / Alarm State
        self._timer_seconds_remaining: int = 0
        self._timer_total_seconds: int = 0
        self._timer_label: str = ""
        self._timer_active: bool = False
        self._focus_timer = QTimer(self)
        self._focus_timer.setInterval(1000)
        self._focus_timer.timeout.connect(self._on_focus_timer_tick)

        # Typewriter dialogue
        self._dialogue_text: str = ""
        self._dialogue_char_idx: int = 0
        self._typewriter_timer = QTimer(self)
        self._typewriter_timer.setInterval(TYPEWRITER_INTERVAL_MS)
        self._typewriter_timer.timeout.connect(self._on_typewriter_tick)

        # Scene animation timer
        self._scene_timer = QTimer(self)
        self._scene_timer.setInterval(SCENE_FRAME_INTERVAL_MS)
        self._scene_timer.timeout.connect(self._on_scene_tick)

        # Dragging state
        self._drag_active: bool = False
        self._drag_start_pos: QPoint = QPoint()

        # Dedicated Input Container with SEND and X buttons
        self._input_container = QWidget(self)
        self._input_container.setStyleSheet(
            "QWidget { background-color: #0c0c14; border: 2px solid #ffffff; }"
        )
        self._input_container.hide()

        self._ai_input = QLineEdit(self._input_container)
        self._ai_input.setStyleSheet(
            f"QLineEdit {{ background: transparent; color: #ffffff; font-family: '{self._font_family}', monospace; font-size: 13px; border: none; padding: 2px 6px; }}"
        )
        self._ai_input.returnPressed.connect(self._on_input_submitted)

        self._input_send_btn = QPushButton("SEND", self._input_container)
        self._input_send_btn.setCursor(Qt.PointingHandCursor)
        self._input_send_btn.setStyleSheet(
            f"QPushButton {{ background-color: #1a1a2e; color: #ffff00; font-family: '{self._font_family}', monospace; font-size: 11px; font-weight: bold; border: 1px solid #ffff00; padding: 2px 8px; }} QPushButton:hover {{ background-color: #ffff00; color: #000000; }}"
        )
        self._input_send_btn.clicked.connect(self._on_input_submitted)

        self._input_cancel_btn = QPushButton("X", self._input_container)
        self._input_cancel_btn.setCursor(Qt.PointingHandCursor)
        self._input_cancel_btn.setStyleSheet(
            f"QPushButton {{ background-color: #1a1a2e; color: #ff6060; font-family: '{self._font_family}', monospace; font-size: 11px; font-weight: bold; border: 1px solid #ff6060; padding: 2px 6px; }} QPushButton:hover {{ background-color: #ff6060; color: #ffffff; }}"
        )
        self._input_cancel_btn.clicked.connect(self._on_input_cancelled)

        self._input_mode: str = ""  # "fact_name", "fact_note", "custom_timer", "ai_ask"

        # Mouse tracking & focus
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

    # --- Sizing & Assets -------------------------------------------------------

    def _calculate_target_geometry(self) -> None:
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        target_area = avail.width() * avail.height() * 0.25
        ideal_scale = math.sqrt(target_area / (CANVAS_W * CANVAS_H))

        if ideal_scale >= 1.4:
            self._scale = 1.4
        elif ideal_scale >= 1.25:
            self._scale = 1.3
        elif ideal_scale >= 1.1:
            self._scale = 1.2
        else:
            self._scale = 1.0

        w = round(CANVAS_W * self._scale)
        h = round(CANVAS_H * self._scale)
        x = avail.x() + avail.width() - w - 40
        y = avail.y() + avail.height() - h - 60
        self.setGeometry(x, y, w, h)
        self.setFixedSize(w, h)

    def _create_soul_heart(self) -> QPixmap:
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
        h, w = len(grid), len(grid[0])
        img = QImage(w * 2, h * 2, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        red = QColor(255, 0, 64, 255).rgba()
        for y, row in enumerate(grid):
            for x, c in enumerate(row):
                if c == "1":
                    for dy in range(2):
                        for dx in range(2):
                            img.setPixel(x * 2 + dx, y * 2 + dy, red)
        return QPixmap.fromImage(img)

    def _load_and_precomposite_assets(self) -> None:
        scenes: list[QPixmap] = []
        for i in range(1, 6):
            p = SHOP_SCENE_DIR / f"{i}.png"
            if p.exists():
                img = QImage(str(p))
                if not img.isNull():
                    scaled = img.scaled(640, 240, Qt.IgnoreAspectRatio, Qt.FastTransformation)
                    scenes.append(QPixmap.fromImage(scaled))
        if not scenes:
            blank = QPixmap(640, 240)
            blank.fill(QColor(40, 36, 36))
            scenes.append(blank)

        huds: dict[str, QPixmap] = {}
        for key, fname in [("root", "shop.png"), ("buy", "shop_buy.png"), ("talk", "shop_talk.png")]:
            p = SHOP_HUD_DIR / fname
            huds[key] = QPixmap(str(p)) if p.exists() else QPixmap(CANVAS_W, CANVAS_H)

        self._bg_cache = {"root": [], "buy": [], "talk": []}
        for key in ("root", "buy", "talk"):
            hud = huds[key]
            for scene in scenes:
                composite = QPixmap(CANVAS_W, CANVAS_H)
                composite.fill(QColor(0, 0, 0, 255))
                p = QPainter(composite)
                p.drawPixmap(0, 0, scene)
                p.drawPixmap(0, 0, hud)
                p.end()
                self._bg_cache[key].append(composite)

    # --- Lifecycle & Canon Dialogues -------------------------------------------

    def _get_root_greeting(self) -> str:
        choices = [g for i, g in enumerate(CANON_GREETINGS) if i != self._last_greeting_idx]
        chosen = random.choice(choices if choices else CANON_GREETINGS)
        self._last_greeting_idx = CANON_GREETINGS.index(chosen)
        return chosen

    def _get_exit_line(self) -> str:
        choices = [e for i, e in enumerate(CANON_EXITS) if i != self._last_exit_idx]
        chosen = random.choice(choices if choices else CANON_EXITS)
        self._last_exit_idx = CANON_EXITS.index(chosen)
        return chosen

    def deliver_ai_reply(self, lines: list[str]) -> None:
        """Deliver AI-generated shopkeeper speech directly into the typewriter dialogue queue."""
        if not lines:
            return
        clean_lines: list[str] = []
        for l in lines:
            text = re.sub(r"\[anim:\s*[^\\\]]+\]", "", l)
            text = re.sub(r"\[mode:\s*[^\\\]]+\]", "", text)
            text = re.sub(r"\[seen:\s*[^\\\]]+\]", "", text).strip()
            if text:
                if not text.startswith("* "):
                    text = "* " + text
                clean_lines.append(text)
        if not clean_lines:
            return
        self._dialogue_queue = clean_lines
        self._dialogue_queue_idx = 0
        self.state = ShopState.TALK_DIALOGUE
        self.set_dialogue(self._dialogue_queue[0])

    def _get_topic_dialogue(self, topic_key: str) -> list[str]:
        if topic_key == "place":
            count = self._wallet.topic_counts.get("place", 0)
            self._wallet.topic_counts["place"] = count + 1
            self._wallet.save()
            if count == 0:
                return [
                    "* I've never seen a sunset so breathtaking...",
                    "* Tell me, was everything always this beautiful?",
                    "* Beautiful... beautiful. Beautiful!",
                ]
            else:
                return [
                    "* Where I came from, the colors were bleak.",
                    "* It was like looking at the world through a napkin.",
                    "* Here, the sunset shines from the back of your eyes, like the afterglow of a light you stared at too long.",
                    "* Hee hee...",
                ]

        elif topic_key == "name":
            count = self._wallet.topic_counts.get("name", 0)
            self._wallet.topic_counts["name"] = count + 1
            self._wallet.save()
            if count == 0:
                return [
                    "* Right, of course, I'm also human. That's why I look and feel like a flower.",
                    "* ... then, what's my name?",
                    "* I suppose... it depends on the color of the sunset.",
                ]
            else:
                return [
                    "* Names, names, names! That's what everyone always thinks about.",
                    "* But, what defines you is...",
                    "* ... well, it's your body, isn't it?",
                ]

        elif topic_key == "ears":
            count = self._wallet.topic_counts.get("ears", 0)
            self._wallet.topic_counts["ears"] = count + 1
            self._wallet.save()
            variant = count % 3
            if variant == 0:  # Kris variant
                return [
                    "* Listen, have you had ears before? Cute and fluffy ears?",
                    "* ... you should try it.",
                    "* Yes, you're nodding. Obviously you agree. Obviously.",
                ]
            elif variant == 1:  # Ralsei variant
                return [
                    "* Listen, have you had ears before? Cute and fluffy ears?",
                    "* ... you should try it.",
                    "* ... not like you, long ears. Those seem like a fire hazard.",
                ]
            else:  # Susie variant
                return [
                    "* Listen, have you had ears before? Cute and fluffy ears?",
                    "* ... you should try it.",
                    "* ... especially you, purpleface. How do you even hear?",
                ]

        elif topic_key == "people":
            count = self._wallet.topic_counts.get("people", 0)
            self._wallet.topic_counts["people"] = count + 1
            self._wallet.save()
            if count == 0:
                return [
                    "* Asgore... he seems happy. You should be happy for him, too.",
                    "* Me? I've... never been able to talk to him. For... obvious reasons.",
                    "* I know. It's selfish, if you say it out loud. Everything... has been thanks to him.",
                    "* Until now, I... I couldn't really think about that.",
                    "* ...",
                    "* I can think now, though. I'll do my best to fit in and help, too.",
                ]
            else:
                return [
                    "* Up until now, I don't think I realized what loneliness means.",
                    "* Now, looking at the sunrise, I finally noticed it. That pang in my heart...",
                    "* ... I'm going to make friends here. I know it. Lots and lots of friends...",
                ]

        elif topic_key == "graduating":
            if self._visit_graduating_count == 0:
                self._visit_graduating_count += 1
                return [
                    "* I guess... I'll be \"graduating\" from here soon.",
                    "* I... I'm not just ready to leave my friends behind yet...",
                    "* But, is that something... anyone is ever ready for?",
                ]
            else:
                self._visit_graduating_count += 1
                return [
                    "* If you \"seal the Fountain\"... I won't stick around.",
                    "* I'll... need some time to myself, I think.",
                    "* But, I'll be meeting you again.",
                    "* And Ory, I'll be making sure Asgore is watering you properly, OK!?",
                ]

        elif topic_key == "egg":
            name = self._get_user_name()
            if not name or name == "Minion":
                name = "Kris"
            return [
                "* (Suddenly, the shopkeeper's body took your hand, and talked in a low voice only you could hear...)",
                f"* {name}, is your hand okay? It looks like... you've got a cat bite, mew.",
                "* Cats can be nasty creatures, can't they, mew...?",
                "* ... I once met someone who REALLY liked cats, mew.",
                "* They liked cats so much, they owned a whole hunting pack of them, mew!",
                "* Of course, cats are fickle creatures, but they were very good at finding protein.",
                f"* {name}, if you have any protein, you must keep it hidden, and never let anyone see it.",
                "* The cats are not too smart, but once they find a target, they never stop chasing it until they get bored.",
                "* And when they find you, they bite... very, VERY, hard.",
                "* Some people would do anything to get away from them, even change their appearance, or go into hiding...",
                f"* Oh, {name}, it's terrible, mew. It's terrible...",
                f"* Please be careful, {name}... promise...",
                "* H... huh? Wh... why am I trembling? Was my body saying something...?",
                "* Hey, don't have any conversations without me!! Communication is key, right, body! Body!?",
            ]

        return []

    def open_shop(self) -> None:
        self._calculate_target_geometry()
        self.state = ShopState.ROOT
        self._selected_index = 0
        self._tasks_subtab = 0
        self._config_tab = 0
        self._tasks_scroll_offset = 0
        self._alarms_scroll_offset = 0
        self._notes_scroll_offset = 0
        self._visit_graduating_count = 0
        self._input_container.hide()
        self.show()
        self.raise_()
        self.activateWindow()

        self._scene_timer.start()
        self.set_dialogue(self._get_root_greeting())

    def close_shop(self) -> None:
        self._scene_timer.stop()
        self._typewriter_timer.stop()
        self._input_container.hide()
        self.hide()
        self.closed.emit()

    def set_dialogue(self, text: str) -> None:
        self._dialogue_text = text
        self._dialogue_char_idx = 0
        self._typewriter_timer.start()
        self.update()

    def _on_typewriter_tick(self) -> None:
        if self._dialogue_char_idx < len(self._dialogue_text):
            self._dialogue_char_idx += 1
            self.update()
        else:
            self._typewriter_timer.stop()

    def _is_typing(self) -> bool:
        return self._typewriter_timer.isActive() and self._dialogue_char_idx < len(self._dialogue_text)

    def _finish_typing(self) -> None:
        self._dialogue_char_idx = len(self._dialogue_text)
        self._typewriter_timer.stop()
        self.update()

    def _is_dialogue_rect(self, pt: QPoint) -> bool:
        if self.state in (ShopState.ROOT, ShopState.EXITING):
            return 12 <= pt.x() <= 403 and 227 <= pt.y() <= 451
        elif self.state == ShopState.TALK_DIALOGUE:
            return 12 <= pt.x() <= 628 and 227 <= pt.y() <= 451
        return False

    def _on_scene_tick(self) -> None:
        cached_count = len(self._bg_cache["root"])
        if cached_count > 0:
            self._scene_frame_idx = (self._scene_frame_idx + 1) % cached_count
            self.update()

    # --- Focus Timer & Alarm Feature -------------------------------------------

    def start_timer(self, minutes: int, label: str) -> None:
        mem = self._memory or (self._pet._memory if self._pet and hasattr(self._pet, "_memory") else None)
        if mem and hasattr(mem, "add_timer"):
            mem.add_timer(minutes * 60, label)
        self._timer_total_seconds = minutes * 60
        self._timer_seconds_remaining = self._timer_total_seconds
        self._timer_label = label
        self._timer_active = True
        self._focus_timer.start()
        self.set_dialogue(f"* Timer set for {minutes}m ({label})! I'll alert you when it rings, mew!")

    def stop_timer(self) -> None:
        mem = self._memory or (self._pet._memory if self._pet and hasattr(self._pet, "_memory") else None)
        if mem and hasattr(mem, "cancel_alarm_or_timer"):
            mem.cancel_alarm_or_timer(self._timer_label)
        self._focus_timer.stop()
        self._timer_active = False
        self._timer_seconds_remaining = 0
        self.set_dialogue("* Active timer stopped, darling.")

    def _on_focus_timer_tick(self) -> None:
        if self._timer_seconds_remaining > 0:
            self._timer_seconds_remaining -= 1
            self.update()
        else:
            self.stop_timer()
            alarm_msg = f"* RING RING! {self._timer_label.upper()} IS UP, MINION!! Time to switch tasks!"
            if self._pet and hasattr(self._pet, "_say"):
                self._pet._say(alarm_msg, force=True, record_memory=False)
            if self._pet and hasattr(self._pet, "_play") and self._pet._can_play("shocked"):
                self._pet._play("shocked")
            self.set_dialogue(alarm_msg)
            self._wallet.add(2)

    # --- Evidence Detection (Screen + Sessions) --------------------------------

    def _scan_task_evidence(self, task_text: str) -> tuple[bool, bool, str]:
        stopwords = {
            "remind", "reminder", "reminders", "user", "me", "to", "add", "a", "an", "the",
            "in", "for", "you", "and", "or", "of", "on", "with", "from", "till", "this",
            "that", "it", "is", "be", "do", "have", "i", "my", "our", "out", "first",
            "feature", "please", "task", "tasks", "todos", "todo", "chore", "chores",
            "duty", "duties", "check", "work", "working", "done", "finish", "finished",
            "started", "start", "make", "just", "about", "thing", "things", "will"
        }
        words = re.findall(r"[a-zA-Z0-9_]{3,}", task_text.lower())
        keywords = [w for w in words if w not in stopwords]
        if not keywords:
            return False, False, ""

        if self._pet and hasattr(self._pet, "_tray_observations"):
            for obs in getattr(self._pet, "_tray_observations", []):
                summary = (obs.get("summary") or "").lower()
                for kw in keywords:
                    if kw in summary:
                        return True, True, kw

        sessions_dir = _BASE_DIR / "memory" / "sessions"
        if sessions_dir.exists():
            for s_file in sorted(sessions_dir.glob("*.json"), reverse=True)[:12]:
                try:
                    data = json.loads(s_file.read_text(encoding="utf-8"))
                    for msg in data.get("messages", []):
                        user_text = (msg.get("user") or "").lower()
                        had_screen = msg.get("had_screen", False)
                        for kw in keywords:
                            if kw in user_text:
                                if had_screen:
                                    return True, True, kw
                                return True, False, kw
                        if had_screen:
                            pink_text = (msg.get("pink") or "").lower()
                            for kw in keywords:
                                if kw in pink_text:
                                    return True, True, kw
                except Exception:
                    pass

        return False, False, ""

    # --- Universal Scrolling & Menu Navigation ---------------------------------

    def _scroll_up(self) -> None:
        if self.state == ShopState.TASKS:
            if self._tasks_subtab == 0:
                self._tasks_scroll_offset = max(0, self._tasks_scroll_offset - 1)
            else:
                self._alarms_scroll_offset = max(0, self._alarms_scroll_offset - 1)
        elif self.state == ShopState.SETTINGS_MENU and self._config_tab == 0:
            self._notes_scroll_offset = max(0, self._notes_scroll_offset - 1)
        self.update()

    def _scroll_down(self) -> None:
        if self.state == ShopState.TASKS:
            if self._tasks_subtab == 0:
                max_off = max(0, len(self._get_active_reminders()) - 4)
                self._tasks_scroll_offset = min(max_off, self._tasks_scroll_offset + 1)
            else:
                max_off = max(0, len(self._get_alarms_menu_items()) - 4)
                self._alarms_scroll_offset = min(max_off, self._alarms_scroll_offset + 1)
        elif self.state == ShopState.SETTINGS_MENU and self._config_tab == 0:
            max_off = max(0, len(self._get_facts_menu_items()) - 4)
            self._notes_scroll_offset = min(max_off, self._notes_scroll_offset + 1)
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta > 0:
            self._scroll_up()
        elif delta < 0:
            self._scroll_down()
        event.accept()

    def _nav_up(self) -> None:
        count = self._get_menu_count()
        if count <= 0:
            return
        if self.state == ShopState.TALK_MENU:
            self._selected_index = (self._selected_index - 2) % count
        else:
            self._selected_index = (self._selected_index - 1) % count

        # Auto-scroll viewport
        if self.state == ShopState.TASKS:
            if self._tasks_subtab == 0:
                if self._selected_index < self._tasks_scroll_offset:
                    self._tasks_scroll_offset = self._selected_index
                elif self._selected_index >= self._tasks_scroll_offset + 4:
                    self._tasks_scroll_offset = max(0, self._selected_index - 3)
            else:
                if self._selected_index < self._alarms_scroll_offset:
                    self._alarms_scroll_offset = self._selected_index
                elif self._selected_index >= self._alarms_scroll_offset + 4:
                    self._alarms_scroll_offset = max(0, self._selected_index - 3)
        elif self.state == ShopState.SETTINGS_MENU and self._config_tab == 0:
            if self._selected_index < self._notes_scroll_offset:
                self._notes_scroll_offset = self._selected_index
            elif self._selected_index >= self._notes_scroll_offset + 4:
                self._notes_scroll_offset = max(0, self._selected_index - 3)

        self._on_selection_changed()
        self.update()

    def _nav_down(self) -> None:
        count = self._get_menu_count()
        if count <= 0:
            return
        if self.state == ShopState.TALK_MENU:
            self._selected_index = (self._selected_index + 2) % count
        else:
            self._selected_index = (self._selected_index + 1) % count

        # Auto-scroll viewport
        if self.state == ShopState.TASKS:
            if self._tasks_subtab == 0:
                if self._selected_index < self._tasks_scroll_offset:
                    self._tasks_scroll_offset = self._selected_index
                elif self._selected_index >= self._tasks_scroll_offset + 4:
                    self._tasks_scroll_offset = max(0, self._selected_index - 3)
            else:
                if self._selected_index < self._alarms_scroll_offset:
                    self._alarms_scroll_offset = self._selected_index
                elif self._selected_index >= self._alarms_scroll_offset + 4:
                    self._alarms_scroll_offset = max(0, self._selected_index - 3)
        elif self.state == ShopState.SETTINGS_MENU and self._config_tab == 0:
            if self._selected_index < self._notes_scroll_offset:
                self._notes_scroll_offset = self._selected_index
            elif self._selected_index >= self._notes_scroll_offset + 4:
                self._notes_scroll_offset = max(0, self._selected_index - 3)

        self._on_selection_changed()
        self.update()

    def _get_menu_count(self) -> int:
        if self.state == ShopState.ROOT:
            return 5  # CHARACTER, TASKS, TALK, CONFIG & SETTINGS, EXIT
        elif self.state == ShopState.CHARACTER:
            return len(CHARACTER_FORMS) + 1  # Forms + Back
        elif self.state == ShopState.TASKS:
            if self._tasks_subtab == 0:
                return len(self._get_active_reminders()) + 1  # Reminders + Back
            else:
                return len(self._get_alarms_menu_items()) + 1  # Alarms items + Back
        elif self.state in (ShopState.TASK_CONFIRM, ShopState.TASK_SECOND_CONFIRM):
            return 2  # YES, NO
        elif self.state == ShopState.TALK_MENU:
            return len(TALK_TOPICS)  # 8 items
        elif self.state == ShopState.SETTINGS_MENU:
            if self._config_tab == 0:
                return len(self._get_facts_menu_items()) + 1  # Facts items + Back
            else:
                return 5  # 4 toggles + Back
        return 0

    def _on_selection_changed(self) -> None:
        if self.state == ShopState.CHARACTER:
            if self._selected_index < len(CHARACTER_FORMS):
                f = CHARACTER_FORMS[self._selected_index]
                if f.get("locked"):
                    self.set_dialogue(f"* {f['name']}: LOCKED!\n* There is only one character: Pink!")
                else:
                    self.set_dialogue(f"* {f['name']}: The one and only companion in this realm!")
            else:
                self.set_dialogue(CANON_BUY_REFUSE)
        elif self.state == ShopState.TALK_MENU:
            if self._selected_index < len(TALK_TOPICS):
                title, key = TALK_TOPICS[self._selected_index]
                if key == "back":
                    self.set_dialogue(self._get_root_greeting())
                else:
                    self.set_dialogue(f"* ... Topic: {title}")
        elif self.state == ShopState.SETTINGS_MENU and self._config_tab == 0:
            notes = self._get_fact_notes()
            if self._selected_index >= 2 and (self._selected_index - 2) < len(notes):
                full_note = notes[self._selected_index - 2]
                self.set_dialogue(f"* Fact Note #{self._selected_index - 1}:\n* \"{full_note}\"")

    def _confirm_selection(self) -> None:
        if self.state == ShopState.ROOT:
            if self._selected_index == 0:  # CHARACTER (LOCKED)
                self.state = ShopState.CHARACTER
                self._selected_index = 0
                self.set_dialogue(CANON_BUY_LOCKED)
            elif self._selected_index == 1:  # TASKS & ALARMS
                self.state = ShopState.TASKS
                self._tasks_subtab = 0
                self._selected_index = 0
                self._tasks_scroll_offset = 0
                reminders = self._get_active_reminders()
                if not reminders:
                    self.set_dialogue(CANON_SELL_EMPTY)
                else:
                    self.set_dialogue(random.choice(CANON_SELL_LINES))
            elif self._selected_index == 2:  # TALK
                self.state = ShopState.TALK_MENU
                self._selected_index = 0
                self.set_dialogue(CANON_TALK_ENTER)
            elif self._selected_index == 3:  # CONFIG & SETTINGS
                self.state = ShopState.SETTINGS_MENU
                self._config_tab = 0
                self._selected_index = 0
                self._notes_scroll_offset = 0
                self.set_dialogue("* Permanent memory fact sheet & companion configuration.")
            elif self._selected_index == 4:  # EXIT
                self._start_exit()

        elif self.state == ShopState.CHARACTER:
            if self._selected_index < len(CHARACTER_FORMS):
                self.set_dialogue("* Locked! There is only one character here, darling!\n* You can't replace me, minion!")
            else:
                self.state = ShopState.ROOT
                self._selected_index = 0
                self.set_dialogue(CANON_BUY_REFUSE)

        elif self.state == ShopState.TASKS:
            if self._tasks_subtab == 0:
                reminders = self._get_active_reminders()
                if self._selected_index < len(reminders):
                    task_text = reminders[self._selected_index]
                    self._pending_sell_reminder = task_text
                    self._pending_sell_value = evaluate_task_value(task_text)

                    has_ev, on_screen, kw = self._scan_task_evidence(task_text)
                    self._sell_has_evidence = has_ev
                    self._sell_saw_on_screen = on_screen
                    self._sell_evidence_kw = kw

                    self.state = ShopState.TASK_CONFIRM
                    self._selected_index = 0
                    if has_ev:
                        proof_loc = "on screen" if on_screen else "in session logs"
                        self.set_dialogue(
                            f"* You're gonna give me stuff?\n* Found proof of '{kw}' {proof_loc}! Complete for P$ {self._pending_sell_value}?"
                        )
                    else:
                        self.set_dialogue(
                            f"* Huh?\n* I haven't seen you do '{kw or task_text[:12]}' at all... Are you sure you finished it?"
                        )
                else:
                    self.state = ShopState.ROOT
                    self._selected_index = 1
                    self.set_dialogue(self._get_root_greeting())
            else:  # Alarms sub-tab
                alarms_items = self._get_alarms_menu_items()
                if self._selected_index < len(alarms_items):
                    item = alarms_items[self._selected_index]
                    kind = item.get("kind")
                    if kind == "preset":
                        mins = item.get("mins", 5)
                        lbl = item.get("label", "Timer")
                        self.start_timer(mins, lbl)
                    elif kind == "custom":
                        self._prompt_custom_timer()
                    elif kind == "active_shop":
                        self.stop_timer()
                    elif kind == "cancel_memory":
                        target = item.get("target")
                        if self._pet and hasattr(self._pet, "_memory") and self._pet._memory:
                            ok, lbl = self._pet._memory.cancel_alarm_or_timer(target)
                            if ok:
                                self.set_dialogue(f"* Cancelled timer/alarm (\"{lbl}\"), mew!")
                            else:
                                self.set_dialogue(f"* Could not cancel {target}, dummy!")
                    elif kind == "stop_all":
                        if self._pet and hasattr(self._pet, "_memory") and self._pet._memory:
                            self._pet._memory.clear_all_alarms()
                        self.stop_timer()
                        self.set_dialogue("* All alarms and timers cleared, minion!")
                else:
                    self.state = ShopState.ROOT
                    self._selected_index = 1
                    self.set_dialogue(self._get_root_greeting())

        elif self.state == ShopState.TASK_CONFIRM:
            if self._selected_index == 0:
                if self._sell_has_evidence:
                    if self._pending_sell_reminder:
                        self._complete_reminder(self._pending_sell_reminder, self._pending_sell_value)
                        self._pending_sell_reminder = None
                    self.state = ShopState.TASKS
                    self._selected_index = 0
                else:
                    self.state = ShopState.TASK_SECOND_CONFIRM
                    self._selected_index = 1
                    self.set_dialogue(
                        "* Huh?!\n* Hold it! I didn't see you do that on screen at all!\n* Are you telling the truth, minion?!"
                    )
            else:
                self._pending_sell_reminder = None
                self.state = ShopState.TASKS
                self._selected_index = 0
                self.set_dialogue(CANON_SELL_REFUSE)

        elif self.state == ShopState.TASK_SECOND_CONFIRM:
            if self._selected_index == 0:
                if self._pending_sell_reminder:
                    self._complete_reminder(self._pending_sell_reminder, self._pending_sell_value)
                    self._pending_sell_reminder = None
                self.state = ShopState.TASKS
                self._selected_index = 0
                self.set_dialogue(
                    f"{CANON_SELL_SUCCESS}\n* ... Hmph! I'll take your word for it this ONCE! (+P$ {self._pending_sell_value})"
                )
            else:
                self._pending_sell_reminder = None
                self.state = ShopState.TASKS
                self._selected_index = 0
                self.set_dialogue(
                    f"{CANON_SELL_UNSELLABLE}\n* Caught you red-handed trying to swindle my boutique!\n* No P$ for fake work!"
                )

        elif self.state == ShopState.TALK_MENU:
            if self._selected_index < len(TALK_TOPICS):
                topic_title, topic_key = TALK_TOPICS[self._selected_index]
                if topic_key == "back":
                    self.state = ShopState.ROOT
                    self._selected_index = 2
                    self.set_dialogue(self._get_root_greeting())
                elif topic_key == "ai_ask":
                    self.state = ShopState.TALK_DIALOGUE
                    self._prompt_serious_inquiry()
                else:
                    queue = self._get_topic_dialogue(topic_key)
                    if queue:
                        self._dialogue_queue = queue
                        self._dialogue_queue_idx = 0
                        self.state = ShopState.TALK_DIALOGUE
                        self.set_dialogue(self._dialogue_queue[0])

        elif self.state == ShopState.TALK_DIALOGUE:
            if self._is_typing():
                self._finish_typing()
            else:
                self._dialogue_queue_idx += 1
                if self._dialogue_queue_idx < len(self._dialogue_queue):
                    self.set_dialogue(self._dialogue_queue[self._dialogue_queue_idx])
                else:
                    self.state = ShopState.TALK_MENU
                    self.set_dialogue(CANON_TALK_ENTER)

        elif self.state == ShopState.SETTINGS_MENU:
            if self._config_tab == 0:  # Edit Facts Tab
                items = self._get_facts_menu_items()
                if self._selected_index == 0:  # Edit Nickname
                    self._prompt_change_nickname()
                elif self._selected_index == 1:  # Add New Fact Note
                    self._prompt_add_fact()
                elif self._selected_index < len(items):  # Selected a specific saved note
                    note_idx = self._selected_index - 2
                    notes = self._get_fact_notes()
                    if 0 <= note_idx < len(notes):
                        note_val = notes[note_idx]
                        self.set_dialogue(f"* Permanent Note #{note_idx + 1}:\n* \"{note_val}\"")
                else:  # Back
                    self.state = ShopState.ROOT
                    self._selected_index = 3
                    self.set_dialogue(self._get_root_greeting())
            else:  # Toggles Tab
                if self._selected_index == 0:  # Dialogue Bubbles
                    if self._pet and hasattr(self._pet, "_dialogue_enabled"):
                        self._pet._dialogue_enabled = not self._pet._dialogue_enabled
                        state_str = "ENABLED" if self._pet._dialogue_enabled else "DISABLED"
                        self.set_dialogue(f"* Dialogue bubbles are now {state_str}, mew!")
                elif self._selected_index == 1:  # Song Commentary
                    if self._pet and hasattr(self._pet, "_ai_song_comment_enabled"):
                        self._pet._ai_song_comment_enabled = not self._pet._ai_song_comment_enabled
                        state_str = "ENABLED" if self._pet._ai_song_comment_enabled else "DISABLED"
                        self.set_dialogue(f"* Autonomous song reactions are now {state_str}, darling!")
                elif self._selected_index == 2:  # Bomb Mode
                    if self._pet and hasattr(self._pet, "_bomb_attack_enabled"):
                        self._pet._bomb_attack_enabled = not self._pet._bomb_attack_enabled
                        state_str = "ARMED" if self._pet._bomb_attack_enabled else "DISARMED"
                        self.set_dialogue(f"* Cat-head bombs are now {state_str}, mew!")
                elif self._selected_index == 3:  # Jump Mode
                    if self._pet and hasattr(self._pet, "_jump_enabled"):
                        self._pet._jump_enabled = not self._pet._jump_enabled
                        state_str = "ENABLED" if self._pet._jump_enabled else "DISABLED"
                        self.set_dialogue(f"* Jump-to-cursor is now {state_str}, minion!")
                else:  # Back
                    self.state = ShopState.ROOT
                    self._selected_index = 3
                    self.set_dialogue(self._get_root_greeting())

        self.update()

    def _cancel_or_back(self) -> None:
        if self._input_container.isVisible():
            self._on_input_cancelled()
            return
        if self.state in (ShopState.CHARACTER, ShopState.TASKS, ShopState.SETTINGS_MENU, ShopState.TALK_MENU):
            self.state = ShopState.ROOT
            self._selected_index = 0
            self.set_dialogue(self._get_root_greeting())
        elif self.state in (ShopState.TASK_CONFIRM, ShopState.TASK_SECOND_CONFIRM):
            self.state = ShopState.TASKS
            self._selected_index = 0
            self.set_dialogue(CANON_SELL_REFUSE)
        elif self.state == ShopState.TALK_DIALOGUE:
            self.state = ShopState.TALK_MENU
            self.set_dialogue(CANON_TALK_ENTER)
        elif self.state == ShopState.ROOT:
            self._start_exit()
        self.update()

    def _start_exit(self) -> None:
        self.state = ShopState.EXITING
        self.set_dialogue(self._get_exit_line())
        QTimer.singleShot(1100, self.close_shop)

    # --- Facts, Notes & Reminders Handling ------------------------------------

    def _get_facts_file_path(self) -> Path:
        if hasattr(self, "_memory") and self._memory and hasattr(self._memory, "facts_path"):
            if self._memory.facts_path.exists():
                return self._memory.facts_path
        if FACTS_PATH.exists():
            return FACTS_PATH
        if hasattr(self, "_memory") and self._memory and hasattr(self._memory, "facts_path"):
            return self._memory.facts_path
        return FACTS_PATH

    def _get_user_name(self) -> str:
        if hasattr(self, "_memory") and self._memory and hasattr(self._memory, "get_user_name"):
            return self._memory.get_user_name()
        p = self._get_facts_file_path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data.get("user_name", "Minion")
            except Exception:
                pass
        return "Minion"

    def _get_fact_notes(self) -> list[str]:
        p = self._get_facts_file_path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return list(data.get("notes", []))
            except Exception as e:
                log.warning("Could not load fact notes from %s: %s", p, e)
        return []

    def _save_facts(self, name: str | None = None, new_note: str | None = None) -> None:
        if name and hasattr(self, "_memory") and self._memory and hasattr(self._memory, "set_user_name"):
            self._memory.set_user_name(name)
        if new_note and hasattr(self, "_memory") and self._memory and hasattr(self._memory, "add_fact"):
            self._memory.add_fact(new_note)

        p = self._get_facts_file_path()
        data = {"user_name": "Minion", "notes": []}
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
        if name:
            data["user_name"] = name
        if new_note:
            notes = data.get("notes", [])
            if new_note not in notes:
                notes.append(new_note)
            data["notes"] = notes
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning("Error saving facts to %s: %s", p, e)

    def _get_facts_menu_items(self) -> list[str]:
        name = self._get_user_name()
        notes = self._get_fact_notes()
        items = [
            f"Nickname: [{name}] (Edit)",
            "[+ Add New Fact Note]",
        ]
        for i, n in enumerate(notes):
            preview = n.replace("\n", " ").strip()
            if len(preview) > 28:
                preview = preview[:27] + "..."
            items.append(f"{i+1}. {preview}")
        return items

    def _get_active_reminders(self) -> list[str]:
        if not self._memory:
            return []
        try:
            if hasattr(self._memory, "get_active_reminders"):
                reminders = self._memory.get_active_reminders()
            elif hasattr(self._memory, "get_reminders"):
                reminders = self._memory.get_reminders()
            else:
                reminders = []
            return [r.get("text", "") for r in reminders if r.get("text")]
        except Exception as e:
            log.warning("Could not fetch active reminders: %s", e)
            return []

    def _complete_reminder(self, text: str, reward: int) -> None:
        if not self._memory:
            return
        ok, deleted_text = self._memory.delete_reminder(text)
        if ok:
            self._wallet.add(reward)
            self.set_dialogue(
                f"{CANON_SELL_SUCCESS}\n* \"{deleted_text}\" finished! (+P$ {reward})"
            )
        else:
            self.set_dialogue(f"{CANON_SELL_UNSELLABLE}\n* Couldn't process that reminder, silly!")

    def _get_active_alarms_list(self) -> list[dict[str, Any]]:
        mem = self._memory or (self._pet._memory if self._pet and hasattr(self._pet, "_memory") else None)
        if mem and hasattr(mem, "get_active_alarms"):
            try:
                return mem.get_active_alarms()
            except Exception as e:
                log.warning("Could not fetch active alarms: %s", e)
        return []

    def _get_alarms_menu_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = [
            {"kind": "preset", "mins": 5, "label": "Start 5m Break"},
            {"kind": "preset", "mins": 15, "label": "Start 15m Sprint"},
            {"kind": "preset", "mins": 25, "label": "Start 25m Pomodoro"},
            {"kind": "custom", "label": "Custom Timer..."},
        ]
        if self._timer_active and self._timer_seconds_remaining > 0:
            m, s = divmod(self._timer_seconds_remaining, 60)
            items.append({
                "kind": "active_shop",
                "label": f"[Active] {self._timer_label} ({m:02d}:{s:02d}) [STOP]",
            })
        active_alarms = self._get_active_alarms_list()
        for a in active_alarms:
            if a.get("state") == "active":
                lbl = a.get("label", "Alarm")
                if a.get("kind") == "timer":
                    tgt = a.get("target_timestamp", 0)
                    rem = max(0, int(tgt - time.time()))
                    m, s = divmod(rem, 60)
                    items.append({
                        "kind": "cancel_memory",
                        "target": a.get("id") or lbl,
                        "label": f"[Active] {lbl} ({m:02d}:{s:02d}) [STOP]",
                    })
                elif a.get("kind") == "alarm":
                    items.append({
                        "kind": "cancel_memory",
                        "target": a.get("id") or lbl,
                        "label": f"[Alarm] {a.get('clock_time')} ({lbl}) [STOP]",
                    })
        if len(items) > 4:
            items.append({"kind": "stop_all", "label": "Stop All Alarms & Timers"})
        return items

    # --- Prompt Input Helpers (with Send & X buttons) --------------------------

    def _prompt_change_nickname(self) -> None:
        self._input_mode = "fact_name"
        self._show_input_bar(f"Enter your new nickname (current: {self._get_user_name()}):")

    def _prompt_add_fact(self) -> None:
        self._input_mode = "fact_note"
        self._show_input_bar("Enter a new fact note for Pink to permanently remember:")

    def _prompt_custom_timer(self) -> None:
        self._input_mode = "custom_timer"
        self._show_input_bar("Enter timer length in minutes (e.g. 10 or 45):")

    def _prompt_serious_inquiry(self) -> None:
        self._input_mode = "ai_ask"
        self._show_input_bar("Ask Pink a serious question about life, work, or the digital world:")

    def _show_input_bar(self, prompt: str) -> None:
        self.set_dialogue(f"* {prompt}")
        scaled_w = round(CANVAS_W * self._scale)
        input_w = round(590 * self._scale)
        input_h = round(38 * self._scale)
        input_x = (scaled_w - input_w) // 2
        input_y = round(380 * self._scale)
        self._input_container.setGeometry(input_x, input_y, input_w, input_h)

        btn_h = input_h - 8
        cancel_w = round(32 * self._scale)
        send_w = round(64 * self._scale)
        btn_x_cancel = input_w - cancel_w - 4
        btn_x_send = btn_x_cancel - send_w - 6
        input_text_w = btn_x_send - 8

        self._ai_input.setGeometry(4, 4, input_text_w, btn_h)
        self._input_send_btn.setGeometry(btn_x_send, 4, send_w, btn_h)
        self._input_cancel_btn.setGeometry(btn_x_cancel, 4, cancel_w, btn_h)

        self._ai_input.clear()
        self._input_container.show()
        self._ai_input.setFocus()

    def _on_input_cancelled(self) -> None:
        self._input_container.hide()
        self.set_dialogue("* Cancelled, darling.")
        self.update()

    def _on_input_submitted(self) -> None:
        val = self._ai_input.text().strip()
        self._input_container.hide()
        if not val:
            return

        if self._input_mode == "fact_name":
            self._save_facts(name=val)
            self.set_dialogue(f"* I shall address you as '{val}' from now on, darling!")
        elif self._input_mode == "fact_note":
            self._save_facts(new_note=val)
            self.set_dialogue(f"* Inscribed into my permanent fact logs:\n* \"{val}\"")
        elif self._input_mode == "custom_timer":
            try:
                mins = int(val)
                if mins > 0:
                    self.start_timer(mins, "Custom Focus")
                else:
                    self.set_dialogue("* Positive minutes only, silly!")
            except ValueError:
                self.set_dialogue("* That wasn't a valid number of minutes, dummy!")
        elif self._input_mode == "ai_ask":
            self.set_dialogue(f"* \"{val}\"\n* ... *pondering seriously with folded paws* ...")
            if self._pet and hasattr(self._pet, "_on_chat_submitted"):
                serious_prompt = (
                    f"(SPECIAL DELTARUNE SHOPKEEPER MODE: You are Mad Mew Mew inside your quiet boutique sanctuary with the breathtaking sunset glowing outside. "
                    f"Answer in character with your canon shopkeeper voice: poetic, wistful, slightly surreal reflections on sunsets, napkins, bodies, flowers, and loneliness, "
                    f"with sudden shopkeeper enthusiasm ('Enjoy. Enjoy! ENJOY!!'), dry humor ('Ever heard of dollars?', 'I could always use a knife.'), "
                    f"or uncanny whispers about cat bites and your body vessel. Keep it concise, under 45 words, starting every line with '* '.) {val}"
                )
                self._pet._on_chat_submitted(serious_prompt, see_screen=False)

    # --- Mouse & Keyboard ------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if self._input_container.isVisible():
            if key == Qt.Key_Escape:
                self._on_input_cancelled()
            super().keyPressEvent(event)
            return

        # Sub-tab switching via Tab key
        if key == Qt.Key_Tab:
            if self.state == ShopState.TASKS:
                self._tasks_subtab = 1 - self._tasks_subtab
                self._selected_index = 0
                self._on_selection_changed()
                self.update()
                return
            elif self.state == ShopState.SETTINGS_MENU:
                self._config_tab = 1 - self._config_tab
                self._selected_index = 0
                self._on_selection_changed()
                self.update()
                return

        if key in (Qt.Key_Up, Qt.Key_W):
            self._nav_up()
        elif key in (Qt.Key_Down, Qt.Key_S):
            self._nav_down()
        elif key in (Qt.Key_Left, Qt.Key_A):
            if self.state == ShopState.TALK_MENU:
                if self._selected_index % 2 == 1:
                    self._selected_index -= 1
                    self._on_selection_changed()
                    self.update()
            elif self.state == ShopState.TASKS and self._tasks_subtab == 1:
                self._tasks_subtab = 0
                self._selected_index = 0
                self.update()
            elif self.state == ShopState.SETTINGS_MENU and self._config_tab == 1:
                self._config_tab = 0
                self._selected_index = 0
                self.update()
        elif key in (Qt.Key_Right, Qt.Key_D):
            if self.state == ShopState.TALK_MENU:
                if self._selected_index % 2 == 0:
                    self._selected_index += 1
                    self._on_selection_changed()
                    self.update()
            elif self.state == ShopState.TASKS and self._tasks_subtab == 0:
                self._tasks_subtab = 1
                self._selected_index = 0
                self.update()
            elif self.state == ShopState.SETTINGS_MENU and self._config_tab == 0:
                self._config_tab = 1
                self._selected_index = 0
                self.update()
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Z, Qt.Key_Space):
            if self.state == ShopState.TALK_DIALOGUE and self._is_typing():
                self._finish_typing()
                return
            self._confirm_selection()
        elif key in (Qt.Key_Escape, Qt.Key_X, Qt.Key_Backspace):
            self._cancel_or_back()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            pos_canvas = self._screen_to_canvas(event.pos())

            # 1. Dialogue skip loading without dismissing
            if self._is_dialogue_rect(pos_canvas):
                if self._is_typing():
                    self._finish_typing()
                    return
                elif self.state == ShopState.TALK_DIALOGUE:
                    self._confirm_selection()
                    return

            # 2. Check sub-tab header clicks in TASKS or SETTINGS
            if self.state == ShopState.TASKS:
                if 242 <= pos_canvas.y() <= 270:
                    if 25 <= pos_canvas.x() <= 185:
                        self._tasks_subtab = 0
                        self._selected_index = 0
                        self._tasks_scroll_offset = 0
                        self.update()
                        return
                    elif 195 <= pos_canvas.x() <= 360:
                        self._tasks_subtab = 1
                        self._selected_index = 0
                        self._alarms_scroll_offset = 0
                        self.update()
                        return
            elif self.state == ShopState.SETTINGS_MENU:
                if 242 <= pos_canvas.y() <= 270:
                    if 25 <= pos_canvas.x() <= 185:
                        self._config_tab = 0
                        self._selected_index = 0
                        self._notes_scroll_offset = 0
                        self.update()
                        return
                    elif 195 <= pos_canvas.x() <= 360:
                        self._config_tab = 1
                        self._selected_index = 0
                        self.update()
                        return

            # 3. Check scroll arrow clicks
            if self.state == ShopState.TASKS:
                if 370 <= pos_canvas.x() <= 405:
                    if 265 <= pos_canvas.y() <= 295:
                        self._scroll_up()
                        return
                    elif 390 <= pos_canvas.y() <= 425:
                        self._scroll_down()
                        return
            elif self.state == ShopState.SETTINGS_MENU and self._config_tab == 0:
                if 370 <= pos_canvas.x() <= 405:
                    if 265 <= pos_canvas.y() <= 295:
                        self._scroll_up()
                        return
                    elif 390 <= pos_canvas.y() <= 425:
                        self._scroll_down()
                        return

            # 4. Menu item selection & instant single-click execution
            clicked_idx = self._get_item_at_canvas_pos(pos_canvas)
            if clicked_idx is not None:
                self._selected_index = clicked_idx
                self._on_selection_changed()
                self._confirm_selection()
                self.update()
                return

            # 5. Draggable upper stage
            if pos_canvas.y() < 220 and pos_canvas.x() < 410:
                self._drag_active = True
                self._drag_start_pos = event.globalPos() - self.pos()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_active:
            self.move(event.globalPos() - self._drag_start_pos)
            return

        pos_canvas = self._screen_to_canvas(event.pos())
        hover_idx = self._get_item_at_canvas_pos(pos_canvas)
        is_dialogue = self._is_dialogue_rect(pos_canvas)

        # Check sub-tab header hover
        is_tab_hover = False
        if self.state in (ShopState.TASKS, ShopState.SETTINGS_MENU):
            if 242 <= pos_canvas.y() <= 270 and 25 <= pos_canvas.x() <= 360:
                is_tab_hover = True

        if hover_idx is not None or is_tab_hover:
            self.setCursor(Qt.PointingHandCursor)
            if hover_idx is not None and hover_idx != self._selected_index:
                self._selected_index = hover_idx
                self._on_selection_changed()
                self.update()
        elif is_dialogue and (self._is_typing() or self.state == ShopState.TALK_DIALOGUE):
            self.setCursor(Qt.PointingHandCursor)
        elif pos_canvas.y() < 220 and pos_canvas.x() < 410:
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def leaveEvent(self, event) -> None:
        self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_active = False

    def _screen_to_canvas(self, pt: QPoint) -> QPoint:
        x = round(pt.x() / self._scale)
        y = round(pt.y() / self._scale)
        return QPoint(x, y)

    def _get_item_at_canvas_pos(self, pt: QPoint) -> int | None:
        if self.state == ShopState.ROOT:
            if 412 <= pt.x() <= 628 and 245 <= pt.y() <= 430:
                idx = (pt.y() - 250) // 36
                if 0 <= idx < 5:
                    return idx

        elif self.state == ShopState.CHARACTER:
            if 20 <= pt.x() <= 403 and 250 <= pt.y() <= 435:
                idx = (pt.y() - 250) // 42
                if 0 <= idx < len(CHARACTER_FORMS):
                    return idx
            if 412 <= pt.x() <= 628 and 385 <= pt.y() <= 440:
                return len(CHARACTER_FORMS)

        elif self.state == ShopState.TASKS:
            if 20 <= pt.x() <= 385 and 272 <= pt.y() <= 420:
                row = (pt.y() - 272) // 36
                if 0 <= row < 4:
                    if self._tasks_subtab == 0:
                        idx = row + self._tasks_scroll_offset
                        if idx < len(self._get_active_reminders()):
                            return idx
                    else:
                        idx = row + self._alarms_scroll_offset
                        if idx < len(self._get_alarms_menu_items()):
                            return idx
            if 412 <= pt.x() <= 628 and 385 <= pt.y() <= 440:
                return self._get_menu_count() - 1

        elif self.state in (ShopState.TASK_CONFIRM, ShopState.TASK_SECOND_CONFIRM):
            if 412 <= pt.x() <= 628:
                if 295 <= pt.y() <= 345:
                    return 0
                elif 350 <= pt.y() <= 405:
                    return 1

        elif self.state == ShopState.SETTINGS_MENU:
            if 20 <= pt.x() <= 385 and 272 <= pt.y() <= 420:
                row = (pt.y() - 272) // 36
                if 0 <= row < 4:
                    if self._config_tab == 0:
                        idx = row + self._notes_scroll_offset
                        if idx < len(self._get_facts_menu_items()):
                            return idx
                    else:
                        if 0 <= row < 4:
                            return row
            if 412 <= pt.x() <= 628 and 385 <= pt.y() <= 440:
                return self._get_menu_count() - 1

        elif self.state == ShopState.TALK_MENU:
            if 255 <= pt.y() <= 435:
                row = min(3, max(0, (pt.y() - 255) // 44))
                col = 0 if pt.x() < 320 else 1
                idx = row * 2 + col
                if 0 <= idx < len(TALK_TOPICS):
                    return idx

        return None

    # --- Painting & Rendering (Zero Allocations) -------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.SmoothPixmapTransform, False)
            p.scale(self._scale, self._scale)

            state_key = "root"
            if self.state in (ShopState.CHARACTER, ShopState.TASKS, ShopState.TASK_CONFIRM,
                              ShopState.TASK_SECOND_CONFIRM, ShopState.SETTINGS_MENU):
                state_key = "buy"
            elif self.state in (ShopState.TALK_MENU, ShopState.TALK_DIALOGUE):
                state_key = "talk"

            cached_frames = self._bg_cache[state_key]
            if cached_frames:
                frame = cached_frames[self._scene_frame_idx % len(cached_frames)]
                p.drawPixmap(0, 0, frame)

            if self.state == ShopState.ROOT:
                self._draw_root_state(p)
            elif self.state == ShopState.CHARACTER:
                self._draw_character_state(p)
            elif self.state == ShopState.TASKS:
                self._draw_tasks_and_alarms_state(p)
            elif self.state == ShopState.TASK_CONFIRM:
                self._draw_task_confirm_state(p)
            elif self.state == ShopState.TASK_SECOND_CONFIRM:
                self._draw_task_second_confirm_state(p)
            elif self.state == ShopState.SETTINGS_MENU:
                self._draw_settings_and_facts_state(p)
            elif self.state in (ShopState.TALK_MENU, ShopState.TALK_DIALOGUE):
                self._draw_talk_state(p)
            elif self.state == ShopState.EXITING:
                self._draw_dialogue_text(p, QRect(32, 248, 355, 185))

        finally:
            p.end()

    def _draw_dialogue_text(self, p: QPainter, rect: QRect) -> None:
        p.setFont(self._font_body)
        p.setPen(QColor(255, 255, 255))
        visible_text = self._dialogue_text[: self._dialogue_char_idx]
        p.drawText(rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, visible_text)

    def _draw_root_state(self, p: QPainter) -> None:
        self._draw_dialogue_text(p, QRect(32, 248, 355, 185))

        p.setFont(self._font_body)
        options = ["CHARACTER", "TASKS & ALARMS", "TALK", "CONFIG & SETTINGS", "EXIT"]
        start_x = 444
        start_y = 262
        line_h = 36

        for i, opt in enumerate(options):
            is_active = (i == self._selected_index)
            color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
            p.setPen(color)
            p.drawText(start_x, start_y + i * line_h, opt)

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

        p.setFont(self._font_small)
        p.setPen(QColor(255, 180, 220))
        p.drawText(430, 438, f"P$ {self._wallet.pink_dollars:06d}")

    def _draw_character_state(self, p: QPainter) -> None:
        # Top-Right Details Card
        p.setFont(self._font_title)
        p.setPen(QColor(255, 255, 0))
        p.drawText(426, 38, "Wardrobe [LOCKED]")

        p.setFont(self._font_small)
        p.setPen(QColor(255, 140, 180))
        p.drawText(426, 60, "Only Pink Exists!")

        p.setPen(QColor(255, 255, 255))
        p.drawText(
            QRect(426, 75, 188, 140),
            Qt.AlignLeft | Qt.TextWordWrap,
            "There is only ONE character in this sanctuary: Pink (Mad Mew Mew)!\nOther forms are locked because you can't replace me, minion!",
        )

        # Bottom-Left Forms List
        p.setFont(self._font_body)
        start_x = 44
        start_y = 265
        line_h = 42

        for i, f in enumerate(CHARACTER_FORMS):
            is_sel = (i == self._selected_index)
            is_locked = f.get("locked", False)
            color = QColor(255, 255, 0) if is_sel else (QColor(150, 150, 160) if is_locked else QColor(170, 255, 230))
            p.setPen(color)

            mark = " [EQUIPPED]" if not is_locked else " [LOCKED]"
            p.drawText(start_x, start_y + i * line_h, f"{f['name']}{mark}")

            cost_str = "ACTIVE" if not is_locked else "LOCKED"
            p.setPen(QColor(157, 162, 196) if not is_sel else QColor(255, 255, 0))
            p.drawText(310, start_y + i * line_h, cost_str)

            if is_sel and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

        # Bottom-Right Wallet & Back
        p.setFont(self._font_body)
        p.setPen(QColor(255, 180, 220))
        p.drawText(430, 265, "Pink Dollars:")
        p.setPen(QColor(255, 255, 255))
        p.drawText(430, 295, f"P$ {self._wallet.pink_dollars:06d}")

        p.setFont(self._font_title)
        is_back = (self._selected_index == len(CHARACTER_FORMS))
        p.setPen(QColor(255, 255, 0) if is_back else QColor(255, 255, 255))
        p.drawText(450, 415, "Back")
        if is_back and self._soul_heart:
            p.drawPixmap(424, 401, self._soul_heart)

    def _draw_tasks_and_alarms_state(self, p: QPainter) -> None:
        # Sub-tab Headers: [ 1. TASKS ]   [ 2. ALARMS ]
        p.setFont(self._font_title)
        tab0_active = (self._tasks_subtab == 0)
        p.setPen(QColor(255, 255, 0) if tab0_active else QColor(160, 160, 190))
        p.drawText(35, 262, "[ 1. TASKS ]")

        p.setPen(QColor(255, 255, 0) if not tab0_active else QColor(160, 160, 190))
        p.drawText(195, 262, "[ 2. ALARMS ]")

        # Top-Right Info Card
        if self._tasks_subtab == 0:
            p.setFont(self._font_title)
            p.setPen(QColor(255, 180, 220))
            p.drawText(426, 38, "Chore Board")

            p.setFont(self._font_small)
            p.setPen(QColor(140, 206, 255))
            reminders = self._get_active_reminders()
            p.drawText(426, 60, f"Active Tasks: {len(reminders)}")

            p.setPen(QColor(255, 255, 255))
            p.drawText(
                QRect(426, 75, 188, 140),
                Qt.AlignLeft | Qt.TextWordWrap,
                "Pink awards P$ 1 - P$ 3 per completed task.\nShe checks your screen history & session memories for proof before paying!",
            )
        else:
            p.setFont(self._font_title)
            p.setPen(QColor(170, 255, 230))
            p.drawText(426, 38, "Focus Alarm")

            p.setFont(self._font_small)
            p.setPen(QColor(140, 206, 255))
            if self._timer_active:
                mins = self._timer_seconds_remaining // 60
                secs = self._timer_seconds_remaining % 60
                p.drawText(426, 60, f"Remaining: {mins:02d}:{secs:02d}")
            else:
                p.drawText(426, 60, "Status: Ready")

            p.setPen(QColor(255, 255, 255))
            p.drawText(
                QRect(426, 75, 188, 140),
                Qt.AlignLeft | Qt.TextWordWrap,
                "Pick a focus sprint or break timer.\nPink provides visual alert animations and bonus P$ upon completion!",
            )

        # Bottom-Left List Area (Scrollable with 4 visible rows)
        start_x = 44
        start_y = 295
        line_h = 36

        if self._tasks_subtab == 0:
            reminders = self._get_active_reminders()
            if not reminders:
                p.setFont(self._font_body)
                p.setPen(QColor(180, 180, 180))
                p.drawText(start_x, start_y + 20, "* No active tasks on board.")
                p.drawText(start_x, start_y + 55, "* Use /remind in chat to add!")
            else:
                visible_reminders = reminders[self._tasks_scroll_offset : self._tasks_scroll_offset + 4]
                p.setFont(self._font_body)
                for row_idx, rem in enumerate(visible_reminders):
                    actual_idx = row_idx + self._tasks_scroll_offset
                    is_active = (actual_idx == self._selected_index)
                    color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
                    p.setPen(color)

                    val = evaluate_task_value(rem)
                    short_text = rem[:18] + "..." if len(rem) > 18 else rem
                    p.drawText(start_x, start_y + row_idx * line_h, f"{actual_idx + 1}. {short_text}")

                    p.setPen(QColor(255, 180, 220) if not is_active else QColor(255, 255, 0))
                    p.drawText(310, start_y + row_idx * line_h, f"+P$ {val}")

                    if is_active and self._soul_heart:
                        p.drawPixmap(start_x - 24, start_y + row_idx * line_h - 13, self._soul_heart)

                # Scroll indicators
                p.setFont(self._font_small)
                p.setPen(QColor(255, 255, 0))
                if self._tasks_scroll_offset > 0:
                    p.drawText(380, 275, "▲")
                if self._tasks_scroll_offset + 4 < len(reminders):
                    p.drawText(380, 425, "▼")
        else:
            alarms_items = self._get_alarms_menu_items()
            visible_alarms = alarms_items[self._alarms_scroll_offset : self._alarms_scroll_offset + 4]
            p.setFont(self._font_body)
            for row_idx, item in enumerate(visible_alarms):
                actual_idx = row_idx + self._alarms_scroll_offset
                is_active = (actual_idx == self._selected_index)
                color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
                p.setPen(color)

                lbl = item.get("label", "")
                if len(lbl) > 24:
                    lbl = lbl[:23] + "..."
                p.drawText(start_x, start_y + row_idx * line_h, lbl)

                if is_active and self._soul_heart:
                    p.drawPixmap(start_x - 24, start_y + row_idx * line_h - 13, self._soul_heart)

            # Scroll indicators
            p.setFont(self._font_small)
            p.setPen(QColor(255, 255, 0))
            if self._alarms_scroll_offset > 0:
                p.drawText(380, 275, "▲")
            if self._alarms_scroll_offset + 4 < len(alarms_items):
                p.drawText(380, 425, "▼")

        # Bottom-Right Wallet & Back
        p.setFont(self._font_body)
        p.setPen(QColor(255, 180, 220))
        p.drawText(430, 265, "Pink Dollars:")
        p.setPen(QColor(255, 255, 255))
        p.drawText(430, 295, f"P$ {self._wallet.pink_dollars:06d}")

        p.setFont(self._font_title)
        back_idx = self._get_menu_count() - 1
        is_back = (self._selected_index == back_idx)
        p.setPen(QColor(255, 255, 0) if is_back else QColor(255, 255, 255))
        p.drawText(450, 415, "Back")
        if is_back and self._soul_heart:
            p.drawPixmap(424, 401, self._soul_heart)

    def _draw_settings_and_facts_state(self, p: QPainter) -> None:
        # Sub-tab Headers: [ 1. EDIT FACTS ]   [ 2. TOGGLES ]
        p.setFont(self._font_title)
        tab0_active = (self._config_tab == 0)
        p.setPen(QColor(255, 255, 0) if tab0_active else QColor(160, 160, 190))
        p.drawText(35, 262, "[ 1. EDIT FACTS ]")

        p.setPen(QColor(255, 255, 0) if not tab0_active else QColor(160, 160, 190))
        p.drawText(205, 262, "[ 2. TOGGLES ]")

        # Top-Right Details Card
        if self._config_tab == 0:
            notes = self._get_fact_notes()
            if self._selected_index >= 2 and (self._selected_index - 2) < len(notes):
                note_idx = self._selected_index - 2
                full_note = notes[note_idx]
                p.setFont(self._font_title)
                p.setPen(QColor(170, 255, 230))
                p.drawText(426, 38, f"Fact Note #{note_idx + 1}")

                p.setFont(self._font_small)
                p.setPen(QColor(140, 206, 255))
                p.drawText(426, 60, "Permanent Memory")

                p.setPen(QColor(255, 255, 255))
                p.drawText(QRect(426, 75, 188, 140), Qt.AlignLeft | Qt.TextWordWrap, full_note)
            else:
                p.setFont(self._font_title)
                p.setPen(QColor(170, 255, 230))
                p.drawText(426, 38, "Fact Sheet")

                p.setFont(self._font_small)
                p.setPen(QColor(140, 206, 255))
                p.drawText(426, 60, f"User: {self._get_user_name()}")

                p.setPen(QColor(255, 255, 255))
                p.drawText(
                    QRect(426, 75, 188, 140),
                    Qt.AlignLeft | Qt.TextWordWrap,
                    f"Notes Stored: {len(notes)}\nScroll down to view every note! Pink permanently remembers them across all sessions.",
                )
        else:
            p.setFont(self._font_title)
            p.setPen(QColor(255, 255, 0))
            p.drawText(426, 38, "Toggles")

            p.setFont(self._font_small)
            p.setPen(QColor(140, 206, 255))
            p.drawText(426, 60, "Pet Configuration")

            p.setPen(QColor(255, 255, 255))
            p.drawText(
                QRect(426, 75, 188, 140),
                Qt.AlignLeft | Qt.TextWordWrap,
                "Toggle desktop companion features and autonomous behaviors on or off directly from here.",
            )

        # Bottom-Left Items List
        start_x = 44
        start_y = 295
        line_h = 36

        if self._config_tab == 0:
            facts_items = self._get_facts_menu_items()
            visible_items = facts_items[self._notes_scroll_offset : self._notes_scroll_offset + 4]
            p.setFont(self._font_body)
            for row_idx, opt in enumerate(visible_items):
                actual_idx = row_idx + self._notes_scroll_offset
                is_active = (actual_idx == self._selected_index)
                color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
                p.setPen(color)
                p.drawText(start_x, start_y + row_idx * line_h, opt)

                if is_active and self._soul_heart:
                    p.drawPixmap(start_x - 24, start_y + row_idx * line_h - 13, self._soul_heart)

            # Scroll indicators
            p.setFont(self._font_small)
            p.setPen(QColor(255, 255, 0))
            if self._notes_scroll_offset > 0:
                p.drawText(380, 275, "▲")
            if self._notes_scroll_offset + 4 < len(facts_items):
                p.drawText(380, 425, "▼")
        else:
            bubbles_on = getattr(self._pet, "_dialogue_enabled", True) if self._pet else True
            song_on = getattr(self._pet, "_ai_song_comment_enabled", True) if self._pet else True
            bomb_on = getattr(self._pet, "_bomb_attack_enabled", False) if self._pet else False
            jump_on = getattr(self._pet, "_jump_enabled", True) if self._pet else True

            toggles = [
                f"Dialogue Bubbles: [{'ON' if bubbles_on else 'OFF'}]",
                f"AI Song Commentary: [{'ON' if song_on else 'OFF'}]",
                f"Bomb Attack Mode: [{'ON' if bomb_on else 'OFF'}]",
                f"Jump to Cursor: [{'ON' if jump_on else 'OFF'}]",
            ]
            p.setFont(self._font_body)
            for row_idx, opt in enumerate(toggles):
                is_active = (row_idx == self._selected_index)
                color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
                p.setPen(color)
                p.drawText(start_x, start_y + row_idx * line_h, opt)

                if is_active and self._soul_heart:
                    p.drawPixmap(start_x - 24, start_y + row_idx * line_h - 13, self._soul_heart)

        # Bottom-Right Back
        p.setFont(self._font_title)
        back_idx = self._get_menu_count() - 1
        is_back = (self._selected_index == back_idx)
        p.setPen(QColor(255, 255, 0) if is_back else QColor(255, 255, 255))
        p.drawText(450, 415, "Back")
        if is_back and self._soul_heart:
            p.drawPixmap(424, 401, self._soul_heart)

    def _draw_task_confirm_state(self, p: QPainter) -> None:
        p.setFont(self._font_title)
        if self._sell_has_evidence:
            p.setPen(QColor(170, 255, 230))
            p.drawText(426, 38, "Verified Work! ✨")
            p.setFont(self._font_small)
            p.setPen(QColor(140, 206, 255))
            proof_type = "Screen Sight" if self._sell_saw_on_screen else "Session Logs"
            p.drawText(426, 60, f"Proof: {proof_type}")
            p.setPen(QColor(255, 255, 255))
            p.drawText(
                QRect(426, 75, 188, 140),
                Qt.AlignLeft | Qt.TextWordWrap,
                f"Pink confirmed proof of work on '{self._sell_evidence_kw}'!\nOne click to complete and collect your P$!",
            )
        else:
            p.setPen(QColor(255, 200, 80))
            p.drawText(426, 38, "Unverified Task ❓")
            p.setFont(self._font_small)
            p.setPen(QColor(255, 160, 100))
            p.drawText(426, 60, "Proof: Not Found")
            p.setPen(QColor(255, 255, 255))
            p.drawText(
                QRect(426, 75, 188, 140),
                Qt.AlignLeft | Qt.TextWordWrap,
                "Pink hasn't observed any evidence of this on your screen or in recent sessions...\nAre you sure you finished it?",
            )

        p.setFont(self._font_body)
        p.setPen(QColor(255, 255, 0))
        p.drawText(36, 265, "Task to Complete:")

        p.setPen(QColor(255, 255, 255))
        task_text = self._pending_sell_reminder or ""
        p.drawText(QRect(36, 290, 350, 140), Qt.AlignLeft | Qt.TextWordWrap, f"\"{task_text}\"")

        p.setFont(self._font_small)
        p.setPen(QColor(140, 206, 255))
        p.drawText(430, 265, f"Value: P$ {self._pending_sell_value}")

        options = [f"YES (+P$ {self._pending_sell_value})", "NO (Keep)"]
        start_x = 444
        start_y = 315
        line_h = 48

        p.setFont(self._font_title)
        for i, opt in enumerate(options):
            is_active = (i == self._selected_index)
            color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
            p.setPen(color)
            p.drawText(start_x, start_y + i * line_h, opt)

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

    def _draw_task_second_confirm_state(self, p: QPainter) -> None:
        p.setFont(self._font_title)
        p.setPen(QColor(255, 64, 64))
        p.drawText(426, 38, "SUSPICION ALERT!")

        p.setFont(self._font_small)
        p.setPen(QColor(255, 140, 140))
        p.drawText(426, 60, "Proof: NOT FOUND!")

        p.setPen(QColor(255, 255, 255))
        p.drawText(
            QRect(426, 75, 188, 140),
            Qt.AlignLeft | Qt.TextWordWrap,
            "Pink scanned your screen sight logs & session memories and found NO evidence of this work!\nAre you double-dog sure?!",
        )

        p.setFont(self._font_body)
        p.setPen(QColor(255, 64, 64))
        p.drawText(36, 265, "Unverified Task Claim:")

        p.setPen(QColor(255, 255, 255))
        task_text = self._pending_sell_reminder or ""
        p.drawText(QRect(36, 290, 350, 90), Qt.AlignLeft | Qt.TextWordWrap, f"\"{task_text}\"")

        p.setFont(self._font_small)
        p.setPen(QColor(255, 140, 140))
        p.drawText(36, 410, "* Pink's Verdict: Highly Suspicious!")

        p.setFont(self._font_small)
        p.setPen(QColor(255, 64, 64))
        p.drawText(430, 265, "FINAL CHANCE:")

        options = ["I REALLY DID!", "...CAUGHT ME"]
        start_x = 444
        start_y = 315
        line_h = 48

        p.setFont(self._font_title)
        for i, opt in enumerate(options):
            is_active = (i == self._selected_index)
            color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
            p.setPen(color)
            p.drawText(start_x, start_y + i * line_h, opt)

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

    def _draw_talk_state(self, p: QPainter) -> None:
        if self.state == ShopState.TALK_MENU:
            p.setFont(self._font_title)

            start_x1 = 50
            start_x2 = 340
            start_y = 280
            line_h = 44

            for i, (topic_title, _) in enumerate(TALK_TOPICS):
                is_active = (i == self._selected_index)
                color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
                p.setPen(color)

                x = start_x1 if i % 2 == 0 else start_x2
                y = start_y + (i // 2) * line_h
                p.drawText(x, y, topic_title)

                if is_active and self._soul_heart:
                    p.drawPixmap(x - 24, y - 13, self._soul_heart)

        elif self.state == ShopState.TALK_DIALOGUE:
            self._draw_dialogue_text(p, QRect(36, 250, 568, 175))
            p.setFont(self._font_small)
            p.setPen(QColor(157, 162, 196))
            p.drawText(530, 435, "[Z / Esc]")
