"""Pink's Dark World Sanctuary (formerly Shop Window) for Yellow's Pixel Buddies.

Comprehensive Feature Set:
1. Tasks & Alarms (4 Tab Menu):
   - GOALS: Long-term personal milestones, [+ Add New Goal], completion awards bonus P$ 5, delete goal.
   - TASKS: Chores & reminders, [+ Add New Task], proof-of-work screen/session verification, cash in for P$ 1 - P$ 3.
   - ALARMS: Scheduled clock alarms (e.g. 08:00 AM), [+ Set Clock Alarm], cancel controls.
   - TIMERS: Countdown focus timers (5m, 15m, 25m Pomodoro, custom countdown), active timer tracking with live remaining time, stop controls.
2. Item Action & Inspection Dialogue:
   - Clicking an item or top-right card opens an interactive dialogue box with full item text and actionable options.
   - Actionable choices for tasks (Complete, Delete, Back), goals (Complete, Delete, Back), alarms (Cancel, Back), timers (Stop, Back), and facts (Delete, Back).
   - Card helper hint: "▶ Click item or card for options".
3. Config & Settings (Menu System):
   - Vertical Undertale menu: "1. Edit Facts & Nickname", "2. Companion Toggles", "3. Back".
   - Edit Facts: Nickname editor, [+ Add New Fact Note], scrollable list of all permanent notes, action dialogue to delete notes.
   - Toggles: Live toggles for Dialogue Bubbles, AI Song Commentary, Bomb Attack, and Jump to Cursor (persisted immediately to config.json).
4. Wardrobe / Characters:
   - Classic Doll is equipped. Other forms marked "COMING SOON" with in-character dialogue ("Pink is still tailoring that form!").
5. Exit Pacing:
   - Selecting Exit delivers Pink's canon goodbye line without auto-closing; user must click again or press Enter/Z to really exit.
6. Universal Scrolling & Seamless Mouse Interaction:
   - Mouse wheel scrolling on all scrollable menus with visual scroll indicators (▲ and ▼).
   - Single-click activation on all menus, tabs, and action choices.
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
if not DETERMINATION_FONT_PATH.exists():
    DETERMINATION_FONT_PATH = _BASE_DIR / "fonts" / "determination.ttf"
WALLET_PATH = _BASE_DIR / "memory" / "wallet.json"
FACTS_PATH = _BASE_DIR / "memory" / "facts.json"
GOALS_PATH = _BASE_DIR / "memory" / "goals.json"

# Native canvas dimensions
CANVAS_W = 640
CANVAS_H = 480
SCENE_NATIVE_W = 320
SCENE_NATIVE_H = 120
SCENE_RENDER_H = 240

# Timing configuration
SCENE_FRAME_INTERVAL_MS = 250
TYPEWRITER_INTERVAL_MS = 28


class ShopState(Enum):
    ROOT = auto()
    CHARACTER = auto()            # Wardrobe (Coming soon)
    TASKS = auto()                # Tasks & Alarms (4 tabs: GOALS, TASKS, ALARMS, TIMERS)
    SETTINGS_MENU = auto()        # Config & Settings (Menu: 1. Edit Facts, 2. Toggles, 3. Back)
    FACTS_EDIT = auto()           # Facts & Notes editor
    TOGGLES_MENU = auto()         # Companion Toggles (Live)
    ITEM_ACTION = auto()          # Interactive inspection dialogue & choices
    TASK_CONFIRM = auto()         # Stage 1 verification
    TASK_SECOND_CONFIRM = auto()  # Stage 2 suspicion confirmation
    TALK_MENU = auto()            # Serious topics (8 items: 7 canon + Back)
    TALK_DIALOGUE = auto()        # Serious typewriter dialogue
    EXITING = auto()              # Goodbye dialogue, requires second click to exit


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


# --- Character Forms (Classic Doll active; others COMING SOON) -----------------
CHARACTER_FORMS = [
    {
        "id": "doll",
        "name": "Classic Doll (Pink)",
        "cost": 0,
        "anim": "idle",
        "desc": "The quintessential cotton Mew Mew doll body. The ONE and ONLY active character in this world!",
        "status": "EQUIPPED",
    },
    {
        "id": "ghost",
        "name": "Spectral Ghost",
        "cost": 0,
        "anim": "angry",
        "desc": "Coming soon! Pink is tailoring her incorporeal spirit form with glowing cyan aura and spectral embers.",
        "status": "COMING SOON",
    },
    {
        "id": "burnt",
        "name": "Burnt Survivor",
        "cost": 0,
        "anim": "burnt",
        "desc": "Coming soon! Battle-hardened, soot-covered survivor doll form. Still undergoing fireproofing tests!",
        "status": "COMING SOON",
    },
    {
        "id": "overjoyed",
        "name": "Cyber Joy",
        "cost": 0,
        "anim": "overjoyed",
        "desc": "Coming soon! Pure cyber bliss and celebratory peace-sign animations in tailoring development.",
        "status": "COMING SOON",
    },
]

# --- Canon Deltarune Shop Dialogues --------------------------------------------
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
CANON_BUY_COMING_SOON = "* Coming soon, minion! Pink is still tailoring that form!"
CANON_TALK_ENTER = "* I guess... we could talk."

TALK_TOPICS = [
    ("What is this place?", "place"),
    ("What's your name?", "name"),
    ("Human ears?", "ears"),
    ("Other people?", "people"),
    ("Graduating", "graduating"),
    ("The Cat Bite", "egg"),
    ("Ask Pink a Question", "ai_ask"),
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

        # 4 Tabs in TASKS state: 0 = Goals, 1 = Tasks, 2 = Alarms, 3 = Timers
        self._tasks_tab: int = 1

        # Scroll offsets
        self._goals_scroll_offset: int = 0
        self._tasks_scroll_offset: int = 0
        self._alarms_scroll_offset: int = 0
        self._timers_scroll_offset: int = 0
        self._notes_scroll_offset: int = 0

        # Item Action / Inspector state
        self._inspect_item_kind: str = ""   # "goal", "task", "alarm", "timer", "fact"
        self._inspect_item_text: str = ""
        self._inspect_item_data: Any = None
        self._inspect_options: list[str] = []
        self._inspect_choice_idx: int = 0

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

        self._input_mode: str = ""  # "fact_name", "fact_note", "new_goal", "new_task", "new_alarm", "custom_timer", "ai_ask"

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

        HUD_Y_OFFSET = 21
        self._bg_cache = {"root": [], "buy": [], "talk": []}
        for key in ("root", "buy", "talk"):
            hud = huds[key]
            for scene in scenes:
                composite = QPixmap(CANVAS_W, CANVAS_H)
                composite.fill(QColor(0, 0, 0, 255))
                p = QPainter(composite)
                # Draw scene scaled 640x240 at (0, 0) - full 240px uncropped
                p.drawPixmap(0, 0, scene)
                # Draw HUD at y=21 so transparent window fits scene and HUD box begins at y=240
                p.drawPixmap(0, HUD_Y_OFFSET, hud)
                p.end()
                self._bg_cache[key].append(composite)

    # --- Lifecycle & Dialogue --------------------------------------------------

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
        self._tasks_tab = 1
        self._goals_scroll_offset = 0
        self._tasks_scroll_offset = 0
        self._alarms_scroll_offset = 0
        self._timers_scroll_offset = 0
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
            return 12 <= pt.x() <= 403 and 248 <= pt.y() <= 472
        elif self.state == ShopState.TALK_DIALOGUE:
            return 12 <= pt.x() <= 628 and 248 <= pt.y() <= 472
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

    # --- Goals, Facts, Tasks & Alarms Model ------------------------------------

    def _get_goals_file_path(self) -> Path:
        if hasattr(self, "_memory") and self._memory and hasattr(self._memory, "memory_dir"):
            return self._memory.memory_dir / "goals.json"
        return GOALS_PATH

    def _get_goals(self) -> list[str]:
        p = self._get_goals_file_path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return [g.get("text", "") if isinstance(g, dict) else str(g) for g in data if g]
            except Exception as e:
                log.warning("Could not read goals from %s: %s", p, e)
        return []

    def _add_goal(self, text: str) -> bool:
        text = text.strip()
        if not text:
            return False
        goals = self._get_goals()
        if text not in goals:
            goals.append(text)
            p = self._get_goals_file_path()
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps([{"text": g, "completed": False} for g in goals], indent=2), encoding="utf-8")
                return True
            except Exception as e:
                log.warning("Could not save goals: %s", e)
        return False

    def _delete_goal(self, text: str) -> bool:
        goals = self._get_goals()
        if text in goals:
            goals.remove(text)
            p = self._get_goals_file_path()
            try:
                p.write_text(json.dumps([{"text": g, "completed": False} for g in goals], indent=2), encoding="utf-8")
                return True
            except Exception as e:
                log.warning("Could not delete goal: %s", e)
        return False

    def _complete_goal(self, text: str) -> None:
        if self._delete_goal(text):
            self._wallet.add(5)
            self.set_dialogue(
                f"* TARGET MILESTONE CONQUERED!!\n* You finished: \"{text}\"!\n* Pink awards you a grand bonus of +P$ 000005!"
            )
        else:
            self.set_dialogue("* Couldn't find that goal, silly!")

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

    def _delete_fact_note(self, note_text: str) -> bool:
        notes = self._get_fact_notes()
        if note_text in notes:
            notes.remove(note_text)
            p = self._get_facts_file_path()
            try:
                data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
                data["notes"] = notes
                p.write_text(json.dumps(data, indent=2), encoding="utf-8")
                return True
            except Exception as e:
                log.warning("Could not delete fact note: %s", e)
        return False

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

    def _get_scheduled_alarms(self) -> list[dict[str, Any]]:
        """Return only scheduled clock alarms (kind == 'alarm')."""
        active = self._get_active_alarms_list()
        return [a for a in active if a.get("kind") == "alarm" and a.get("state") == "active"]

    def _get_active_timers(self) -> list[dict[str, Any]]:
        """Return active countdown timers (kind == 'timer')."""
        active = self._get_active_alarms_list()
        return [a for a in active if a.get("kind") == "timer" and a.get("state") == "active"]

    # --- Item Action / Inspector Mode -----------------------------------------

    def _open_item_action(self, kind: str, text: str, data: Any = None) -> None:
        self._inspect_item_kind = kind
        self._inspect_item_text = text
        self._inspect_item_data = data
        self._inspect_choice_idx = 0
        self.state = ShopState.ITEM_ACTION

        if kind == "goal":
            self._inspect_options = ["Complete (+P$ 5)", "Delete Goal", "Back"]
            self.set_dialogue(f"* Target Milestone:\n* \"{text}\"\n* Ready to mark it completed or remove it?")
        elif kind == "task":
            val = evaluate_task_value(text)
            self._inspect_options = [f"Complete (+P$ {val})", "Delete Task", "Back"]
            self.set_dialogue(f"* Task on Board:\n* \"{text}\"\n* Ready to verify and collect P$ {val}?")
        elif kind == "alarm":
            self._inspect_options = ["Cancel / Delete Alarm", "Back"]
            time_str = data.get("clock_time", "Scheduled") if isinstance(data, dict) else ""
            lbl = data.get("label", text) if isinstance(data, dict) else text
            self.set_dialogue(f"* Clock Alarm [{time_str}]:\n* \"{lbl}\"\n* Want Pink to cancel this alarm?")
        elif kind == "timer":
            self._inspect_options = ["Stop / Cancel Timer", "Back"]
            self.set_dialogue(f"* Countdown Timer:\n* \"{text}\"\n* Stop this focus interval?")
        elif kind == "fact":
            self._inspect_options = ["Delete Fact Note", "Back"]
            self.set_dialogue(f"* Permanent Fact Note:\n* \"{text}\"\n* Inscribed in Pink's memory core.")

    def _confirm_item_action(self) -> None:
        opt = self._inspect_options[self._inspect_choice_idx] if self._inspect_choice_idx < len(self._inspect_options) else "Back"

        if self._inspect_item_kind == "goal":
            if opt.startswith("Complete"):
                self._complete_goal(self._inspect_item_text)
                self.state = ShopState.TASKS
                self._tasks_tab = 0
                self._selected_index = 0
            elif opt.startswith("Delete"):
                self._delete_goal(self._inspect_item_text)
                self.set_dialogue(f"* Goal discarded:\n* \"{self._inspect_item_text}\"")
                self.state = ShopState.TASKS
                self._tasks_tab = 0
                self._selected_index = 0
            else:  # Back
                self.state = ShopState.TASKS
                self._tasks_tab = 0
                self.set_dialogue("* Back to goals.")

        elif self._inspect_item_kind == "task":
            if opt.startswith("Complete"):
                task_text = self._inspect_item_text
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
            elif opt.startswith("Delete"):
                if self._memory:
                    self._memory.delete_reminder(self._inspect_item_text)
                self.set_dialogue(f"* Task removed from chore board:\n* \"{self._inspect_item_text}\"")
                self.state = ShopState.TASKS
                self._tasks_tab = 1
                self._selected_index = 0
            else:  # Back
                self.state = ShopState.TASKS
                self._tasks_tab = 1
                self.set_dialogue("* Back to chores.")

        elif self._inspect_item_kind == "alarm":
            if opt.startswith("Cancel"):
                target = self._inspect_item_data.get("id") or self._inspect_item_text if isinstance(self._inspect_item_data, dict) else self._inspect_item_text
                mem = self._memory or (self._pet._memory if self._pet and hasattr(self._pet, "_memory") else None)
                if mem and hasattr(mem, "cancel_alarm_or_timer"):
                    mem.cancel_alarm_or_timer(target)
                self.set_dialogue(f"* Alarm cancelled:\n* \"{self._inspect_item_text}\"")
                self.state = ShopState.TASKS
                self._tasks_tab = 2
                self._selected_index = 0
            else:
                self.state = ShopState.TASKS
                self._tasks_tab = 2
                self.set_dialogue("* Back to alarms.")

        elif self._inspect_item_kind == "timer":
            if opt.startswith("Stop"):
                if isinstance(self._inspect_item_data, str) and self._inspect_item_data == "active_shop":
                    self.stop_timer()
                else:
                    target = self._inspect_item_data.get("id") if isinstance(self._inspect_item_data, dict) else self._inspect_item_text
                    mem = self._memory or (self._pet._memory if self._pet and hasattr(self._pet, "_memory") else None)
                    if mem and hasattr(mem, "cancel_alarm_or_timer"):
                        mem.cancel_alarm_or_timer(target)
                self.set_dialogue("* Active timer stopped, darling.")
                self.state = ShopState.TASKS
                self._tasks_tab = 3
                self._selected_index = 0
            else:
                self.state = ShopState.TASKS
                self._tasks_tab = 3
                self.set_dialogue("* Back to timers.")

        elif self._inspect_item_kind == "fact":
            if opt.startswith("Delete"):
                self._delete_fact_note(self._inspect_item_text)
                self.set_dialogue(f"* Fact note expunged from memory:\n* \"{self._inspect_item_text}\"")
                self.state = ShopState.FACTS_EDIT
                self._selected_index = 0
            else:
                self.state = ShopState.FACTS_EDIT
                self.set_dialogue("* Back to fact sheet.")

        self.update()

    # --- Universal Scrolling & Navigation --------------------------------------

    def _scroll_up(self) -> None:
        if self.state == ShopState.TASKS:
            if self._tasks_tab == 0:
                self._goals_scroll_offset = max(0, self._goals_scroll_offset - 1)
            elif self._tasks_tab == 1:
                self._tasks_scroll_offset = max(0, self._tasks_scroll_offset - 1)
            elif self._tasks_tab == 2:
                self._alarms_scroll_offset = max(0, self._alarms_scroll_offset - 1)
            elif self._tasks_tab == 3:
                self._timers_scroll_offset = max(0, self._timers_scroll_offset - 1)
        elif self.state == ShopState.FACTS_EDIT:
            self._notes_scroll_offset = max(0, self._notes_scroll_offset - 1)
        self.update()

    def _scroll_down(self) -> None:
        if self.state == ShopState.TASKS:
            if self._tasks_tab == 0:
                max_off = max(0, len(self._get_goals()) + 1 - 4)
                self._goals_scroll_offset = min(max_off, self._goals_scroll_offset + 1)
            elif self._tasks_tab == 1:
                max_off = max(0, len(self._get_active_reminders()) + 1 - 4)
                self._tasks_scroll_offset = min(max_off, self._tasks_scroll_offset + 1)
            elif self._tasks_tab == 2:
                max_off = max(0, len(self._get_scheduled_alarms()) + 1 - 4)
                self._alarms_scroll_offset = min(max_off, self._alarms_scroll_offset + 1)
            elif self._tasks_tab == 3:
                max_off = max(0, len(self._get_timers_menu_items()) - 4)
                self._timers_scroll_offset = min(max_off, self._timers_scroll_offset + 1)
        elif self.state == ShopState.FACTS_EDIT:
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
        elif self.state == ShopState.ITEM_ACTION:
            self._inspect_choice_idx = (self._inspect_choice_idx - 1) % len(self._inspect_options)
            self._selected_index = self._inspect_choice_idx
            self.update()
            return
        else:
            self._selected_index = (self._selected_index - 1) % count

        # Auto-scroll viewport
        if self.state == ShopState.TASKS:
            offset_attr = [
                "_goals_scroll_offset",
                "_tasks_scroll_offset",
                "_alarms_scroll_offset",
                "_timers_scroll_offset",
            ][self._tasks_tab]
            cur_off = getattr(self, offset_attr)
            if self._selected_index < cur_off:
                setattr(self, offset_attr, self._selected_index)
            elif self._selected_index >= cur_off + 4:
                setattr(self, offset_attr, max(0, self._selected_index - 3))
        elif self.state == ShopState.FACTS_EDIT:
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
        elif self.state == ShopState.ITEM_ACTION:
            self._inspect_choice_idx = (self._inspect_choice_idx + 1) % len(self._inspect_options)
            self._selected_index = self._inspect_choice_idx
            self.update()
            return
        else:
            self._selected_index = (self._selected_index + 1) % count

        # Auto-scroll viewport
        if self.state == ShopState.TASKS:
            offset_attr = [
                "_goals_scroll_offset",
                "_tasks_scroll_offset",
                "_alarms_scroll_offset",
                "_timers_scroll_offset",
            ][self._tasks_tab]
            cur_off = getattr(self, offset_attr)
            if self._selected_index < cur_off:
                setattr(self, offset_attr, self._selected_index)
            elif self._selected_index >= cur_off + 4:
                setattr(self, offset_attr, max(0, self._selected_index - 3))
        elif self.state == ShopState.FACTS_EDIT:
            if self._selected_index < self._notes_scroll_offset:
                self._notes_scroll_offset = self._selected_index
            elif self._selected_index >= self._notes_scroll_offset + 4:
                self._notes_scroll_offset = max(0, self._selected_index - 3)

        self._on_selection_changed()
        self.update()

    def _get_menu_count(self) -> int:
        if self.state == ShopState.ROOT:
            return 5  # CHARACTER, TASKS & ALARMS, TALK, CONFIG & SETTINGS, EXIT
        elif self.state == ShopState.CHARACTER:
            return len(CHARACTER_FORMS) + 1  # Forms + Back
        elif self.state == ShopState.TASKS:
            if self._tasks_tab == 0:
                return len(self._get_goals()) + 2  # [+ Add Goal] + Goals + Back
            elif self._tasks_tab == 1:
                return len(self._get_active_reminders()) + 2  # [+ Add Task] + Tasks + Back
            elif self._tasks_tab == 2:
                return len(self._get_scheduled_alarms()) + 2  # [+ Set Alarm] + Alarms + Back
            elif self._tasks_tab == 3:
                return len(self._get_timers_menu_items()) + 1  # Presets/timers + Back
        elif self.state == ShopState.SETTINGS_MENU:
            return 3  # 1. Edit Facts, 2. Toggles, 3. Back
        elif self.state == ShopState.FACTS_EDIT:
            return len(self._get_facts_menu_items()) + 1  # Facts + Back
        elif self.state == ShopState.TOGGLES_MENU:
            return 5  # 4 toggles + Back
        elif self.state == ShopState.ITEM_ACTION:
            return len(self._inspect_options)
        elif self.state in (ShopState.TASK_CONFIRM, ShopState.TASK_SECOND_CONFIRM):
            return 2  # YES, NO
        elif self.state == ShopState.TALK_MENU:
            return len(TALK_TOPICS)  # 8 items
        return 0

    def _get_timers_menu_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = [
            {"kind": "preset", "mins": 5, "label": "Start 5m Short Break"},
            {"kind": "preset", "mins": 15, "label": "Start 15m Sprint Focus"},
            {"kind": "preset", "mins": 25, "label": "Start 25m Pomodoro Focus"},
            {"kind": "custom", "label": "Custom Countdown Timer..."},
        ]
        if self._timer_active and self._timer_seconds_remaining > 0:
            m, s = divmod(self._timer_seconds_remaining, 60)
            items.append({
                "kind": "active_shop",
                "label": f"[Active] {self._timer_label} ({m:02d}:{s:02d})",
            })
        for t in self._get_active_timers():
            tgt = t.get("target_timestamp", 0)
            rem = max(0, int(tgt - time.time()))
            m, s = divmod(rem, 60)
            items.append({
                "kind": "active_memory",
                "target": t.get("id") or t.get("label"),
                "label": f"[Active] {t.get('label', 'Timer')} ({m:02d}:{s:02d})",
                "data": t,
            })
        if len(items) > 4:
            items.append({"kind": "stop_all", "label": "Stop All Active Timers"})
        return items

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

    def _on_selection_changed(self) -> None:
        if self.state == ShopState.CHARACTER:
            if self._selected_index < len(CHARACTER_FORMS):
                f = CHARACTER_FORMS[self._selected_index]
                if f.get("status") == "COMING SOON":
                    self.set_dialogue(f"* {f['name']}: Coming soon, minion! Pink is tailoring it!")
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

        elif self.state == ShopState.FACTS_EDIT:
            notes = self._get_fact_notes()
            if self._selected_index >= 2 and (self._selected_index - 2) < len(notes):
                full_note = notes[self._selected_index - 2]
                self.set_dialogue(f"* Fact Note #{self._selected_index - 1}:\n* \"{full_note}\"")

    def _confirm_selection(self) -> None:
        if self.state == ShopState.ROOT:
            if self._selected_index == 0:  # CHARACTER
                self.state = ShopState.CHARACTER
                self._selected_index = 0
                self.set_dialogue("* Pink's Wardrobe! Other styles are coming soon, darling!")
            elif self._selected_index == 1:  # TASKS & ALARMS
                self.state = ShopState.TASKS
                self._tasks_tab = 1
                self._selected_index = 0
                self.set_dialogue("* Tasks, Goals, Timers & Alarms command center!")
            elif self._selected_index == 2:  # TALK
                self.state = ShopState.TALK_MENU
                self._selected_index = 0
                self.set_dialogue(CANON_TALK_ENTER)
            elif self._selected_index == 3:  # CONFIG & SETTINGS
                self.state = ShopState.SETTINGS_MENU
                self._selected_index = 0
                self.set_dialogue("* Sanctuary settings & permanent memory fact sheet.")
            elif self._selected_index == 4:  # EXIT
                self._start_exit()

        elif self.state == ShopState.CHARACTER:
            if self._selected_index < len(CHARACTER_FORMS):
                f = CHARACTER_FORMS[self._selected_index]
                if f.get("status") == "COMING SOON":
                    self.set_dialogue(CANON_BUY_COMING_SOON)
                else:
                    self.set_dialogue("* Already equipped, darling! You look magnificent!")
            else:
                self.state = ShopState.ROOT
                self._selected_index = 0
                self.set_dialogue(self._get_root_greeting())

        elif self.state == ShopState.TASKS:
            if self._tasks_tab == 0:  # GOALS
                goals = self._get_goals()
                if self._selected_index == 0:
                    self._prompt_add_goal()
                elif self._selected_index <= len(goals):
                    goal_text = goals[self._selected_index - 1]
                    self._open_item_action("goal", goal_text)
                else:  # Back
                    self.state = ShopState.ROOT
                    self._selected_index = 1
                    self.set_dialogue(self._get_root_greeting())

            elif self._tasks_tab == 1:  # TASKS
                reminders = self._get_active_reminders()
                if self._selected_index == 0:
                    self._prompt_add_task()
                elif self._selected_index <= len(reminders):
                    task_text = reminders[self._selected_index - 1]
                    self._open_item_action("task", task_text)
                else:  # Back
                    self.state = ShopState.ROOT
                    self._selected_index = 1
                    self.set_dialogue(self._get_root_greeting())

            elif self._tasks_tab == 2:  # ALARMS
                alarms = self._get_scheduled_alarms()
                if self._selected_index == 0:
                    self._prompt_add_alarm()
                elif self._selected_index <= len(alarms):
                    alarm_item = alarms[self._selected_index - 1]
                    lbl = alarm_item.get("label", "Alarm")
                    self._open_item_action("alarm", lbl, alarm_item)
                else:  # Back
                    self.state = ShopState.ROOT
                    self._selected_index = 1
                    self.set_dialogue(self._get_root_greeting())

            elif self._tasks_tab == 3:  # TIMERS
                items = self._get_timers_menu_items()
                if self._selected_index < len(items):
                    it = items[self._selected_index]
                    kind = it.get("kind")
                    if kind == "preset":
                        self.start_timer(it.get("mins", 5), it.get("label"))
                    elif kind == "custom":
                        self._prompt_custom_timer()
                    elif kind in ("active_shop", "active_memory"):
                        lbl = it.get("label", "Timer")
                        self._open_item_action("timer", lbl, it.get("data") or kind)
                    elif kind == "stop_all":
                        mem = self._memory or (self._pet._memory if self._pet and hasattr(self._pet, "_memory") else None)
                        if mem and hasattr(mem, "clear_all_alarms"):
                            mem.clear_all_alarms()
                        self.stop_timer()
                        self.set_dialogue("* All active timers halted, minion!")
                else:  # Back
                    self.state = ShopState.ROOT
                    self._selected_index = 1
                    self.set_dialogue(self._get_root_greeting())

        elif self.state == ShopState.SETTINGS_MENU:
            if self._selected_index == 0:  # Edit Facts
                self.state = ShopState.FACTS_EDIT
                self._selected_index = 0
                self._notes_scroll_offset = 0
                self.set_dialogue("* Permanent memory fact sheet & nickname manager.")
            elif self._selected_index == 1:  # Companion Toggles
                self.state = ShopState.TOGGLES_MENU
                self._selected_index = 0
                self.set_dialogue("* Toggle companion autonomous behaviors in real time.")
            else:  # Back
                self.state = ShopState.ROOT
                self._selected_index = 3
                self.set_dialogue(self._get_root_greeting())

        elif self.state == ShopState.FACTS_EDIT:
            items = self._get_facts_menu_items()
            if self._selected_index == 0:  # Edit Nickname
                self._prompt_change_nickname()
            elif self._selected_index == 1:  # Add New Note
                self._prompt_add_fact()
            elif self._selected_index < len(items):  # Note inspect
                note_idx = self._selected_index - 2
                notes = self._get_fact_notes()
                if 0 <= note_idx < len(notes):
                    self._open_item_action("fact", notes[note_idx])
            else:  # Back
                self.state = ShopState.SETTINGS_MENU
                self._selected_index = 0
                self.set_dialogue("* Back to sanctuary settings.")

        elif self.state == ShopState.TOGGLES_MENU:
            if self._selected_index == 0:  # Dialogue Bubbles
                if self._pet:
                    new_val = not getattr(self._pet, "_dialogue_enabled", True)
                    self._pet._toggle_dialogue(new_val)
                    state_str = "ENABLED" if new_val else "DISABLED"
                    self.set_dialogue(f"* Dialogue bubbles are now {state_str}, mew!")
            elif self._selected_index == 1:  # Song Commentary
                if self._pet:
                    new_val = not getattr(self._pet, "_ai_song_comment_enabled", True)
                    self._pet._ai_song_comment_enabled = new_val
                    if hasattr(self._pet, "_save_live_settings"):
                        self._pet._save_live_settings()
                    state_str = "ENABLED" if new_val else "DISABLED"
                    self.set_dialogue(f"* Autonomous song reactions are now {state_str}, darling!")
            elif self._selected_index == 2:  # Bomb Mode
                if self._pet:
                    new_val = not getattr(self._pet, "_bomb_attack_enabled", False)
                    self._pet._toggle_bomb_attack(new_val)
                    state_str = "ARMED" if new_val else "DISARMED"
                    self.set_dialogue(f"* Cat-head bombs are now {state_str}, mew!")
            elif self._selected_index == 3:  # Jump Mode
                if self._pet:
                    new_val = not getattr(self._pet, "_jump_enabled", True)
                    self._pet._toggle_jump_mode(new_val)
                    state_str = "ENABLED" if new_val else "DISABLED"
                    self.set_dialogue(f"* Jump-to-cursor is now {state_str}, minion!")
            else:  # Back
                self.state = ShopState.SETTINGS_MENU
                self._selected_index = 1
                self.set_dialogue("* Back to sanctuary settings.")

        elif self.state == ShopState.ITEM_ACTION:
            self._confirm_item_action()

        elif self.state == ShopState.TASK_CONFIRM:
            if self._selected_index == 0:
                if self._sell_has_evidence:
                    if self._pending_sell_reminder:
                        self._complete_reminder(self._pending_sell_reminder, self._pending_sell_value)
                        self._pending_sell_reminder = None
                    self.state = ShopState.TASKS
                    self._tasks_tab = 1
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
                self._tasks_tab = 1
                self._selected_index = 0
                self.set_dialogue(CANON_SELL_REFUSE)

        elif self.state == ShopState.TASK_SECOND_CONFIRM:
            if self._selected_index == 0:
                if self._pending_sell_reminder:
                    self._complete_reminder(self._pending_sell_reminder, self._pending_sell_value)
                    self._pending_sell_reminder = None
                self.state = ShopState.TASKS
                self._tasks_tab = 1
                self._selected_index = 0
                self.set_dialogue(
                    f"{CANON_SELL_SUCCESS}\n* ... Hmph! I'll take your word for it this ONCE! (+P$ {self._pending_sell_value})"
                )
            else:
                self._pending_sell_reminder = None
                self.state = ShopState.TASKS
                self._tasks_tab = 1
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

        self.update()

    def _cancel_or_back(self) -> None:
        if self._input_container.isVisible():
            self._on_input_cancelled()
            return
        if self.state in (ShopState.CHARACTER, ShopState.TASKS, ShopState.SETTINGS_MENU, ShopState.TALK_MENU):
            self.state = ShopState.ROOT
            self._selected_index = 0
            self.set_dialogue(self._get_root_greeting())
        elif self.state in (ShopState.FACTS_EDIT, ShopState.TOGGLES_MENU):
            self.state = ShopState.SETTINGS_MENU
            self._selected_index = 0
            self.set_dialogue("* Sanctuary settings.")
        elif self.state == ShopState.ITEM_ACTION:
            if self._inspect_item_kind in ("goal", "task", "alarm", "timer"):
                self.state = ShopState.TASKS
            else:
                self.state = ShopState.FACTS_EDIT
            self.set_dialogue("* Back.")
        elif self.state in (ShopState.TASK_CONFIRM, ShopState.TASK_SECOND_CONFIRM):
            self.state = ShopState.TASKS
            self._tasks_tab = 1
            self._selected_index = 0
            self.set_dialogue(CANON_SELL_REFUSE)
        elif self.state == ShopState.TALK_DIALOGUE:
            self.state = ShopState.TALK_MENU
            self.set_dialogue(CANON_TALK_ENTER)
        elif self.state == ShopState.ROOT:
            self._start_exit()
        elif self.state == ShopState.EXITING:
            if self._is_typing():
                self._finish_typing()
            else:
                self.close_shop()
        self.update()

    def _start_exit(self) -> None:
        """Deliver Pink's canon exit dialogue. The user must click again or press Enter/Z to exit."""
        self.state = ShopState.EXITING
        self.set_dialogue(self._get_exit_line())

    # --- Prompt Input Helpers --------------------------------------------------

    def _prompt_change_nickname(self) -> None:
        self._input_mode = "fact_name"
        self._show_input_bar(f"Enter your new nickname (current: {self._get_user_name()}):")

    def _prompt_add_fact(self) -> None:
        self._input_mode = "fact_note"
        self._show_input_bar("Enter a new fact note for Pink to permanently remember:")

    def _prompt_add_goal(self) -> None:
        self._input_mode = "new_goal"
        self._show_input_bar("Enter a personal goal or milestone objective:")

    def _prompt_add_task(self) -> None:
        self._input_mode = "new_task"
        self._show_input_bar("Enter a new task or chore to complete for Pink Dollars:")

    def _prompt_add_alarm(self) -> None:
        self._input_mode = "new_alarm"
        self._show_input_bar("Enter alarm time and reason (e.g. 08:30 AM Team Sync):")

    def _prompt_custom_timer(self) -> None:
        self._input_mode = "custom_timer"
        self._show_input_bar("Enter timer length in minutes (e.g. 10 or 45):")

    def _prompt_serious_inquiry(self) -> None:
        self._input_mode = "ai_ask"
        self._show_input_bar("Ask Pink a question:")

    def _show_input_bar(self, prompt: str) -> None:
        self.set_dialogue(f"* {prompt}")
        scaled_w = round(CANVAS_W * self._scale)
        input_w = round(590 * self._scale)
        input_h = round(38 * self._scale)
        input_x = (scaled_w - input_w) // 2
        input_y = round(401 * self._scale)
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
        elif self._input_mode == "new_goal":
            self._add_goal(val)
            self.set_dialogue(f"* New target milestone logged:\n* \"{val}\"\n* Complete it to collect +P$ 000005!")
        elif self._input_mode == "new_task":
            if self._memory:
                self._memory.add_reminder(val)
            self.set_dialogue(f"* Task registered to chore board:\n* \"{val}\"\n* Finish it for Pink Dollars!")
        elif self._input_mode == "new_alarm":
            parts = val.split(" ", 1)
            time_str = parts[0].strip()
            lbl = parts[1].strip() if len(parts) > 1 else "Alarm"
            mem = self._memory or (self._pet._memory if self._pet and hasattr(self._pet, "_memory") else None)
            if mem and hasattr(mem, "add_alarm"):
                item = mem.add_alarm(time_str, lbl)
                if item:
                    self.set_dialogue(f"* Clock alarm primed for {item.get('clock_time')} (\"{lbl}\")!")
                else:
                    self.set_dialogue("* Format error: Use e.g. 08:30 AM Meeting, dummy!")
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

        # Exit mode: any key exits or finishes typing
        if self.state == ShopState.EXITING:
            if self._is_typing():
                self._finish_typing()
            else:
                self.close_shop()
            return

        # Sub-tab switching in TASKS via Tab key
        if key == Qt.Key_Tab and self.state == ShopState.TASKS:
            self._tasks_tab = (self._tasks_tab + 1) % 4
            self._selected_index = 0
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
            elif self.state == ShopState.TASKS:
                self._tasks_tab = (self._tasks_tab - 1) % 4
                self._selected_index = 0
                self.update()
        elif key in (Qt.Key_Right, Qt.Key_D):
            if self.state == ShopState.TALK_MENU:
                if self._selected_index % 2 == 0:
                    self._selected_index += 1
                    self._on_selection_changed()
                    self.update()
            elif self.state == ShopState.TASKS:
                self._tasks_tab = (self._tasks_tab + 1) % 4
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

            # 1. Exit Mode: click again to close
            if self.state == ShopState.EXITING:
                if self._is_typing():
                    self._finish_typing()
                else:
                    self.close_shop()
                return

            # 2. Dialogue skip loading without dismissing
            if self._is_dialogue_rect(pos_canvas):
                if self._is_typing():
                    self._finish_typing()
                    return
                elif self.state == ShopState.TALK_DIALOGUE:
                    self._confirm_selection()
                    return

            # 3. Check 4-Tab clicks in TASKS (y: 263..289)
            if self.state == ShopState.TASKS and 263 <= pos_canvas.y() <= 289:
                if 24 <= pos_canvas.x() <= 112:
                    self._tasks_tab = 0
                    self._selected_index = 0
                    self.update()
                    return
                elif 118 <= pos_canvas.x() <= 206:
                    self._tasks_tab = 1
                    self._selected_index = 0
                    self.update()
                    return
                elif 212 <= pos_canvas.x() <= 304:
                    self._tasks_tab = 2
                    self._selected_index = 0
                    self.update()
                    return
                elif 310 <= pos_canvas.x() <= 402:
                    self._tasks_tab = 3
                    self._selected_index = 0
                    self.update()
                    return

            # 4. Check Top-Right Inspector Card click (x: 412..628, y: 46..246)
            if 412 <= pos_canvas.x() <= 628 and 46 <= pos_canvas.y() <= 246:
                if self.state == ShopState.TASKS:
                    if self._tasks_tab == 0:
                        goals = self._get_goals()
                        if goals:
                            idx = (self._selected_index - 1) if 1 <= self._selected_index <= len(goals) else 0
                            self._open_item_action("goal", goals[idx])
                            return
                    elif self._tasks_tab == 1:
                        reminders = self._get_active_reminders()
                        if reminders:
                            idx = (self._selected_index - 1) if 1 <= self._selected_index <= len(reminders) else 0
                            self._open_item_action("task", reminders[idx])
                            return
                    elif self._tasks_tab == 2:
                        alarms = self._get_scheduled_alarms()
                        if alarms:
                            idx = (self._selected_index - 1) if 1 <= self._selected_index <= len(alarms) else 0
                            al = alarms[idx]
                            self._open_item_action("alarm", al.get("label", "Alarm"), al)
                            return
                    elif self._tasks_tab == 3:
                        items = self._get_timers_menu_items()
                        active_items = [it for it in items if it.get("kind") in ("active_shop", "active_memory")]
                        if active_items:
                            it = active_items[0]
                            self._open_item_action("timer", it.get("label", "Timer"), it.get("data") or it.get("kind"))
                            return
                elif self.state == ShopState.FACTS_EDIT:
                    notes = self._get_fact_notes()
                    if notes:
                        idx = (self._selected_index - 2) if self._selected_index >= 2 and (self._selected_index - 2) < len(notes) else 0
                        self._open_item_action("fact", notes[idx])
                        return

            # 5. Check scroll arrow clicks
            if self.state in (ShopState.TASKS, ShopState.FACTS_EDIT):
                if 370 <= pos_canvas.x() <= 405:
                    if 286 <= pos_canvas.y() <= 316:
                        self._scroll_up()
                        return
                    elif 411 <= pos_canvas.y() <= 446:
                        self._scroll_down()
                        return

            # 6. Menu item selection & instant single-click execution
            clicked_idx = self._get_item_at_canvas_pos(pos_canvas)
            if clicked_idx is not None:
                self._selected_index = clicked_idx
                if self.state == ShopState.ITEM_ACTION:
                    self._inspect_choice_idx = clicked_idx
                self._on_selection_changed()
                self._confirm_selection()
                self.update()
                return

            # 7. Draggable upper stage
            if pos_canvas.y() < 240 and pos_canvas.x() < 410:
                self._drag_active = True
                self._drag_start_pos = event.globalPos() - self.pos()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_active:
            self.move(event.globalPos() - self._drag_start_pos)
            return

        pos_canvas = self._screen_to_canvas(event.pos())
        hover_idx = self._get_item_at_canvas_pos(pos_canvas)
        is_dialogue = self._is_dialogue_rect(pos_canvas)

        is_tab_hover = False
        if self.state == ShopState.TASKS and 263 <= pos_canvas.y() <= 289 and 24 <= pos_canvas.x() <= 402:
            is_tab_hover = True

        is_card_hover = False
        if 412 <= pos_canvas.x() <= 628 and 46 <= pos_canvas.y() <= 246:
            if self.state in (ShopState.TASKS, ShopState.FACTS_EDIT):
                is_card_hover = True

        if hover_idx is not None or is_tab_hover or is_card_hover:
            self.setCursor(Qt.PointingHandCursor)
            if hover_idx is not None and hover_idx != self._selected_index:
                self._selected_index = hover_idx
                if self.state == ShopState.ITEM_ACTION:
                    self._inspect_choice_idx = hover_idx
                self._on_selection_changed()
                self.update()
        elif is_dialogue and (self._is_typing() or self.state in (ShopState.TALK_DIALOGUE, ShopState.EXITING)):
            self.setCursor(Qt.PointingHandCursor)
        elif pos_canvas.y() < 240 and pos_canvas.x() < 410:
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
            if 412 <= pt.x() <= 628 and 266 <= pt.y() <= 451:
                idx = (pt.y() - 271) // 36
                if 0 <= idx < 5:
                    return idx

        elif self.state == ShopState.CHARACTER:
            if 20 <= pt.x() <= 403 and 271 <= pt.y() <= 456:
                idx = (pt.y() - 271) // 42
                if 0 <= idx < len(CHARACTER_FORMS):
                    return idx
            if 412 <= pt.x() <= 628 and 406 <= pt.y() <= 461:
                return len(CHARACTER_FORMS)

        elif self.state == ShopState.TASKS:
            if 20 <= pt.x() <= 385 and 293 <= pt.y() <= 441:
                row = (pt.y() - 293) // 36
                if 0 <= row < 4:
                    if self._tasks_tab == 0:
                        idx = row + self._goals_scroll_offset
                        if idx < len(self._get_goals()) + 1:
                            return idx
                    elif self._tasks_tab == 1:
                        idx = row + self._tasks_scroll_offset
                        if idx < len(self._get_active_reminders()) + 1:
                            return idx
                    elif self._tasks_tab == 2:
                        idx = row + self._alarms_scroll_offset
                        if idx < len(self._get_scheduled_alarms()) + 1:
                            return idx
                    elif self._tasks_tab == 3:
                        idx = row + self._timers_scroll_offset
                        if idx < len(self._get_timers_menu_items()):
                            return idx
            if 412 <= pt.x() <= 628 and 406 <= pt.y() <= 461:
                return self._get_menu_count() - 1

        elif self.state == ShopState.SETTINGS_MENU:
            if 20 <= pt.x() <= 403 and 276 <= pt.y() <= 451:
                idx = (pt.y() - 276) // 44
                if 0 <= idx < 3:
                    return idx

        elif self.state == ShopState.FACTS_EDIT:
            if 20 <= pt.x() <= 385 and 293 <= pt.y() <= 441:
                row = (pt.y() - 293) // 36
                if 0 <= row < 4:
                    idx = row + self._notes_scroll_offset
                    if idx < len(self._get_facts_menu_items()):
                        return idx
            if 412 <= pt.x() <= 628 and 406 <= pt.y() <= 461:
                return self._get_menu_count() - 1

        elif self.state == ShopState.TOGGLES_MENU:
            if 20 <= pt.x() <= 385 and 293 <= pt.y() <= 441:
                row = (pt.y() - 293) // 36
                if 0 <= row < 4:
                    return row
            if 412 <= pt.x() <= 628 and 406 <= pt.y() <= 461:
                return 4

        elif self.state == ShopState.ITEM_ACTION:
            if 412 <= pt.x() <= 628 and 281 <= pt.y() <= 456:
                idx = (pt.y() - 281) // 44
                if 0 <= idx < len(self._inspect_options):
                    return idx

        elif self.state in (ShopState.TASK_CONFIRM, ShopState.TASK_SECOND_CONFIRM):
            if 412 <= pt.x() <= 628:
                if 316 <= pt.y() <= 366:
                    return 0
                elif 371 <= pt.y() <= 426:
                    return 1

        elif self.state == ShopState.TALK_MENU:
            if 276 <= pt.y() <= 456:
                row = min(3, max(0, (pt.y() - 276) // 44))
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
                              ShopState.TASK_SECOND_CONFIRM, ShopState.SETTINGS_MENU,
                              ShopState.FACTS_EDIT, ShopState.TOGGLES_MENU, ShopState.ITEM_ACTION):
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
            elif self.state == ShopState.SETTINGS_MENU:
                self._draw_settings_menu_state(p)
            elif self.state == ShopState.FACTS_EDIT:
                self._draw_facts_edit_state(p)
            elif self.state == ShopState.TOGGLES_MENU:
                self._draw_toggles_menu_state(p)
            elif self.state == ShopState.ITEM_ACTION:
                self._draw_item_action_state(p)
            elif self.state == ShopState.TASK_CONFIRM:
                self._draw_task_confirm_state(p)
            elif self.state == ShopState.TASK_SECOND_CONFIRM:
                self._draw_task_second_confirm_state(p)
            elif self.state in (ShopState.TALK_MENU, ShopState.TALK_DIALOGUE):
                self._draw_talk_state(p)
            elif self.state == ShopState.EXITING:
                self._draw_dialogue_text(p, QRect(32, 269, 355, 185))
                p.setFont(self._font_small)
                p.setPen(QColor(255, 255, 0))
                p.drawText(430, 441, "[Click or press Z to Exit]")

        finally:
            p.end()

    def _draw_dialogue_text(self, p: QPainter, rect: QRect) -> None:
        p.setFont(self._font_body)
        p.setPen(QColor(255, 255, 255))
        visible_text = self._dialogue_text[: self._dialogue_char_idx]
        p.drawText(rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, visible_text)

    def _draw_root_state(self, p: QPainter) -> None:
        self._draw_dialogue_text(p, QRect(32, 269, 355, 185))

        p.setFont(self._font_body)
        options = ["CHARACTER", "TASKS & ALARMS", "TALK", "CONFIG & SETTINGS", "EXIT"]
        start_x = 444
        start_y = 283
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
        p.drawText(430, 459, f"P$ {self._wallet.pink_dollars:06d}")

    def _draw_character_state(self, p: QPainter) -> None:
        # Top-Right Details Card
        p.setFont(self._font_title)
        p.setPen(QColor(255, 255, 0))
        p.drawText(426, 59, "Pink's Wardrobe")

        p.setFont(self._font_small)
        if self._selected_index < len(CHARACTER_FORMS):
            f = CHARACTER_FORMS[self._selected_index]
            status = f.get("status", "LOCKED")
            p.setPen(QColor(170, 255, 230) if status == "EQUIPPED" else QColor(255, 160, 200))
            p.drawText(426, 81, f"Status: {status}")

            p.setPen(QColor(255, 255, 255))
            p.drawText(QRect(426, 96, 188, 135), Qt.AlignLeft | Qt.TextWordWrap, f["desc"])

        # Bottom-Left Forms List
        p.setFont(self._font_body)
        start_x = 44
        start_y = 286
        line_h = 42

        for i, f in enumerate(CHARACTER_FORMS):
            is_sel = (i == self._selected_index)
            status = f.get("status", "LOCKED")
            color = QColor(255, 255, 0) if is_sel else (QColor(170, 255, 230) if status == "EQUIPPED" else QColor(160, 160, 175))
            p.setPen(color)

            mark = f" [{status}]"
            p.drawText(start_x, start_y + i * line_h, f"{f['name']}{mark}")

            if is_sel and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

        # Bottom-Right Wallet & Back
        p.setFont(self._font_body)
        p.setPen(QColor(255, 180, 220))
        p.drawText(430, 286, "Pink Dollars:")
        p.setPen(QColor(255, 255, 255))
        p.drawText(430, 316, f"P$ {self._wallet.pink_dollars:06d}")

        p.setFont(self._font_title)
        is_back = (self._selected_index == len(CHARACTER_FORMS))
        p.setPen(QColor(255, 255, 0) if is_back else QColor(255, 255, 255))
        p.drawText(450, 436, "Back")
        if is_back and self._soul_heart:
            p.drawPixmap(424, 422, self._soul_heart)

    def _draw_tasks_and_alarms_state(self, p: QPainter) -> None:
        # 4 Tab Headers: [ GOALS ]  [ TASKS ]  [ ALARMS ]  [ TIMERS ]
        p.setFont(self._font_title)
        tab_titles = ["GOALS", "TASKS", "ALARMS", "TIMERS"]
        tab_xs = [24, 118, 212, 310]

        for i, tname in enumerate(tab_titles):
            is_active = (self._tasks_tab == i)
            p.setPen(QColor(255, 255, 0) if is_active else QColor(150, 150, 180))
            p.drawText(tab_xs[i], 283, f"[{tname}]" if is_active else tname)

        # Top-Right Details Card
        p.setFont(self._font_title)
        p.setPen(QColor(170, 255, 230))

        if self._tasks_tab == 0:
            goals = self._get_goals()
            p.drawText(426, 59, "Goals Board")
            p.setFont(self._font_small)
            p.setPen(QColor(140, 206, 255))
            p.drawText(426, 79, f"Active Goals: {len(goals)}")
            p.setPen(QColor(255, 255, 255))
            if 1 <= self._selected_index <= len(goals):
                p.drawText(QRect(426, 93, 188, 125), Qt.AlignLeft | Qt.TextWordWrap, goals[self._selected_index - 1])
            else:
                p.drawText(QRect(426, 93, 188, 125), Qt.AlignLeft | Qt.TextWordWrap, "Set personal milestones! Completing a milestone awards a bonus of +P$ 000005!")
            p.setFont(self._font_small)
            p.setPen(QColor(255, 255, 0))
            p.drawText(QRect(426, 227, 188, 18), Qt.AlignCenter, "[ Click card for options ]")

        elif self._tasks_tab == 1:
            reminders = self._get_active_reminders()
            p.drawText(426, 59, "Chore Board")
            p.setFont(self._font_small)
            p.setPen(QColor(140, 206, 255))
            p.drawText(426, 79, f"Active Chores: {len(reminders)}")
            p.setPen(QColor(255, 255, 255))
            if 1 <= self._selected_index <= len(reminders):
                t_val = evaluate_task_value(reminders[self._selected_index - 1])
                p.drawText(QRect(426, 93, 188, 125), Qt.AlignLeft | Qt.TextWordWrap, f"Valuation: +P$ {t_val}\n\"{reminders[self._selected_index - 1]}\"")
            else:
                p.drawText(QRect(426, 93, 188, 125), Qt.AlignLeft | Qt.TextWordWrap, "Pink awards P$ 1 - P$ 3 per completed chore.\nShe checks screen sights & session memories for proof!")
            p.setFont(self._font_small)
            p.setPen(QColor(255, 255, 0))
            p.drawText(QRect(426, 227, 188, 18), Qt.AlignCenter, "[ Click card for options ]")

        elif self._tasks_tab == 2:
            alarms = self._get_scheduled_alarms()
            p.drawText(426, 59, "Clock Alarms")
            p.setFont(self._font_small)
            p.setPen(QColor(140, 206, 255))
            p.drawText(426, 79, f"Scheduled: {len(alarms)}")
            p.setPen(QColor(255, 255, 255))
            if 1 <= self._selected_index <= len(alarms):
                al = alarms[self._selected_index - 1]
                p.drawText(QRect(426, 93, 188, 125), Qt.AlignLeft | Qt.TextWordWrap, f"Time: {al.get('clock_time')}\nReason: {al.get('label')}")
            else:
                p.drawText(QRect(426, 93, 188, 125), Qt.AlignLeft | Qt.TextWordWrap, "Schedule wall-clock alarms. Pink will pop up choices to Dismiss or Snooze when time hits!")
            p.setFont(self._font_small)
            p.setPen(QColor(255, 255, 0))
            p.drawText(QRect(426, 227, 188, 18), Qt.AlignCenter, "[ Click card for options ]")

        elif self._tasks_tab == 3:
            p.drawText(426, 59, "Focus Timers")
            p.setFont(self._font_small)
            p.setPen(QColor(140, 206, 255))
            if self._timer_active:
                m, s = divmod(self._timer_seconds_remaining, 60)
                p.drawText(426, 79, f"Active: {m:02d}:{s:02d} ({self._timer_label})")
            else:
                p.drawText(426, 79, "Status: Ready")
            p.setPen(QColor(255, 255, 255))
            p.drawText(QRect(426, 93, 188, 125), Qt.AlignLeft | Qt.TextWordWrap, "Pick a study sprint or break timer.\nPink provides visual alert animations and bonus P$ upon completion!")
            p.setFont(self._font_small)
            p.setPen(QColor(255, 255, 0))
            p.drawText(QRect(426, 227, 188, 18), Qt.AlignCenter, "[ Click card for options ]")

        # Bottom-Left List Area (Scrollable with 4 visible rows)
        start_x = 44
        start_y = 316
        line_h = 36

        if self._tasks_tab == 0:  # GOALS
            goals = self._get_goals()
            full_list = ["[+ Add New Goal]"] + [f"{i+1}. {g}" for i, g in enumerate(goals)]
            visible_items = full_list[self._goals_scroll_offset : self._goals_scroll_offset + 4]
            p.setFont(self._font_body)
            for row_idx, text in enumerate(visible_items):
                actual_idx = row_idx + self._goals_scroll_offset
                is_active = (actual_idx == self._selected_index)
                color = QColor(255, 255, 0) if is_active else (QColor(170, 255, 230) if actual_idx == 0 else QColor(255, 255, 255))
                p.setPen(color)
                preview = text[:26] + "..." if len(text) > 26 else text
                p.drawText(start_x, start_y + row_idx * line_h, preview)
                if is_active and self._soul_heart:
                    p.drawPixmap(start_x - 24, start_y + row_idx * line_h - 13, self._soul_heart)

            # Scroll indicators
            p.setFont(self._font_small)
            p.setPen(QColor(255, 255, 0))
            if self._goals_scroll_offset > 0:
                p.drawText(380, 296, "▲")
            if self._goals_scroll_offset + 4 < len(full_list):
                p.drawText(380, 446, "▼")

        elif self._tasks_tab == 1:  # TASKS
            reminders = self._get_active_reminders()
            full_list = ["[+ Add New Task]"] + [f"{i+1}. {r}" for i, r in enumerate(reminders)]
            visible_items = full_list[self._tasks_scroll_offset : self._tasks_scroll_offset + 4]
            p.setFont(self._font_body)
            for row_idx, text in enumerate(visible_items):
                actual_idx = row_idx + self._tasks_scroll_offset
                is_active = (actual_idx == self._selected_index)
                color = QColor(255, 255, 0) if is_active else (QColor(170, 255, 230) if actual_idx == 0 else QColor(255, 255, 255))
                p.setPen(color)

                if actual_idx > 0 and actual_idx - 1 < len(reminders):
                    rem_text = reminders[actual_idx - 1]
                    val = evaluate_task_value(rem_text)
                    short_text = rem_text[:18] + "..." if len(rem_text) > 18 else rem_text
                    p.drawText(start_x, start_y + row_idx * line_h, f"{actual_idx}. {short_text}")
                    p.setPen(QColor(255, 180, 220) if not is_active else QColor(255, 255, 0))
                    p.drawText(310, start_y + row_idx * line_h, f"+P$ {val}")
                else:
                    p.drawText(start_x, start_y + row_idx * line_h, text)

                if is_active and self._soul_heart:
                    p.drawPixmap(start_x - 24, start_y + row_idx * line_h - 13, self._soul_heart)

            # Scroll indicators
            p.setFont(self._font_small)
            p.setPen(QColor(255, 255, 0))
            if self._tasks_scroll_offset > 0:
                p.drawText(380, 296, "▲")
            if self._tasks_scroll_offset + 4 < len(full_list):
                p.drawText(380, 446, "▼")

        elif self._tasks_tab == 2:  # ALARMS
            alarms = self._get_scheduled_alarms()
            full_list = ["[+ Set Clock Alarm]"] + [f"{i+1}. {a.get('clock_time')} ({a.get('label', '')[:14]})" for i, a in enumerate(alarms)]
            visible_items = full_list[self._alarms_scroll_offset : self._alarms_scroll_offset + 4]
            p.setFont(self._font_body)
            for row_idx, text in enumerate(visible_items):
                actual_idx = row_idx + self._alarms_scroll_offset
                is_active = (actual_idx == self._selected_index)
                color = QColor(255, 255, 0) if is_active else (QColor(170, 255, 230) if actual_idx == 0 else QColor(255, 255, 255))
                p.setPen(color)
                p.drawText(start_x, start_y + row_idx * line_h, text)
                if is_active and self._soul_heart:
                    p.drawPixmap(start_x - 24, start_y + row_idx * line_h - 13, self._soul_heart)

            # Scroll indicators
            p.setFont(self._font_small)
            p.setPen(QColor(255, 255, 0))
            if self._alarms_scroll_offset > 0:
                p.drawText(380, 296, "▲")
            if self._alarms_scroll_offset + 4 < len(full_list):
                p.drawText(380, 446, "▼")

        elif self._tasks_tab == 3:  # TIMERS
            timers_items = self._get_timers_menu_items()
            visible_items = timers_items[self._timers_scroll_offset : self._timers_scroll_offset + 4]
            p.setFont(self._font_body)
            for row_idx, it in enumerate(visible_items):
                actual_idx = row_idx + self._timers_scroll_offset
                is_active = (actual_idx == self._selected_index)
                color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
                p.setPen(color)
                lbl = it.get("label", "")
                if len(lbl) > 26:
                    lbl = lbl[:25] + "..."
                p.drawText(start_x, start_y + row_idx * line_h, lbl)
                if is_active and self._soul_heart:
                    p.drawPixmap(start_x - 24, start_y + row_idx * line_h - 13, self._soul_heart)

            # Scroll indicators
            p.setFont(self._font_small)
            p.setPen(QColor(255, 255, 0))
            if self._timers_scroll_offset > 0:
                p.drawText(380, 296, "▲")
            if self._timers_scroll_offset + 4 < len(timers_items):
                p.drawText(380, 446, "▼")

        # Bottom-Right Wallet & Back
        p.setFont(self._font_body)
        p.setPen(QColor(255, 180, 220))
        p.drawText(430, 286, "Pink Dollars:")
        p.setPen(QColor(255, 255, 255))
        p.drawText(430, 316, f"P$ {self._wallet.pink_dollars:06d}")

        p.setFont(self._font_title)
        back_idx = self._get_menu_count() - 1
        is_back = (self._selected_index == back_idx)
        p.setPen(QColor(255, 255, 0) if is_back else QColor(255, 255, 255))
        p.drawText(450, 436, "Back")
        if is_back and self._soul_heart:
            p.drawPixmap(424, 422, self._soul_heart)

    def _draw_settings_menu_state(self, p: QPainter) -> None:
        # Top-Right Overview Card
        p.setFont(self._font_title)
        p.setPen(QColor(255, 255, 0))
        p.drawText(426, 59, "Settings Menu")

        p.setFont(self._font_small)
        p.setPen(QColor(140, 206, 255))
        p.drawText(426, 81, "Sanctuary Controls")

        p.setPen(QColor(255, 255, 255))
        p.drawText(
            QRect(426, 96, 188, 135),
            Qt.AlignLeft | Qt.TextWordWrap,
            "Manage permanent memory notes, edit your primary nickname, or customize companion live behaviors.",
        )

        # Bottom-Left Settings Menu
        p.setFont(self._font_title)
        options = ["1. Edit Facts & Nickname", "2. Companion Toggles", "3. Back"]
        start_x = 44
        start_y = 301
        line_h = 44

        for i, opt in enumerate(options):
            is_active = (i == self._selected_index)
            color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
            p.setPen(color)
            p.drawText(start_x, start_y + i * line_h, opt)

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

    def _draw_facts_edit_state(self, p: QPainter) -> None:
        notes = self._get_fact_notes()

        # Top-Right Card
        p.setFont(self._font_title)
        p.setPen(QColor(170, 255, 230))
        if self._selected_index >= 2 and (self._selected_index - 2) < len(notes):
            note_idx = self._selected_index - 2
            p.drawText(426, 59, f"Fact Note #{note_idx + 1}")
            p.setFont(self._font_small)
            p.setPen(QColor(140, 206, 255))
            p.drawText(426, 79, "Permanent Memory")
            p.setPen(QColor(255, 255, 255))
            p.drawText(QRect(426, 93, 188, 125), Qt.AlignLeft | Qt.TextWordWrap, notes[note_idx])
            p.setFont(self._font_small)
            p.setPen(QColor(255, 255, 0))
            p.drawText(QRect(426, 227, 188, 18), Qt.AlignCenter, "[ Click card for options ]")
        else:
            p.drawText(426, 59, "Fact Sheet")
            p.setFont(self._font_small)
            p.setPen(QColor(140, 206, 255))
            p.drawText(426, 79, f"User: {self._get_user_name()}")
            p.setPen(QColor(255, 255, 255))
            p.drawText(
                QRect(426, 93, 188, 125),
                Qt.AlignLeft | Qt.TextWordWrap,
                f"Notes Stored: {len(notes)}\nScroll down to view every note! Pink permanently remembers them across all sessions.",
            )
            p.setFont(self._font_small)
            p.setPen(QColor(255, 255, 0))
            p.drawText(QRect(426, 227, 188, 18), Qt.AlignCenter, "[ Click card for options ]")

        # Bottom-Left List
        facts_items = self._get_facts_menu_items()
        visible_items = facts_items[self._notes_scroll_offset : self._notes_scroll_offset + 4]
        start_x = 44
        start_y = 316
        line_h = 36

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
            p.drawText(380, 296, "▲")
        if self._notes_scroll_offset + 4 < len(facts_items):
            p.drawText(380, 446, "▼")

        # Back
        p.setFont(self._font_title)
        back_idx = len(facts_items)
        is_back = (self._selected_index == back_idx)
        p.setPen(QColor(255, 255, 0) if is_back else QColor(255, 255, 255))
        p.drawText(450, 415, "Back")
        if is_back and self._soul_heart:
            p.drawPixmap(424, 401, self._soul_heart)

    def _draw_toggles_menu_state(self, p: QPainter) -> None:
        p.setFont(self._font_title)
        p.setPen(QColor(255, 255, 0))
        p.drawText(426, 59, "Live Toggles")

        p.setFont(self._font_small)
        p.setPen(QColor(140, 206, 255))
        p.drawText(426, 81, "Instant Configuration")

        p.setPen(QColor(255, 255, 255))
        p.drawText(
            QRect(426, 96, 188, 135),
            Qt.AlignLeft | Qt.TextWordWrap,
            "Toggles update desktop pet behavior immediately and persist permanently across runs.",
        )

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

        start_x = 44
        start_y = 296
        line_h = 36

        p.setFont(self._font_body)
        for row_idx, opt in enumerate(toggles):
            is_active = (row_idx == self._selected_index)
            color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
            p.setPen(color)
            p.drawText(start_x, start_y + row_idx * line_h, opt)

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + row_idx * line_h - 13, self._soul_heart)

        p.setFont(self._font_title)
        is_back = (self._selected_index == 4)
        p.setPen(QColor(255, 255, 0) if is_back else QColor(255, 255, 255))
        p.drawText(450, 415, "Back")
        if is_back and self._soul_heart:
            p.drawPixmap(424, 401, self._soul_heart)

    def _draw_item_action_state(self, p: QPainter) -> None:
        # Left Box: Dialogue Text
        self._draw_dialogue_text(p, QRect(32, 269, 355, 185))

        # Top-Right Details
        p.setFont(self._font_title)
        p.setPen(QColor(170, 255, 230))
        p.drawText(426, 59, f"Inspect: {self._inspect_item_kind.upper()}")

        p.setFont(self._font_small)
        p.setPen(QColor(140, 206, 255))
        p.drawText(426, 81, "Action Selection")

        p.setPen(QColor(255, 255, 255))
        p.drawText(QRect(426, 96, 188, 135), Qt.AlignLeft | Qt.TextWordWrap, self._inspect_item_text)

        # Bottom-Right Choices
        p.setFont(self._font_title)
        start_x = 444
        start_y = 301
        line_h = 44

        for i, opt in enumerate(self._inspect_options):
            is_active = (i == self._inspect_choice_idx)
            color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
            p.setPen(color)
            p.drawText(start_x, start_y + i * line_h, opt)

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

    def _draw_task_confirm_state(self, p: QPainter) -> None:
        p.setFont(self._font_title)
        if self._sell_has_evidence:
            p.setPen(QColor(170, 255, 230))
            p.drawText(426, 59, "Verified Work! ✨")
            p.setFont(self._font_small)
            p.setPen(QColor(140, 206, 255))
            proof_type = "Screen Sight" if self._sell_saw_on_screen else "Session Logs"
            p.drawText(426, 81, f"Proof: {proof_type}")
            p.setPen(QColor(255, 255, 255))
            p.drawText(
                QRect(426, 96, 188, 135),
                Qt.AlignLeft | Qt.TextWordWrap,
                f"Pink confirmed proof of work on '{self._sell_evidence_kw}'!\nOne click to complete and collect your P$!",
            )
        else:
            p.setPen(QColor(255, 200, 80))
            p.drawText(426, 59, "Unverified Task ❓")
            p.setFont(self._font_small)
            p.setPen(QColor(255, 160, 100))
            p.drawText(426, 81, "Proof: Not Found")
            p.setPen(QColor(255, 255, 255))
            p.drawText(
                QRect(426, 96, 188, 135),
                Qt.AlignLeft | Qt.TextWordWrap,
                "Pink hasn't observed any evidence of this on your screen or in recent sessions...\nAre you sure you finished it?",
            )

        p.setFont(self._font_body)
        p.setPen(QColor(255, 255, 0))
        p.drawText(36, 286, "Task to Complete:")

        p.setPen(QColor(255, 255, 255))
        task_text = self._pending_sell_reminder or ""
        p.drawText(QRect(36, 311, 350, 140), Qt.AlignLeft | Qt.TextWordWrap, f"\"{task_text}\"")

        p.setFont(self._font_small)
        p.setPen(QColor(140, 206, 255))
        p.drawText(430, 286, f"Value: P$ {self._pending_sell_value}")

        options = [f"YES (+P$ {self._pending_sell_value})", "NO (Keep)"]
        start_x = 444
        start_y = 336
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
        p.drawText(426, 59, "SUSPICION ALERT!")

        p.setFont(self._font_small)
        p.setPen(QColor(255, 140, 140))
        p.drawText(426, 81, "Proof: NOT FOUND!")

        p.setPen(QColor(255, 255, 255))
        p.drawText(
            QRect(426, 96, 188, 135),
            Qt.AlignLeft | Qt.TextWordWrap,
            "Pink scanned your screen sight logs & session memories and found NO evidence of this work!\nAre you double-dog sure?!",
        )

        p.setFont(self._font_body)
        p.setPen(QColor(255, 64, 64))
        p.drawText(36, 286, "Unverified Task Claim:")

        p.setPen(QColor(255, 255, 255))
        task_text = self._pending_sell_reminder or ""
        p.drawText(QRect(36, 311, 350, 90), Qt.AlignLeft | Qt.TextWordWrap, f"\"{task_text}\"")

        p.setFont(self._font_small)
        p.setPen(QColor(255, 140, 140))
        p.drawText(36, 431, "* Pink's Verdict: Highly Suspicious!")

        p.setFont(self._font_small)
        p.setPen(QColor(255, 64, 64))
        p.drawText(430, 286, "FINAL CHANCE:")

        options = ["I REALLY DID!", "...CAUGHT ME"]
        start_x = 444
        start_y = 336
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
            start_y = 301
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
            self._draw_dialogue_text(p, QRect(36, 271, 568, 175))
            p.setFont(self._font_small)
            p.setPen(QColor(157, 162, 196))
            p.drawText(530, 456, "[Z / Esc]")
