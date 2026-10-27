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

import datetime
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
SCENE_FRAME_INTERVAL_MS = 380
TYPEWRITER_INTERVAL_MS = 28


class ShopState(Enum):
    ROOT = auto()
    CHARACTER = auto()            # Wardrobe (Pink equipped; others Coming soon)
    TASKS_SUBMENU = auto()        # Tasks & Alarms Submenu (Goals, Tasks, Alarms, Timers, Back)
    TASKS = auto()                # Tasks & Alarms list items (Goals, Tasks, Alarms, Timers)
    SETTINGS_MENU = auto()        # Config & Settings (Edit Facts, Toggles, Back)
    FACTS_EDIT = auto()           # Facts & Notes editor
    TOGGLES_MENU = auto()         # Companion Toggles (Live)
    ITEM_ACTION = auto()          # Interactive inspection dialogue & choices
    TASK_CONFIRM = auto()         # Stage 1 verification
    TASK_SECOND_CONFIRM = auto()  # Stage 2 suspicion confirmation
    TALK_MENU = auto()            # Serious topics (canon topics + Chat History + Back)
    TALK_DIALOGUE = auto()        # Serious typewriter dialogue
    CHAT_HISTORY_SESSIONS = auto() # Session selection list (Inside TALK menu)
    CHAT_HISTORY_VIEW = auto()     # Turn-by-turn dialogue inspection

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
        "name": "Pink (Equipped)",
        "desc": "The quintessential cotton Mew Mew doll body. The one and only active companion in this world!",
        "status": "EQUIPPED",
    },
    {
        "id": "coming_soon_1",
        "name": "(COMING SOON)",
        "desc": "Additional companion forms and outfits are currently in tailoring development.",
        "status": "COMING SOON",
    },
    {
        "id": "coming_soon_2",
        "name": "(COMING SOON)",
        "desc": "Pink is still tailoring new companion forms and outfits. Check back soon, mew!",
        "status": "COMING SOON",
    },
    {
        "id": "coming_soon_3",
        "name": "(COMING SOON)",
        "desc": "Wardrobe slot locked. Pink is busy experimenting with ribbons and fabrics behind the counter.",
        "status": "COMING SOON",
    },
]

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
    ("Chat History 📜", "chat_history"),
    ("Ask Pink a Question", "ai_ask"),
    ("Back", "back"),
]


def _parse_iso_ts(ts_str: str | None) -> datetime.datetime | None:
    """Safely parse ISO 8601 timestamps into naive datetime for comparison."""
    if not ts_str:
        return None
    try:
        dt = datetime.datetime.fromisoformat(ts_str)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _is_task_creation_turn(msg: dict[str, Any]) -> bool:
    """Identify if a session message turn was creating or registering a reminder."""
    user_text = (msg.get("user") or "").lower()
    pink_text = (msg.get("pink") or "").lower()

    creation_patterns = [
        r"\[add_reminder:",
        r"^/remind\b",
        r"^/todo\b",
        r"^/add_reminder\b",
        r"\bremind me\b",
        r"\bdon't let me forget\b",
        r"\badd (?:a )?(?:new )?(?:task|reminder|chore|todo)\b",
        r"\bput (?:this )?on my (?:chore|task|todo) list\b",
        r"\bregister (?:a )?(?:new )?(?:task|reminder|chore)\b",
    ]
    for pat in creation_patterns:
        if re.search(pat, user_text, re.IGNORECASE) or re.search(pat, pink_text, re.IGNORECASE):
            return True
    return False


def evaluate_task_value(text: str) -> int:
    """Pink evaluates a task's worth between P$ 1 and P$ 4 based on effort, complexity, and scope."""
    clean = (text or "").strip().lower()
    if not clean:
        return 1

    words = re.findall(r"[a-zA-Z0-9_]+", clean)
    if not words:
        return 1

    word_set = set(words)
    score = 2  # Baseline reward for standard daily chores

    # 1. High-complexity / Heavy cognitive or heavy manual labor (+2)
    heavy_kws = {
        "code", "coding", "program", "programming", "develop", "dev", "build", "deploy",
        "deployment", "refactor", "refactoring", "algorithm", "database", "sql", "migration",
        "infrastructure", "infra", "architecture", "thesis", "dissertation", "exam", "finals",
        "midterm", "audit", "presentation", "slides", "pipeline", "backend", "frontend",
        "fullstack", "security", "docker", "kubernetes", "deepwork", "assignment", "paper"
    }
    if any(w in word_set for w in heavy_kws):
        score += 2

    # 2. Medium-complexity / Substantial chores (+1)
    medium_kws = {
        "study", "studying", "homework", "research", "analyze", "analysis", "review",
        "write", "writing", "draft", "article", "essay", "chapter", "documentation", "docs",
        "clean", "cleaning", "organize", "organizing", "declutter", "vacuum", "mop", "laundry",
        "cook", "cooking", "mealprep", "bake", "baking", "workout", "exercise", "gym",
        "fitness", "run", "running", "cardio", "budget", "finance", "taxes", "debug",
        "debugging", "test", "testing", "practice", "rehearse", "design", "figma",
        "wireframe", "read", "reading", "translate", "translation", "groceries", "grocery"
    }
    if any(w in word_set for w in medium_kws):
        score += 1

    # 3. Action / Execution commitment verbs (+1)
    commitment_kws = {
        "finish", "complete", "completed", "submit", "submitted", "publish", "published",
        "ship", "shipped", "finalize", "finalized", "implement", "implemented", "solve", "solved"
    }
    if any(w in word_set for w in commitment_kws):
        score += 1

    # 4. Detail & specificity bonus (+1 if user clearly defined scope)
    if len(words) >= 6 or len(clean) >= 32:
        score += 1

    # 5. Micro-habits & trivial actions (-1, but min 1)
    trivial_kws = {
        "water", "drink", "sip", "snack", "eat", "bite", "stretch", "breathe",
        "blink", "afk", "glance", "check", "tap", "nap", "brush", "floss", "rest"
    }
    if any(w in word_set for w in trivial_kws):
        score -= 1

    return max(1, min(4, score))

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
        self._font_title = QFont(self._font_family, 13)
        self._font_title.setBold(False)
        self._font_title.setWeight(QFont.Normal)
        self._font_body = QFont(self._font_family, 12)
        self._font_body.setBold(False)
        self._font_body.setWeight(QFont.Normal)
        self._font_small = QFont(self._font_family, 11)
        self._font_small.setBold(False)
        self._font_small.setWeight(QFont.Normal)

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
        self._talk_scroll_offset: int = 0
        self._note_scroll_offset: int = 0

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
        self._session_summaries: list[dict[str, Any]] = []
        self._sessions_scroll_offset: int = 0
        self._history_view_turns: list[list[str]] = []
        self._history_turn_idx: int = 0
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
            f"QPushButton {{ background-color: #1a1a2e; color: #ffff00; font-family: '{self._font_family}', monospace; font-size: 11px; font-weight: normal; border: 1px solid #ffff00; padding: 2px 8px; }} QPushButton:hover {{ background-color: #ffff00; color: #000000; }}"
        )
        self._input_send_btn.clicked.connect(self._on_input_submitted)

        self._input_cancel_btn = QPushButton("X", self._input_container)
        self._input_cancel_btn.setCursor(Qt.PointingHandCursor)
        self._input_cancel_btn.setStyleSheet(
            f"QPushButton {{ background-color: #1a1a2e; color: #ff6060; font-family: '{self._font_family}', monospace; font-size: 11px; font-weight: normal; border: 1px solid #ff6060; padding: 2px 6px; }} QPushButton:hover {{ background-color: #ff6060; color: #ffffff; }}"
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
        if self.state in (ShopState.TALK_DIALOGUE, ShopState.CHAT_HISTORY_VIEW):
            return 12 <= pt.x() <= 628 and 248 <= pt.y() <= 472
        elif self.state in (ShopState.ROOT, ShopState.ITEM_ACTION, ShopState.TASK_CONFIRM, ShopState.TASK_SECOND_CONFIRM):
            return 12 <= pt.x() <= 403 and 248 <= pt.y() <= 472
        return False

    def _on_scene_tick(self) -> None:
        cached_count = len(self._bg_cache["root"])
        if cached_count > 0:
            self._scene_frame_idx = (self._scene_frame_idx + 1) % cached_count
            self.update()

    def _clean_history_dialogue(self, text: str) -> list[str]:
        """Clean AI metadata tags, asterisks, and format into speech lines starting with '* '."""
        if not text:
            return ["* ..."]
        t = re.sub(r"\[(?:anim|mode|ghost|seen|add_fact|add_reminder|delete_reminder|edit_reminder):\s*[^\]]+\]", "", text, flags=re.IGNORECASE)
        t = re.sub(r"\*{2,}", "", t)
        lines = [l.strip() for l in t.splitlines() if l.strip()]
        out: list[str] = []
        for l in lines:
            clean_l = l.lstrip("* ").strip()
            if clean_l:
                out.append(f"* {clean_l}")
        return out if out else ["* ..."]

    def _load_session_summaries(self) -> list[dict[str, Any]]:
        """Load and summarize recent chat sessions from memory and disk."""
        mem = self._memory or (self._pet._memory if self._pet and hasattr(self._pet, "_memory") else None)
        if not mem:
            return []

        summaries: list[dict[str, Any]] = []
        now = datetime.datetime.now()

        # 1. Current active session
        active_history = getattr(mem, "history", [])
        if active_history:
            sights: list[str] = []
            for m in active_history:
                s = m.get("seen", "")
                if s and s not in sights:
                    sights.append(s)
            seen_summary = ", ".join(sights[:2]) if sights else ""
            last_turn = active_history[-1]
            last_p = last_turn.get("pink", "")
            clean_p = self._clean_history_dialogue(last_p)
            preview = clean_p[0] if clean_p else ""

            summaries.append({
                "label": "Current Session (Active)",
                "turn_count": len(active_history),
                "seen_summary": seen_summary,
                "preview": preview,
                "messages": list(active_history),
                "is_active": True,
            })

        # 2. Past sessions from sessions_dir
        sessions_dir = getattr(mem, "sessions_dir", None)
        if sessions_dir and sessions_dir.is_dir():
            active_name = mem.session_file.name if hasattr(mem, "session_file") and mem.session_file else ""
            files = sorted(sessions_dir.glob("session_*.json"), reverse=True)
            for f in files:
                if f.name == active_name:
                    continue
                try:
                    if f.stat().st_size <= 120:
                        continue
                    data = json.loads(f.read_text(encoding="utf-8"))
                    msgs = data.get("messages", [])
                    if not msgs:
                        continue

                    first_ts = msgs[0].get("timestamp", "")
                    dt = datetime.datetime.fromisoformat(first_ts) if first_ts else now
                    d_diff = (now.date() - dt.date()).days
                    t_str = dt.strftime("%I:%M %p")
                    if d_diff == 0:
                        date_label = f"Today {t_str}"
                    elif d_diff == 1:
                        date_label = f"Yesterday {t_str}"
                    else:
                        date_label = f"{dt.strftime('%b %d')} {t_str}"

                    sights = []
                    for m in msgs:
                        s = m.get("seen", "")
                        if s and s not in sights:
                            sights.append(s)
                    seen_summary = ", ".join(sights[:2]) if sights else ""

                    last_turn = msgs[-1]
                    last_p = last_turn.get("pink", "")
                    clean_p = self._clean_history_dialogue(last_p)
                    preview = clean_p[0] if clean_p else ""

                    summaries.append({
                        "label": date_label,
                        "turn_count": len(msgs),
                        "seen_summary": seen_summary,
                        "preview": preview,
                        "messages": msgs,
                        "is_active": False,
                    })

                    if len(summaries) >= 40:
                        break
                except Exception as err:
                    log.debug("Error reading session %s for shop: %s", f, err)

        return summaries

    def _prepare_session_turns(self, session_data: dict[str, Any]) -> list[list[str]]:
        """Convert a session's messages into formatted multi-line dialogue cards."""
        msgs = session_data.get("messages", [])
        if not msgs:
            return []

        turns: list[list[str]] = []
        for m in msgs:
            ts_str = m.get("timestamp", "")
            t_str = ""
            if ts_str:
                try:
                    dt = datetime.datetime.fromisoformat(ts_str)
                    t_str = dt.strftime("%I:%M %p")
                except Exception:
                    t_str = ""
            pfx = f"[{t_str}] " if t_str else ""

            u_raw = (m.get("user") or "").strip()
            p_raw = (m.get("pink") or "").strip()
            p_lines = self._clean_history_dialogue(p_raw)

            card_lines: list[str] = []
            if u_raw.startswith("[Pink peeks") and m.get("seen"):
                card_lines.append(f"* {pfx}(Screen Sight): {m['seen']}")
            elif u_raw.startswith("[Music played:"):
                track_info = u_raw[14:].rstrip("]")
                card_lines.append(f"* {pfx}(Music Played): {track_info}")
            elif u_raw.startswith("[Pink asked:"):
                q_info = u_raw[12:].rstrip("]")
                card_lines.append(f"* {pfx}{q_info}")
            elif u_raw.startswith("[Pink annoyed:"):
                if "5 dialogue" in u_raw or "moving" in u_raw:
                    card_lines.append(f"* {pfx}(Annoyed): Ignored 5 dialogue boxes while active")
                else:
                    card_lines.append(f"* {pfx}(Annoyed): Ignored 2 dialogue boxes while away")
            elif u_raw.startswith("[User clicked Pink to acknowledge"):
                card_lines.append(f"* {pfx}(Returned): Acknowledged Pink")
            elif u_raw.startswith(("[User returned after being away]", "[User clicked Pink to return")):
                card_lines.append(f"* {pfx}(Returned): User returned from AFK")
            elif u_raw:
                clean_u = u_raw.replace("\n", " ").strip()
                if len(clean_u) > 90:
                    clean_u = clean_u[:87] + "..."
                card_lines.append(f"* {pfx}You: \"{clean_u}\"")

            card_lines.extend(p_lines)
            turns.append(card_lines)

        return turns

    def _prev_history_turn(self) -> None:
        if not self._history_view_turns:
            return
        if self._history_turn_idx > 0:
            self._history_turn_idx -= 1
            self.set_dialogue("\n".join(self._history_view_turns[self._history_turn_idx]))
            self.update()

    def _next_history_turn(self) -> None:
        if not self._history_view_turns:
            return
        if self._history_turn_idx < len(self._history_view_turns) - 1:
            self._history_turn_idx += 1
            self.set_dialogue("\n".join(self._history_view_turns[self._history_turn_idx]))
            self.update()
        else:
            self.state = ShopState.CHAT_HISTORY_SESSIONS
            self.set_dialogue("* End of session turns reached. Returned to archives.")
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
        self.set_dialogue(
            f"* Calibrating focus hourglass and sand crystals...\n"
            f"* Focus countdown primed for {minutes}m ({label})!\n"
            f"* Focus mode engaged, darling! I will sound the alert when time's up, mew!"
        )

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

    def _find_task_created_dt(self, task_text: str, task_data: dict[str, Any] | None = None) -> datetime.datetime | None:
        """Find the creation datetime of a task from task data or memory."""
        created_str = None
        if task_data and isinstance(task_data, dict):
            created_str = task_data.get("created_at")
        if not created_str and self._memory and hasattr(self._memory, "get_active_reminders"):
            try:
                active = self._memory.get_active_reminders()
                for r in active:
                    if isinstance(r, dict) and r.get("text", "").strip().lower() == task_text.strip().lower():
                        created_str = r.get("created_at")
                        if created_str:
                            break
            except Exception:
                pass
        return _parse_iso_ts(created_str)

    def _scan_task_evidence(self, task_text: str, task_data: dict[str, Any] | None = None) -> tuple[bool, bool, str]:
        stopwords = {
            "remind", "reminder", "reminders", "user", "me", "to", "add", "a", "an", "the",
            "in", "for", "you", "and", "or", "of", "on", "with", "from", "till", "this",
            "that", "it", "is", "be", "do", "have", "i", "my", "our", "out", "first",
            "feature", "please", "task", "tasks", "todos", "todo", "chore", "chores",
            "duty", "duties", "check", "started", "start", "make", "just", "about",
            "thing", "things", "will"
        }
        all_words = re.findall(r"[a-zA-Z0-9_]{3,}", task_text.lower())
        keywords = [w for w in all_words if w not in stopwords]
        if not keywords:
            basic_grammar = {"the", "and", "for", "with", "from", "this", "that", "you", "remind", "reminder"}
            keywords = [w for w in all_words if w not in basic_grammar]
        if not keywords and all_words:
            keywords = all_words
        if not keywords:
            keywords = re.findall(r"[a-zA-Z0-9_]{2,}", task_text.lower())
        if not keywords:
            return False, False, ""

        task_created_dt = self._find_task_created_dt(task_text, task_data)

        # 1. Background system tray observations (_tray_observations)
        if self._pet and hasattr(self._pet, "_tray_observations"):
            for obs in getattr(self._pet, "_tray_observations", []):
                obs_ts = _parse_iso_ts(obs.get("timestamp"))
                if task_created_dt and obs_ts and obs_ts <= task_created_dt + datetime.timedelta(seconds=5):
                    continue
                seen_text = (obs.get("seen") or "").lower()
                obs_text = (obs.get("text") or "").lower()
                for kw in keywords:
                    kw_pat = rf"\b{re.escape(kw)}\b"
                    if (seen_text and re.search(kw_pat, seen_text, re.IGNORECASE)) or (obs_text and re.search(kw_pat, obs_text, re.IGNORECASE)):
                        return True, True, kw

        # 2. Session logs (memory/sessions/*.json)
        sessions_dir = _BASE_DIR / "memory" / "sessions"
        if sessions_dir.exists():
            for s_file in sorted(sessions_dir.glob("*.json"), reverse=True)[:12]:
                try:
                    data = json.loads(s_file.read_text(encoding="utf-8"))
                    for msg in data.get("messages", []):
                        msg_ts = _parse_iso_ts(msg.get("timestamp"))
                        # Validate that evidence occurred strictly after task creation
                        if task_created_dt and msg_ts and msg_ts <= task_created_dt + datetime.timedelta(seconds=5):
                            continue
                        # Prevent task creation prompts from counting as proof
                        if _is_task_creation_turn(msg):
                            continue

                        seen_text = (msg.get("seen") or "").lower()
                        user_text = (msg.get("user") or "").lower()
                        pink_text = (msg.get("pink") or "").lower()

                        # Check desktop screen sights (turn["seen"] or peek observation headers)
                        for kw in keywords:
                            kw_pat = rf"\b{re.escape(kw)}\b"
                            if seen_text and re.search(kw_pat, seen_text, re.IGNORECASE):
                                return True, True, kw
                            if user_text.startswith("[pink peeks") and re.search(kw_pat, user_text, re.IGNORECASE):
                                return True, True, kw

                        # Check general chat turns (user or pink talking about task completion/work)
                        for kw in keywords:
                            kw_pat = rf"\b{re.escape(kw)}\b"
                            if re.search(kw_pat, user_text, re.IGNORECASE) or re.search(kw_pat, pink_text, re.IGNORECASE):
                                return True, False, kw
                except Exception:
                    pass

        # If no evidence found, return False with first keyword for dialogue display
        return False, False, (keywords[0] if keywords else "")
    # --- Goals, Facts, Tasks & Alarms Model ------------------------------------

    def _get_goals_file_path(self) -> Path:
        if hasattr(self, "_memory") and self._memory and hasattr(self._memory, "memory_dir"):
            return self._memory.memory_dir / "goals.json"
        return GOALS_PATH

    def evaluate_goal_value(self, text: str) -> int:
        """Pink decides what a personal goal/milestone is worth (awarding between P$ 03 and P$ 08)."""
        clean = (text or "").lower()
        score = 4
        major_kws = [
            "finish", "complete", "publish", "ship", "launch", "exam", "thesis",
            "marathon", "project", "degree", "clean", "build", "develop", "refactor",
            "gym", "workout", "fitness", "run", "exercise", "learn", "study",
            "write", "chapter", "release", "portfolio", "presentation", "assignment"
        ]
        score += sum(1 for kw in major_kws if kw in clean)
        if len(clean.split()) >= 6:
            score += 1
        if len(clean) >= 35:
            score += 1
        trivial_kws = ["water", "drink", "check", "eat", "snack", "stretch", "breathe", "nap"]
        if any(kw in clean for kw in trivial_kws):
            score -= 1
        return max(3, min(8, score))

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
        val = self.evaluate_goal_value(text)
        if self._delete_goal(text):
            self._wallet.add(val)
            self.set_dialogue(
                f"* TARGET MILESTONE CONQUERED!!\n* You finished: \"{text}\"\n* Pink evaluated your achievement at +P$ {val:06d}!"
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

    def _edit_fact_note(self, old_text: str, new_text: str) -> bool:
        notes = self._get_fact_notes()
        if old_text in notes:
            idx = notes.index(old_text)
            notes[idx] = new_text
            p = self._get_facts_file_path()
            try:
                data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
                data["notes"] = notes
                p.write_text(json.dumps(data, indent=2), encoding="utf-8")
                return True
            except Exception as e:
                log.warning("Could not edit fact note: %s", e)
        return False

    def _prompt_edit_fact_note(self, note_text: str) -> None:
        self._input_mode = "edit_fact_note"
        self._show_input_bar("Edit Fact Note:")
        self._ai_input.setText(note_text)
        self._ai_input.selectAll()

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

    def _get_active_reminder_objects(self) -> list[dict[str, Any]]:
        """Return raw active reminder objects with IDs and created_at timestamps."""
        if not self._memory:
            return []
        try:
            if hasattr(self._memory, "get_active_reminders"):
                reminders = self._memory.get_active_reminders()
            elif hasattr(self._memory, "get_reminders"):
                reminders = self._memory.get_reminders()
            else:
                reminders = []
            return [r for r in reminders if isinstance(r, dict) and r.get("text")]
        except Exception as e:
            log.warning("Could not fetch active reminder objects: %s", e)
            return []

    def _get_active_reminders(self) -> list[str]:
        objs = self._get_active_reminder_objects()
        return [r.get("text", "") for r in objs if r.get("text")]
    def _complete_reminder(self, text: str, reward: int) -> None:
        if not self._memory:
            return
        ok, deleted_text = self._memory.delete_reminder(text)
        if ok:
            self._wallet.add(reward)
            self.set_dialogue(
                f"{CANON_SELL_SUCCESS}\n* \"{deleted_text}\" finished! (+P$ {reward:02d})"
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
        self._note_scroll_offset = 0
        self.state = ShopState.ITEM_ACTION

        if kind == "goal":
            val = self.evaluate_goal_value(text)
            self._inspect_options = [f"Complete (+P$ {val:02d})", "Delete Goal", "Back"]
            self.set_dialogue(
                f"* TARGET MILESTONE:\n* \"{text}\"\n* Valuation: +P$ {val:02d}!\n* What would you like to do?"
            )
        elif kind == "task":
            val = evaluate_task_value(text)
            self._inspect_options = [f"Complete (+P$ {val:02d})", "Delete Task", "Back"]
            self.set_dialogue(f"* CHORE ON BOARD:\n* \"{text}\"\n* Valuation: +P$ {val:02d}!\n* Ready to verify and collect P$ {val:02d}?")
        elif kind == "alarm":
            self._inspect_options = ["Cancel / Delete Alarm", "Back"]
            time_str = data.get("clock_time", "Scheduled") if isinstance(data, dict) else ""
            lbl = data.get("label", text) if isinstance(data, dict) else text
            self.set_dialogue(f"* Clock Alarm [{time_str}]:\n* \"{lbl}\"\n* Want Pink to cancel this alarm?")
        elif kind == "timer":
            self._inspect_options = ["Stop / Cancel Timer", "Back"]
            self.set_dialogue(f"* Countdown Timer:\n* \"{text}\"\n* Stop this focus interval?")
        elif kind == "fact":
            self._inspect_options = ["Edit Note", "Delete Note", "Back"]
            self.set_dialogue(text)

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
                r_data = self._inspect_item_data if isinstance(self._inspect_item_data, dict) else None
                has_ev, on_screen, kw = self._scan_task_evidence(task_text, task_data=r_data)
                self._sell_has_evidence = has_ev
                self._sell_saw_on_screen = on_screen
                self._sell_evidence_kw = kw

                self.state = ShopState.TASK_CONFIRM
                self._selected_index = 0
                if has_ev:
                    proof_loc = "on screen" if on_screen else "in session logs"
                    self.set_dialogue(
                        f"* You're gonna give me stuff?\n* Found proof of '{kw}' {proof_loc}! Complete for P$ {self._pending_sell_value:02d}?"
                    )
                else:
                    target_kw = kw or (task_text[:15] if task_text else "that")
                    self.set_dialogue(
                        f"* Huh?\n* I haven't seen you do '{target_kw}' at all... Are you sure you finished it?"
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
            if self._inspect_choice_idx == 0 or opt.startswith("Edit"):
                self._prompt_edit_fact_note(self._inspect_item_text)
            elif self._inspect_choice_idx == 1 or opt.startswith("Delete"):
                self._delete_fact_note(self._inspect_item_text)
                self.set_dialogue(f"* Fact note expunged from memory:\n* \"{self._inspect_item_text}\"")
                self.state = ShopState.FACTS_EDIT
                self._selected_index = 0
                self.update()
            else:
                self.state = ShopState.FACTS_EDIT
                self.set_dialogue("* Back to fact sheet.")
                self.update()

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
        elif self.state == ShopState.TALK_MENU:
            self._talk_scroll_offset = max(0, self._talk_scroll_offset - 1)
        elif self.state == ShopState.CHAT_HISTORY_SESSIONS:
            self._sessions_scroll_offset = max(0, self._sessions_scroll_offset - 1)
        elif self.state == ShopState.ITEM_ACTION and self._inspect_item_kind == "fact":
            self._note_scroll_offset = max(0, self._note_scroll_offset - 1)
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
                max_off = max(0, len(self._get_scheduled_alarms()) + 2 - 4)
                self._alarms_scroll_offset = min(max_off, self._alarms_scroll_offset + 1)
            elif self._tasks_tab == 3:
                max_off = max(0, len(self._get_timers_menu_items()) - 4)
                self._timers_scroll_offset = min(max_off, self._timers_scroll_offset + 1)
        elif self.state == ShopState.FACTS_EDIT:
            max_off = max(0, len(self._get_facts_menu_items()) - 4)
            self._notes_scroll_offset = min(max_off, self._notes_scroll_offset + 1)
        elif self.state == ShopState.TALK_MENU:
            max_off = max(0, len(TALK_TOPICS) - 1 - 4)
            self._talk_scroll_offset = min(max_off, self._talk_scroll_offset + 1)
        elif self.state == ShopState.CHAT_HISTORY_SESSIONS:
            max_off = max(0, len(self._session_summaries) - 4)
            self._sessions_scroll_offset = min(max_off, self._sessions_scroll_offset + 1)
        elif self.state == ShopState.ITEM_ACTION and self._inspect_item_kind == "fact":
            self._note_scroll_offset += 1
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
        if self.state == ShopState.ITEM_ACTION:
            if self._inspect_item_kind == "fact":
                self._scroll_up()
                return
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
        elif self.state == ShopState.TALK_MENU:
            topics_count = len(TALK_TOPICS) - 1
            if self._selected_index < self._talk_scroll_offset:
                self._talk_scroll_offset = self._selected_index
            elif self._selected_index < topics_count and self._selected_index >= self._talk_scroll_offset + 4:
                self._talk_scroll_offset = max(0, self._selected_index - 3)
        elif self.state == ShopState.CHAT_HISTORY_SESSIONS:
            total_items = len(self._session_summaries)
            if self._selected_index < self._sessions_scroll_offset:
                self._sessions_scroll_offset = self._selected_index
            elif self._selected_index < total_items and self._selected_index >= self._sessions_scroll_offset + 4:
                self._sessions_scroll_offset = max(0, self._selected_index - 3)
        elif self.state == ShopState.CHAT_HISTORY_SESSIONS:
            total_items = len(self._session_summaries)
            if self._selected_index < self._sessions_scroll_offset:
                self._sessions_scroll_offset = self._selected_index
            elif self._selected_index < total_items and self._selected_index >= self._sessions_scroll_offset + 4:
                self._sessions_scroll_offset = max(0, self._selected_index - 3)

        self._on_selection_changed()
        self.update()

    def _nav_down(self) -> None:
        count = self._get_menu_count()
        if count <= 0:
            return
        if self.state == ShopState.ITEM_ACTION:
            if self._inspect_item_kind == "fact":
                self._scroll_down()
                return
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
        elif self.state == ShopState.TALK_MENU:
            topics_count = len(TALK_TOPICS) - 1
            if self._selected_index < self._talk_scroll_offset:
                self._talk_scroll_offset = self._selected_index
            elif self._selected_index < topics_count and self._selected_index >= self._talk_scroll_offset + 4:
                self._talk_scroll_offset = max(0, self._selected_index - 3)
        elif self.state == ShopState.CHAT_HISTORY_SESSIONS:
            total_items = len(self._session_summaries)
            if self._selected_index < self._sessions_scroll_offset:
                self._sessions_scroll_offset = self._selected_index
            elif self._selected_index < total_items and self._selected_index >= self._sessions_scroll_offset + 4:
                self._sessions_scroll_offset = max(0, self._selected_index - 3)
        elif self.state == ShopState.CHAT_HISTORY_SESSIONS:
            total_items = len(self._session_summaries)
            if self._selected_index < self._sessions_scroll_offset:
                self._sessions_scroll_offset = self._selected_index
            elif self._selected_index < total_items and self._selected_index >= self._sessions_scroll_offset + 4:
                self._sessions_scroll_offset = max(0, self._selected_index - 3)

        self._on_selection_changed()
        self.update()

    def _get_menu_count(self) -> int:
        if self.state == ShopState.ROOT:
            return 5  # CHARACTER, TASKS & ALARMS, TALK, CONFIG & SETTINGS, EXIT
        elif self.state == ShopState.CHARACTER:
            return len(CHARACTER_FORMS) + 1  # Forms (Pink + 3 COMING SOON) + Back
        elif self.state == ShopState.TASKS_SUBMENU:
            return 5  # Goals, Tasks, Alarms, Timers, Back
        elif self.state == ShopState.TASKS:
            if self._tasks_tab == 0:
                return len(self._get_goals()) + 2  # [+ Add Goal] + Goals + Back
            elif self._tasks_tab == 1:
                return len(self._get_active_reminders()) + 2  # [+ Add Task] + Tasks + Back
            elif self._tasks_tab == 2:
                return len(self._get_scheduled_alarms()) + 3  # [+ Prime Alarm] + Clear All + Alarms + Back
            elif self._tasks_tab == 3:
                return len(self._get_timers_menu_items()) + 1  # Presets + Custom + Actives + Back
        elif self.state == ShopState.SETTINGS_MENU:
            return 5  # Pet Scale, Companion Toggles, Edit Facts, Uninstall Pink, Back
        elif self.state == ShopState.FACTS_EDIT:
            return len(self._get_facts_menu_items()) + 1  # Facts + Back
        elif self.state == ShopState.TOGGLES_MENU:
            return 5  # 4 toggles + Back
        elif self.state == ShopState.ITEM_ACTION:
            return len(self._inspect_options)
        elif self.state in (ShopState.TASK_CONFIRM, ShopState.TASK_SECOND_CONFIRM):
            return 2  # YES, NO
        elif self.state == ShopState.TALK_MENU:
            return len(TALK_TOPICS)
        elif self.state == ShopState.CHAT_HISTORY_SESSIONS:
            return len(self._session_summaries) + 1  # summaries + Back
        elif self.state == ShopState.CHAT_HISTORY_VIEW:
            return max(1, len(self._history_view_turns))
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
        if self.state == ShopState.ROOT:
            dialogues = [
                "* Pink's Wardrobe! Other styles are coming soon, darling!",
                "* Sanctuary Tasks & Alarms Center.\n* What would you like to inspect, darling?",
                "* I guess... we could talk.",
                "* Sanctuary settings & permanent memory fact sheet.",
                "* Exit back to the outside world.",
            ]
            if 0 <= self._selected_index < len(dialogues):
                self.set_dialogue(dialogues[self._selected_index])

        elif self.state == ShopState.CHARACTER:
            if self._selected_index == 0:
                self.set_dialogue("* Pink (Equipped):\n* The one and only companion in this world!")
            elif self._selected_index < 4:
                self.set_dialogue("* (COMING SOON)\n* Tailoring in progress... Coming in a future update!")
            else:
                self.set_dialogue("* Return to the main parlour.")

        elif self.state == ShopState.TASKS_SUBMENU:
            dialogues = [
                "* Target Milestones & Long-term Goals board!\n* Pink evaluates each goal dynamically between P$ 03 and P$ 08!",
                "* Daily Chores & Reminders board!\n* Complete chores to earn P$ 01 to P$ 03 upon verification!",
                "* Alarms (COMING SOON):\n* Scheduled clock alarms are temporarily offline for maintenance.",
                "* Focus Timers (COMING SOON):\n* Focus timers are being rebuilt for the next version, darling!",
                "* Return to the main parlour.",
            ]
            if 0 <= self._selected_index < len(dialogues):
                self.set_dialogue(dialogues[self._selected_index])

        elif self.state == ShopState.TASKS:
            if self._tasks_tab == 0:  # Goals
                goals = self._get_goals()
                if self._selected_index == 0:
                    self.set_dialogue("* Log a new personal milestone objective for Pink to evaluate!")
                elif self._selected_index <= len(goals):
                    g = goals[self._selected_index - 1]
                    val = self.evaluate_goal_value(g)
                    self.set_dialogue(f"* Milestone: \"{g}\"\n* Pink's Valuation: +P$ {val:02d} upon completion!")
                else:
                    self.set_dialogue("* Return to Tasks & Alarms menu.")

            elif self._tasks_tab == 1:  # Tasks
                reminders = self._get_active_reminders()
                if self._selected_index == 0:
                    self.set_dialogue("* Register a new chore to complete for Pink Dollars!")
                elif self._selected_index <= len(reminders):
                    t = reminders[self._selected_index - 1]
                    val = evaluate_task_value(t)
                    self.set_dialogue(f"* Chore: \"{t}\"\n* Pink's Valuation: +P$ {val:02d} upon verification!")
                else:
                    self.set_dialogue("* Return to Tasks & Alarms menu.")

            elif self._tasks_tab == 2:  # Alarms
                alarms = self._get_scheduled_alarms()
                if self._selected_index == 0:
                    self.set_dialogue("* Prime a new wall-clock alarm (e.g. 08:30 AM Meeting)!")
                elif self._selected_index == 1:
                    self.set_dialogue("* Clear all scheduled alarms from the memory log.")
                elif self._selected_index - 2 < len(alarms):
                    al = alarms[self._selected_index - 2]
                    self.set_dialogue(f"* Clock Alarm: [{al.get('clock_time')}] \"{al.get('label')}\"")
                else:
                    self.set_dialogue("* Return to Tasks & Alarms menu.")

            elif self._tasks_tab == 3:  # Timers
                timers = self._get_timers_menu_items()
                if self._selected_index < len(timers):
                    it = timers[self._selected_index]
                    self.set_dialogue(f"* Focus Timer: {it.get('label')}")
                else:
                    self.set_dialogue("* Return to Tasks & Alarms menu.")

        elif self.state == ShopState.SETTINGS_MENU:
            cur_scale = getattr(self._pet, "_scale_modifier", 1.0) if self._pet else 1.0
            scale_str = f"{cur_scale:.2f}x" if cur_scale != round(cur_scale) else f"{cur_scale:.1f}x"
            dialogues = [
                f"* Adjust Pink's sprite scale on your desktop ({scale_str}).",
                "* Toggle companion autonomous behaviors in real time.",
                "* Permanent memory fact sheet & nickname manager.",
                "* Uninstall Pink and cleanly remove settings/data.",
                "* Return to the main parlour.",
            ]
            if 0 <= self._selected_index < len(dialogues):
                self.set_dialogue(dialogues[self._selected_index])

        elif self.state == ShopState.TOGGLES_MENU:
            dialogues = [
                "* Toggle desktop speech bubble thoughts and reactions.",
                "* Toggle real-time background song commentary.",
                "* Auto-detect video games for faster screen commentary & backseat catgirl banter.",
                "* Toggle feline explosive ordnance and laser defense.",
                "* Return to sanctuary settings.",
            ]
            if 0 <= self._selected_index < len(dialogues):
                self.set_dialogue(dialogues[self._selected_index])

        elif self.state == ShopState.FACTS_EDIT:
            notes = self._get_fact_notes()
            if self._selected_index == 0:
                self.set_dialogue(f"* Change your nickname (current: {self._get_user_name()}).")
            elif self._selected_index == 1:
                self.set_dialogue("* Inscribe a new permanent fact note into Pink's logs.")
            elif self._selected_index - 2 < len(notes):
                full_note = notes[self._selected_index - 2]
                self.set_dialogue(f"* Fact Note #{self._selected_index - 1}:\n* \"{full_note}\"")
            else:
                self.set_dialogue("* Return to sanctuary settings.")

        elif self.state == ShopState.TALK_MENU:
            if self._selected_index < len(TALK_TOPICS) - 1:
                title, key = TALK_TOPICS[self._selected_index]
                if key == "chat_history":
                    self.set_dialogue("* Review conversation archives and sights from past sessions.\n* Press Enter or Z to inspect.")
                else:
                    self.set_dialogue(f"* Talk topic: {title}\n* Press Enter or Z to listen.")
            else:
                self.set_dialogue("* Return to the main parlour.")
        elif self.state == ShopState.CHAT_HISTORY_SESSIONS:
            if self._selected_index < len(self._session_summaries):
                sess = self._session_summaries[self._selected_index]
                seen_str = f"\n* Sights: {sess['seen_summary']}" if sess.get('seen_summary') else ""
                self.set_dialogue(f"* Timeline: {sess['label']}\n* {sess['turn_count']} dialogue turns.{seen_str}")
            else:
                self.set_dialogue("* Return to the talk topics menu.")

    def _confirm_selection(self) -> None:
        if self.state == ShopState.ROOT:
            if self._selected_index == 0:  # CHARACTER
                self.state = ShopState.CHARACTER
                self._selected_index = 0
                self.set_dialogue("* Characters are coming soon! Only one companion in this world for now.")
            elif self._selected_index == 1:  # TASKS & ALARMS
                self.state = ShopState.TASKS_SUBMENU
                self._selected_index = 0
                self.set_dialogue("* Sanctuary Tasks & Alarms Center.\n* What would you like to inspect, darling?")
            elif self._selected_index == 2:  # TALK
                self.state = ShopState.TALK_MENU
                self._selected_index = 0
                self.set_dialogue(CANON_TALK_ENTER)
            elif self._selected_index == 3:  # CONFIG & SETTINGS
                self.state = ShopState.SETTINGS_MENU
                self._selected_index = 0
                self.set_dialogue("* Sanctuary settings & permanent memory fact sheet.")
            elif self._selected_index == 4:  # EXIT
                self.close_shop()

        elif self.state == ShopState.TASKS_SUBMENU:
            if self._selected_index == 0:  # Goals
                self.state = ShopState.TASKS
                self._tasks_tab = 0
                self._selected_index = 0
                self._goals_scroll_offset = 0
                self.set_dialogue("* Target Milestones & Long-term Goals board.")
            elif self._selected_index == 1:  # Tasks
                self.state = ShopState.TASKS
                self._tasks_tab = 1
                self._selected_index = 0
                self._tasks_scroll_offset = 0
                self.set_dialogue("* Chores & Reminders board. Complete tasks for Pink Dollars!")
            elif self._selected_index == 2:  # Alarms (COMING SOON)
                self.set_dialogue("* (Under construction...)\n* Scheduled alarms are temporarily offline, minion!")
            elif self._selected_index == 3:  # Timers (COMING SOON)
                self.set_dialogue("* (Under construction...)\n* Focus timers are being rebuilt for the next version, darling!")
            else:  # Back
                self.state = ShopState.ROOT
                self._selected_index = 1
                self.set_dialogue(self._get_root_greeting())

        elif self.state == ShopState.CHARACTER:
            if self._selected_index == 0:
                self.set_dialogue("* That's me, darling! You are already equipped with Pink!")
            elif self._selected_index < 4:
                self.set_dialogue("* Other companions are still under construction, darling! Coming soon!")
            else:  # Back
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
                    self.state = ShopState.TASKS_SUBMENU
                    self._selected_index = self._tasks_tab
                    self.set_dialogue("* Sanctuary Tasks & Alarms Center.\n* What would you like to inspect, darling?")

            elif self._tasks_tab == 1:  # TASKS
                reminder_objs = self._get_active_reminder_objects()
                if self._selected_index == 0:
                    self._prompt_add_task()
                elif self._selected_index <= len(reminder_objs):
                    r_obj = reminder_objs[self._selected_index - 1]
                    task_text = r_obj.get("text", "")
                    self._open_item_action("task", task_text, r_obj)
                else:  # Back
                    self.state = ShopState.TASKS_SUBMENU
                    self._selected_index = self._tasks_tab
                    self.set_dialogue("* Sanctuary Tasks & Alarms Center.\n* What would you like to inspect, darling?")

            elif self._tasks_tab == 2:  # ALARMS
                alarms = self._get_scheduled_alarms()
                if self._selected_index == 0:
                    self._prompt_add_alarm()
                elif self._selected_index <= len(alarms):
                    alarm_item = alarms[self._selected_index - 1]
                    lbl = alarm_item.get("label", "Alarm")
                    self._open_item_action("alarm", lbl, alarm_item)
                else:  # Back
                    self.state = ShopState.TASKS_SUBMENU
                    self._selected_index = self._tasks_tab
                    self.set_dialogue("* Sanctuary Tasks & Alarms Center.\n* What would you like to inspect, darling?")

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
                    self.state = ShopState.TASKS_SUBMENU
                    self._selected_index = self._tasks_tab
                    self.set_dialogue("* Sanctuary Tasks & Alarms Center.\n* What would you like to inspect, darling?")

        elif self.state == ShopState.SETTINGS_MENU:
            if self._selected_index == 0:  # Pet Scale
                self._cycle_pet_scale(direction=1)
            elif self._selected_index == 1:  # Companion Toggles
                self.state = ShopState.TOGGLES_MENU
                self._selected_index = 0
                self.set_dialogue("* Toggle companion autonomous behaviors in real time.")
            elif self._selected_index == 2:  # Edit Facts
                self.state = ShopState.FACTS_EDIT
                self._selected_index = 0
                self._notes_scroll_offset = 0
                self.set_dialogue("* Permanent memory fact sheet & nickname manager.")
            elif self._selected_index == 3:  # Uninstall Pink
                if self._pet and hasattr(self._pet, "_handle_uninstall"):
                    self._pet._handle_uninstall()
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
                self._selected_index = 2
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
            elif self._selected_index == 2:  # Game Mode
                if self._pet and hasattr(self._pet, "_cycle_game_mode"):
                    new_mode = self._pet._cycle_game_mode()
                    if new_mode == "AUTO":
                        self.set_dialogue("* Game Mode: AUTO! I'll watch closely whenever you launch a game, mew!")
                    elif new_mode == "ON":
                        self.set_dialogue("* Game Mode: ON! Full gaming focus & backseat spectating active, darling!")
                    else:
                        self.set_dialogue("* Game Mode: OFF! Reverted to standard desktop pacing.")
                self.update()
            elif self._selected_index == 3:  # Bomb Mode
                if self._pet:
                    new_val = not getattr(self._pet, "_bomb_attack_enabled", False)
                    self._pet._toggle_bomb_attack(new_val)
                    state_str = "ARMED" if new_val else "DISARMED"
                    self.set_dialogue(f"* Cat-head bombs are now {state_str}, mew!")
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
                elif topic_key == "chat_history":
                    self._session_summaries = self._load_session_summaries()
                    self._sessions_scroll_offset = 0
                    self._selected_index = 0
                    self.state = ShopState.CHAT_HISTORY_SESSIONS
                    if self._session_summaries:
                        self.set_dialogue("* Desktop session archive. Pick a timeline to inspect!")
                    else:
                        self.set_dialogue("* No recorded session logs found yet, mew.")
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

        elif self.state == ShopState.CHAT_HISTORY_SESSIONS:
            if self._selected_index == len(self._session_summaries):
                self.state = ShopState.TALK_MENU
                chat_idx = next((i for i, (_, k) in enumerate(TALK_TOPICS) if k == "chat_history"), 0)
                self._selected_index = chat_idx
                self.set_dialogue(CANON_TALK_ENTER)
            elif self._selected_index < len(self._session_summaries):
                sess = self._session_summaries[self._selected_index]
                turns = self._prepare_session_turns(sess)
                if not turns:
                    self.set_dialogue("* That session was completely silent. Nothing was spoken, mew.")
                else:
                    self._history_view_turns = turns
                    self._history_turn_idx = 0
                    self.state = ShopState.CHAT_HISTORY_VIEW
                    self.set_dialogue("\n".join(self._history_view_turns[0]))

        elif self.state == ShopState.CHAT_HISTORY_VIEW:
            self._next_history_turn()

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

    def _cycle_pet_scale(self, direction: int = 1) -> None:
        if not self._pet or not hasattr(self._pet, "cycle_scale_modifier"):
            return
        new_scale = self._pet.cycle_scale_modifier(direction=direction)
        if new_scale <= 0.5:
            self.set_dialogue("* Tiny mode engaged! I'm smol but mighty, mew!")
        elif new_scale <= 0.75:
            self.set_dialogue("* Compact mode! Sleek and stealthy, darling!")
        elif new_scale <= 1.0:
            self.set_dialogue("* Standard scale restored! Just right, darling!")
        elif new_scale <= 1.25:
            self.set_dialogue("* Comfort mode! Easier on your eyes, mew!")
        elif new_scale <= 1.5:
            self.set_dialogue("* Large mode! Can you feel my overwhelming aura?")
        else:
            self.set_dialogue("* Giant mode active! Bow before my majestic presence, minion!")
        self.update()

    def _cancel_or_back(self) -> None:
        if self._input_container.isVisible():
            self._on_input_cancelled()
            return
        if self.state in (ShopState.CHARACTER, ShopState.TASKS_SUBMENU, ShopState.SETTINGS_MENU, ShopState.TALK_MENU):
            self.state = ShopState.ROOT
            self._selected_index = 0
            self.set_dialogue(self._get_root_greeting())
        elif self.state == ShopState.TASKS:
            self.state = ShopState.TASKS_SUBMENU
            self._selected_index = self._tasks_tab
            self.set_dialogue("* Sanctuary Tasks & Alarms Center.\n* What would you like to inspect, darling?")
        elif self.state in (ShopState.FACTS_EDIT, ShopState.TOGGLES_MENU):
            self.state = ShopState.SETTINGS_MENU
            self._selected_index = 1 if self.state == ShopState.TOGGLES_MENU else 2
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
        elif self.state == ShopState.CHAT_HISTORY_VIEW:
            self.state = ShopState.CHAT_HISTORY_SESSIONS
            self.set_dialogue("* Returned to session archive.")
        elif self.state == ShopState.CHAT_HISTORY_SESSIONS:
            self.state = ShopState.TALK_MENU
            chat_idx = next((i for i, (_, k) in enumerate(TALK_TOPICS) if k == "chat_history"), 0)
            self._selected_index = chat_idx
            self.set_dialogue(CANON_TALK_ENTER)
        elif self.state == ShopState.TALK_DIALOGUE:
            self.state = ShopState.TALK_MENU
            self.set_dialogue(CANON_TALK_ENTER)
        elif self.state == ShopState.ROOT:
            self.close_shop()
        self.update()

    def _start_exit(self) -> None:
        """Exit dialogue removed per user request: close shop immediately."""
        self.close_shop()

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
        elif self._input_mode == "edit_fact_note":
            old_text = self._inspect_item_text
            self._edit_fact_note(old_text, val)
            self._inspect_item_text = val
            self._note_scroll_offset = 0
            self.set_dialogue(f"* Fact note updated:\n* \"{val}\"")
            self.state = ShopState.FACTS_EDIT
            self.update()
        elif self._input_mode == "new_goal":
            self._add_goal(val)
            self.set_dialogue(f"* New target milestone logged:\n* \"{val}\"\n* Complete it to collect +P$ 000005!")
        elif self._input_mode == "new_task":
            if self._memory:
                self._memory.add_reminder(val)
            self.set_dialogue(f"* Task registered to chore board:\n* \"{val}\"\n* Finish it for Pink Dollars!")
        elif self._input_mode == "new_alarm":
            m = re.match(r"^(\d{1,2}(?::\d{2})?\s*(?:am|pm)?|\d{1,2}[:.]\d{2})\s*(.*)$", val, re.IGNORECASE)
            if m:
                time_str = m.group(1).strip()
                lbl = m.group(2).strip() or "Alarm"
            else:
                parts = val.split(" ", 1)
                time_str = parts[0].strip()
                lbl = parts[1].strip() if len(parts) > 1 else "Alarm"

            mem = self._memory or (self._pet._memory if self._pet and hasattr(self._pet, "_memory") else None)
            if mem and hasattr(mem, "add_alarm"):
                item = mem.add_alarm(time_str, lbl)
                if item:
                    self.set_dialogue(
                        f"* Calibrating chronometers and winding the pocket watch...\n"
                        f"* Clock alarm primed for {item.get('clock_time')} (\"{lbl}\")!\n"
                        f"* I will sound the bells right on schedule, minion!"
                    )
                else:
                    self.set_dialogue("* Format error: Use e.g. 08:30 AM Meeting or 14:30 Sync, dummy!")
            else:
                self.set_dialogue("* Alarm mechanism currently unavailable, mew!")
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

        # Submenu return in TASKS via Tab key
        if key == Qt.Key_Tab and self.state == ShopState.TASKS:
            self.state = ShopState.TASKS_SUBMENU
            self._selected_index = self._tasks_tab
            self.update()
            return

        if key in (Qt.Key_Up, Qt.Key_W):
            if self.state == ShopState.CHAT_HISTORY_VIEW:
                self._prev_history_turn()
                return
            self._nav_up()
        elif key in (Qt.Key_Down, Qt.Key_S):
            if self.state == ShopState.CHAT_HISTORY_VIEW:
                self._next_history_turn()
                return
            self._nav_down()
        elif key in (Qt.Key_Left, Qt.Key_A):
            if self.state == ShopState.CHAT_HISTORY_VIEW:
                self._prev_history_turn()
                return
            elif self.state == ShopState.SETTINGS_MENU and self._selected_index == 0:
                self._cycle_pet_scale(direction=-1)
                return
            elif self.state == ShopState.ITEM_ACTION and self._inspect_item_kind == "fact":
                self._inspect_choice_idx = (self._inspect_choice_idx - 1) % len(self._inspect_options)
                self.update()
                return
            elif self.state == ShopState.TASKS:
                self._tasks_tab = (self._tasks_tab - 1) % 2
                self._selected_index = 0
                self.update()
        elif key in (Qt.Key_Right, Qt.Key_D):
            if self.state == ShopState.CHAT_HISTORY_VIEW:
                self._next_history_turn()
                return
            elif self.state == ShopState.SETTINGS_MENU and self._selected_index == 0:
                self._cycle_pet_scale(direction=1)
                return
            elif self.state == ShopState.ITEM_ACTION and self._inspect_item_kind == "fact":
                self._inspect_choice_idx = (self._inspect_choice_idx + 1) % len(self._inspect_options)
                self.update()
                return
            elif self.state == ShopState.TASKS:
                self._tasks_tab = (self._tasks_tab + 1) % 2
                self._selected_index = 0
                self.update()
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Z, Qt.Key_Space):
            if self.state in (ShopState.TALK_DIALOGUE, ShopState.CHAT_HISTORY_VIEW) and self._is_typing():
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

            # 1. Dialogue skip typing without dismissing
            if self._is_dialogue_rect(pos_canvas):
                if self._is_typing():
                    self._finish_typing()
                    return
                elif self.state in (ShopState.TALK_DIALOGUE, ShopState.CHAT_HISTORY_VIEW):
                    self._confirm_selection()
                    return

            # 2. Single wide box inspection click (Note inspection actions)
            if self.state == ShopState.ITEM_ACTION and self._inspect_item_kind == "fact":
                # Check choices at bottom
                btn_idx = self._get_item_at_canvas_pos(pos_canvas)
                if btn_idx is not None:
                    self._inspect_choice_idx = btn_idx
                    self._confirm_item_action()
                    return

            # 3. Check scroll arrow clicks (left side at x: 365..405)
            if self.state in (ShopState.TASKS, ShopState.FACTS_EDIT, ShopState.TALK_MENU, ShopState.CHAT_HISTORY_SESSIONS):
                if 365 <= pos_canvas.x() <= 405:
                    if 265 <= pos_canvas.y() <= 310:
                        self._scroll_up()
                        return
                    elif 370 <= pos_canvas.y() <= 415:
                        self._scroll_down()
                        return

            # 4. Menu item selection & instant single-click execution
            clicked_idx = self._get_item_at_canvas_pos(pos_canvas)
            if clicked_idx is not None:
                self._selected_index = clicked_idx
                if self.state == ShopState.ITEM_ACTION:
                    self._inspect_choice_idx = clicked_idx
                self._confirm_selection()
                self.update()
                return

            # 5. Non-interactive canvas / backdrop area clicked -> Start dragging the shop window!
            self._drag_active = True
            self._drag_start_pos = event.globalPos() - self.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_active:
            self.setCursor(Qt.ClosedHandCursor)
            self.move(event.globalPos() - self._drag_start_pos)
            return

        pos_canvas = self._screen_to_canvas(event.pos())
        hover_idx = self._get_item_at_canvas_pos(pos_canvas)
        is_dialogue = self._is_dialogue_rect(pos_canvas)

        if hover_idx is not None:
            self.setCursor(Qt.PointingHandCursor)
            if hover_idx != self._selected_index:
                self._selected_index = hover_idx
                if self.state == ShopState.ITEM_ACTION:
                    self._inspect_choice_idx = hover_idx
                self._on_selection_changed()
                self.update()
        elif is_dialogue and (self._is_typing() or self.state in (ShopState.TALK_DIALOGUE, ShopState.CHAT_HISTORY_VIEW)):
            self.setCursor(Qt.PointingHandCursor)
        elif pos_canvas.y() < 240:
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def leaveEvent(self, event) -> None:
        if not self._drag_active:
            self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_active:
            self._drag_active = False
            pos_canvas = self._screen_to_canvas(event.pos())
            if pos_canvas.y() < 240 and pos_canvas.x() < 410:
                self.setCursor(Qt.OpenHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        self._drag_active = False

    def _screen_to_canvas(self, pt: QPoint) -> QPoint:
        x = round(pt.x() / self._scale)
        y = round(pt.y() / self._scale)
        return QPoint(x, y)

    def _get_item_at_canvas_pos(self, pt: QPoint) -> int | None:
        if self.state in (ShopState.TALK_DIALOGUE, ShopState.CHAT_HISTORY_VIEW):
            return None

        # Check scroll arrows for note enter in ITEM_ACTION (right side at x: 570..610)
        if self.state == ShopState.ITEM_ACTION and self._inspect_item_kind == "fact":
            if 570 <= pt.x() <= 610:
                if 260 <= pt.y() <= 310:
                    self._scroll_up()
                    return None
                elif 370 <= pt.y() <= 415:
                    self._scroll_down()
                    return None
            if 420 <= pt.y() <= 465:
                if 30 <= pt.x() <= 190:
                    return 0  # Edit Note
                elif 210 <= pt.x() <= 380:
                    return 1  # Delete Note
                elif 400 <= pt.x() <= 540:
                    return 2  # Back
            return None

        # Check scroll arrows for scrollable states (left side at x: 365..405)
        if self.state in (ShopState.TASKS, ShopState.FACTS_EDIT, ShopState.TALK_MENU, ShopState.CHAT_HISTORY_SESSIONS):
            if 365 <= pt.x() <= 405:
                if 265 <= pt.y() <= 310:
                    self._scroll_up()
                    return None
                elif 370 <= pt.y() <= 415:
                    self._scroll_down()
                    return None

        # Left-side submenus: start_x = 44, start_y = 283, line_h = 36
        if self.state in (ShopState.CHARACTER, ShopState.TASKS_SUBMENU, ShopState.TASKS,
                          ShopState.SETTINGS_MENU, ShopState.TOGGLES_MENU, ShopState.FACTS_EDIT,
                          ShopState.TALK_MENU, ShopState.CHAT_HISTORY_SESSIONS):
            if 20 <= pt.x() <= 400 and 265 <= pt.y() <= 465:
                row = (pt.y() - 265) // 36
                if 0 <= row < 5:
                    if self.state in (ShopState.CHARACTER, ShopState.TASKS_SUBMENU, ShopState.TOGGLES_MENU):
                        return row
                    elif self.state == ShopState.SETTINGS_MENU:
                        return row if row < 5 else None
                    elif self.state == ShopState.TASKS:
                        raw_len = self._get_menu_count() - 1
                        if row == 4:
                            return raw_len  # Back
                        off = [self._goals_scroll_offset, self._tasks_scroll_offset, self._alarms_scroll_offset, self._timers_scroll_offset][self._tasks_tab]
                        idx = off + row
                        return idx if idx < raw_len else None
                    elif self.state == ShopState.FACTS_EDIT:
                        raw_len = len(self._get_facts_menu_items())
                        if row == 4:
                            return raw_len  # Back
                        idx = self._notes_scroll_offset + row
                        return idx if idx < raw_len else None
                    elif self.state == ShopState.TALK_MENU:
                        topics_count = len(TALK_TOPICS) - 1
                        if row == 4:
                            return topics_count  # Back
                        idx = self._talk_scroll_offset + row
                        return idx if idx < topics_count else None
                    elif self.state == ShopState.CHAT_HISTORY_SESSIONS:
                        raw_len = len(self._session_summaries)
                        if row == 4:
                            return raw_len  # Back
                        idx = self._sessions_scroll_offset + row
                        return idx if idx < raw_len else None

        # Right-side menus: start_x = 444, start_y = 283, line_h = 36
        if self.state in (ShopState.ROOT, ShopState.ITEM_ACTION, ShopState.TASK_CONFIRM, ShopState.TASK_SECOND_CONFIRM):
            if 412 <= pt.x() <= 630 and 265 <= pt.y() <= 465:
                row = (pt.y() - 265) // 36
                if 0 <= row < 5:
                    if self.state == ShopState.ROOT:
                        return row
                    elif self.state == ShopState.ITEM_ACTION:
                        return row if row < len(self._inspect_options) else None
                    elif self.state in (ShopState.TASK_CONFIRM, ShopState.TASK_SECOND_CONFIRM):
                        return row if row < 2 else None

        return None

    # --- Painting & Rendering (Zero Allocations) -------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.SmoothPixmapTransform, False)
            p.scale(self._scale, self._scale)

            state_key = "root"
            if self.state in (ShopState.TALK_DIALOGUE, ShopState.CHAT_HISTORY_VIEW):
                state_key = "talk"
            elif self.state == ShopState.ITEM_ACTION and self._inspect_item_kind == "fact":
                state_key = "talk" 

            cached_frames = self._bg_cache[state_key]
            if cached_frames:
                frame = cached_frames[self._scene_frame_idx % len(cached_frames)]
                p.drawPixmap(0, 0, frame)

            if self.state == ShopState.ROOT:
                self._draw_root_state(p)
            elif self.state == ShopState.CHARACTER:
                self._draw_character_state(p)
            elif self.state == ShopState.TASKS_SUBMENU:
                self._draw_tasks_submenu_state(p)
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
            elif self.state in (ShopState.TALK_MENU, ShopState.TALK_DIALOGUE, ShopState.CHAT_HISTORY_SESSIONS, ShopState.CHAT_HISTORY_VIEW):
                self._draw_talk_state(p)


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
        # Left Submenu Options (Layout, margins, line_h=36, font matching sub menu.png)
        p.setFont(self._font_body)
        options = ["Pink (Equipped)", "(COMING SOON)", "(COMING SOON)", "(COMING SOON)", "Back"]
        start_x = 44
        start_y = 283
        line_h = 36

        for i, opt in enumerate(options):
            is_active = (i == self._selected_index)
            if is_active:
                color = QColor(255, 255, 0)
            elif i == 0 or i == 4:
                color = QColor(255, 255, 255)
            else:
                color = QColor(140, 140, 140)  # Dark white for COMING SOON
            p.setPen(color)
            p.drawText(start_x, start_y + i * line_h, opt)

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

        # Right Box: Vessel Description / Dialogue inside QRect(430, 269, 185, 175)
        p.setFont(self._font_body)
        p.setPen(QColor(255, 255, 255))
        if self._selected_index == 0:
            desc = "* Pink:\n* The quintessential cotton Mew Mew doll.\n* [EQUIPPED]"
        elif self._selected_index < 4:
            desc = "* (COMING SOON)\n* Tailoring in progress...\n* Check back in a future update!"
        else:
            desc = "* Return to the sanctuary main parlour."
        p.drawText(QRect(430, 269, 185, 175), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, desc)

        p.setFont(self._font_small)
        p.setPen(QColor(255, 180, 220))
        p.drawText(430, 459, f"P$ {self._wallet.pink_dollars:06d}")

    def _draw_tasks_submenu_state(self, p: QPainter) -> None:
        # Left Submenu Options (Layout, margins, line_h=36, font matching sub menu.png)
        p.setFont(self._font_body)
        options = ["Goals", "Tasks", "Alarms (COMING SOON)", "Timers (COMING SOON)", "Back"]
        start_x = 44
        start_y = 283
        line_h = 36

        for i, opt in enumerate(options):
            is_active = (i == self._selected_index)
            if is_active:
                color = QColor(255, 255, 0)
            elif i in (2, 3):
                color = QColor(140, 140, 140)  # Dark white for COMING SOON
            else:
                color = QColor(255, 255, 255)
            p.setPen(color)
            p.drawText(start_x, start_y + i * line_h, opt)

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

        # Right Box: Submenu Dialogue inside QRect(430, 269, 185, 175)
        p.setFont(self._font_body)
        p.setPen(QColor(255, 255, 255))
        if self._selected_index == 0:
            desc = "* Goals Board:\n* Target milestones.\n* Pink awards P$ 03 - P$ 08 per goal!"
        elif self._selected_index == 1:
            desc = "* Chore Board:\n* Daily tasks.\n* Complete chores for Pink Dollars!"
        elif self._selected_index == 2:
            desc = "* Alarms (COMING SOON):\n* Scheduled alarms are temporarily offline for maintenance."
        elif self._selected_index == 3:
            desc = "* Timers (COMING SOON):\n* Focus timers are being rebuilt for the next version, darling!"
        else:
            desc = "* Return to the sanctuary main parlour."
        p.drawText(QRect(430, 269, 185, 175), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, desc)

        p.setFont(self._font_small)
        p.setPen(QColor(255, 180, 220))
        p.drawText(430, 459, f"P$ {self._wallet.pink_dollars:06d}")

    def _draw_tasks_and_alarms_state(self, p: QPainter) -> None:
        # Left Submenu Options (Layout, margins, line_h=36, font matching sub menu.png)
        p.setFont(self._font_body)
        start_x = 44
        start_y = 283
        line_h = 36

        if self._tasks_tab == 0:
            raw_list = ["[+ Add New Goal]"] + self._get_goals()
            scroll_off = self._goals_scroll_offset
        else:
            raw_list = ["[+ Add New Task]"] + self._get_active_reminders()
            scroll_off = self._tasks_scroll_offset

        visible_items = raw_list[scroll_off : scroll_off + 4]

        for r_idx, label in enumerate(visible_items):
            actual_idx = scroll_off + r_idx
            is_active = (actual_idx == self._selected_index)
            color = QColor(255, 255, 0) if is_active else (QColor(170, 255, 230) if actual_idx == 0 else QColor(255, 255, 255))
            p.setPen(color)
            display_str = label
            if len(display_str) > 26:
                display_str = display_str[:25] + "..."
            p.drawText(start_x, start_y + r_idx * line_h, display_str)

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + r_idx * line_h - 13, self._soul_heart)

        back_idx = len(raw_list)
        is_back = (self._selected_index == back_idx)
        color = QColor(255, 255, 0) if is_back else QColor(255, 255, 255)
        p.setPen(color)
        p.drawText(start_x, start_y + 4 * line_h, "Back")
        if is_back and self._soul_heart:
            p.drawPixmap(start_x - 24, start_y + 4 * line_h - 13, self._soul_heart)

        # Scroll indicators
        p.setFont(self._font_small)
        p.setPen(QColor(255, 255, 0))
        if scroll_off > 0:
            p.drawText(380, 283, "▲")
        if scroll_off + 4 < len(raw_list):
            p.drawText(380, 391, "▼")

        # Right Box: Item details & Valuation preview inside QRect(430, 269, 185, 175)
        p.setFont(self._font_body)
        p.setPen(QColor(255, 255, 255))
        if self._selected_index == 0:
            if self._dialogue_text and ("finished!" in self._dialogue_text or "MINE now" in self._dialogue_text):
                desc = self._dialogue_text
            elif self._tasks_tab == 0:
                desc = "* Register a new personal goal into your log!"
            else:
                desc = "* Register a new chore to complete for Pink Dollars!"
        elif 1 <= self._selected_index <= len(raw_list) - 1:
            item_text = raw_list[self._selected_index]
            if self._tasks_tab == 0:
                val = self.evaluate_goal_value(item_text)
                desc = f"* Goal:\n* \"{item_text}\"\n* Valuation: +P$ {val:02d}\n* [Click to inspect]"
            else:
                val = evaluate_task_value(item_text)
                desc = f"* Task:\n* \"{item_text}\"\n* Valuation: +P$ {val:02d}\n* [Click to inspect]"
        else:
            desc = "* Return to Tasks & Alarms menu."
        p.drawText(QRect(430, 269, 185, 175), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, desc)

        p.setFont(self._font_small)
        p.setPen(QColor(255, 180, 220))
        p.drawText(430, 459, f"P$ {self._wallet.pink_dollars:06d}")

    def _draw_settings_menu_state(self, p: QPainter) -> None:
        p.setFont(self._font_body)
        cur_scale = getattr(self._pet, "_scale_modifier", 1.0) if self._pet else 1.0
        scale_str = f"{cur_scale:.2f}x" if cur_scale != round(cur_scale) else f"{cur_scale:.1f}x"
        options = [
            f"Pet Scale: [{scale_str}]",
            "Companion Toggles",
            "Edit Facts & Nickname",
            "Uninstall Pink 🗑️",
            "Back",
        ]
        start_x = 44
        start_y = 283
        line_h = 36

        for i, opt in enumerate(options):
            is_active = (i == self._selected_index)
            color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
            p.setPen(color)
            p.drawText(start_x, start_y + i * line_h, opt)

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

        # Right Box: Dialogue inside QRect(430, 269, 185, 175)
        p.setFont(self._font_body)
        p.setPen(QColor(255, 255, 255))
        if self._selected_index == 0:
            desc = (
                f"* Pet Scale:\n"
                f"* Current: {scale_str}\n"
                f"* [Click/Enter or Left/Right arrows to resize Pink]"
            )
        elif self._selected_index == 1:
            desc = "* Companion Toggles:\n* Live toggles for speech, music reactions, and defenses."
        elif self._selected_index == 2:
            notes = self._get_fact_notes()
            desc = f"* Fact Sheet:\n* Notes stored: {len(notes)}\n* Pink remembers your nickname and notes permanently."
        elif self._selected_index == 3:
            desc = "* Uninstall Pink:\n* Launch the Windows uninstaller or clean local pet data."
        else:
            desc = "* Return to sanctuary main parlour."
        p.drawText(QRect(430, 269, 185, 175), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, desc)

        p.setFont(self._font_small)
        p.setPen(QColor(255, 180, 220))
        p.drawText(430, 459, f"P$ {self._wallet.pink_dollars:06d}")

    def _draw_toggles_menu_state(self, p: QPainter) -> None:
        dlg_on = getattr(self._pet, "_dialogue_enabled", True) if self._pet else True
        song_on = getattr(self._pet, "_ai_song_comment_enabled", True) if self._pet else True
        game_mode = getattr(self._pet, "_game_mode", "AUTO") if self._pet else "AUTO"
        bomb_on = getattr(self._pet, "_bomb_attack_enabled", False) if self._pet else False

        p.setFont(self._font_body)
        options = [
            f"Dialogue: [{'ON' if dlg_on else 'OFF'}]",
            f"Song React: [{'ON' if song_on else 'OFF'}]",
            f"Game Mode: [{game_mode}]",
            f"Bomb Attack: [{'ON' if bomb_on else 'OFF'}]",
            "Back",
        ]
        start_x = 44
        start_y = 283
        line_h = 36

        for i, opt in enumerate(options):
            is_active = (i == self._selected_index)
            color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
            p.setPen(color)
            p.drawText(start_x, start_y + i * line_h, opt)

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

        # Right Box: Dialogue inside QRect(430, 269, 185, 175)
        descriptions = [
            "* Toggle speech bubbles and reactions on desktop.",
            "* Toggle AI commentary on currently playing music.",
            "* Auto-detect video games for faster screen commentary & backseat catgirl banter.",
            "* Toggle feline explosive defense behavior.",
            "* Return to sanctuary settings.",
        ]
        desc = descriptions[self._selected_index] if 0 <= self._selected_index < len(descriptions) else ""
        p.setFont(self._font_body)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRect(430, 269, 185, 175), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, desc)

        p.setFont(self._font_small)
        p.setPen(QColor(255, 180, 220))
        p.drawText(430, 459, f"P$ {self._wallet.pink_dollars:06d}")

    def _draw_facts_edit_state(self, p: QPainter) -> None:
        p.setFont(self._font_body)
        start_x = 44
        start_y = 283
        line_h = 36

        raw_list = self._get_facts_menu_items()
        scroll_off = self._notes_scroll_offset
        visible_items = raw_list[scroll_off : scroll_off + 4]

        for r_idx, label in enumerate(visible_items):
            actual_idx = scroll_off + r_idx
            is_active = (actual_idx == self._selected_index)
            color = QColor(255, 255, 0) if is_active else (QColor(170, 255, 230) if actual_idx < 2 else QColor(255, 255, 255))
            p.setPen(color)
            display_str = label
            if len(display_str) > 26:
                display_str = display_str[:25] + "..."
            p.drawText(start_x, start_y + r_idx * line_h, display_str)

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + r_idx * line_h - 13, self._soul_heart)

        back_idx = len(raw_list)
        is_back = (self._selected_index == back_idx)
        color = QColor(255, 255, 0) if is_back else QColor(255, 255, 255)
        p.setPen(color)
        p.drawText(start_x, start_y + 4 * line_h, "Back")
        if is_back and self._soul_heart:
            p.drawPixmap(start_x - 24, start_y + 4 * line_h - 13, self._soul_heart)

        # Scroll indicators
        p.setFont(self._font_small)
        p.setPen(QColor(255, 255, 0))
        if scroll_off > 0:
            p.drawText(380, 283, "▲")
        if scroll_off + 4 < len(raw_list):
            p.drawText(380, 391, "▼")

        # Right Box: Dialogue preview inside QRect(430, 269, 185, 175)
        p.setFont(self._font_body)
        p.setPen(QColor(255, 255, 255))
        notes = self._get_fact_notes()
        if self._selected_index == 0:
            desc = f"* Nickname Manager:\n* Current: \"{self._get_user_name()}\"\n* Pink addresses you by this moniker."
        elif self._selected_index == 1:
            desc = "* Inscribe a new permanent fact note into Pink's memory logs."
        elif 2 <= self._selected_index < len(notes) + 2:
            n_text = notes[self._selected_index - 2]
            desc = f"* Note #{self._selected_index - 1}:\n* \"{n_text}\"\n* [Click to open & edit]"
        else:
            desc = "* Return to sanctuary settings."
        p.drawText(QRect(430, 269, 185, 175), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, desc)

        p.setFont(self._font_small)
        p.setPen(QColor(255, 180, 220))
        p.drawText(430, 459, f"P$ {self._wallet.pink_dollars:06d}")

    def _draw_talk_state(self, p: QPainter) -> None:
        if self.state == ShopState.TALK_MENU:
            # Left Box: Topics (Layout matching talk inside or submenu.png)
            p.setFont(self._font_body)
            start_x = 44
            start_y = 283
            line_h = 36

            topics_without_back = TALK_TOPICS[:-1]
            scroll_off = self._talk_scroll_offset
            visible_topics = topics_without_back[scroll_off : scroll_off + 4]

            for r_idx, (t_title, _) in enumerate(visible_topics):
                actual_idx = scroll_off + r_idx
                is_active = (actual_idx == self._selected_index)
                color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
                p.setPen(color)
                display_str = t_title
                if len(display_str) > 26:
                    display_str = display_str[:25] + "..."
                p.drawText(start_x, start_y + r_idx * line_h, display_str)

                if is_active and self._soul_heart:
                    p.drawPixmap(start_x - 24, start_y + r_idx * line_h - 13, self._soul_heart)

            back_idx = len(topics_without_back)
            is_back = (self._selected_index == back_idx)
            color = QColor(255, 255, 0) if is_back else QColor(255, 255, 255)
            p.setPen(color)
            p.drawText(start_x, start_y + 4 * line_h, "Back")
            if is_back and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + 4 * line_h - 13, self._soul_heart)

            # Scroll indicators
            p.setFont(self._font_small)
            p.setPen(QColor(255, 255, 0))
            if scroll_off > 0:
                p.drawText(380, 283, "▲")
            if scroll_off + 4 < len(topics_without_back):
                p.drawText(380, 391, "▼")

            # Right Box: Dialogue preview inside QRect(430, 269, 185, 175)
            p.setFont(self._font_body)
            p.setPen(QColor(255, 255, 255))
            if self._selected_index < len(topics_without_back):
                t_title, _ = topics_without_back[self._selected_index]
                desc = f"* Serious Inquiry:\n* \"{t_title}\"\n* [Press Enter or click to listen]"
            else:
                desc = "* Return to the sanctuary main parlour."
            p.drawText(QRect(430, 269, 185, 175), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, desc)

            p.setFont(self._font_small)
            p.setPen(QColor(255, 180, 220))
            p.drawText(430, 459, f"P$ {self._wallet.pink_dollars:06d}")

        elif self.state == ShopState.CHAT_HISTORY_SESSIONS:
            # Left Box: Session items list
            p.setFont(self._font_body)
            start_x = 44
            start_y = 283
            line_h = 36

            total_sessions = len(self._session_summaries)
            scroll_off = self._sessions_scroll_offset
            visible_sessions = self._session_summaries[scroll_off : scroll_off + 4]

            for r_idx, sess in enumerate(visible_sessions):
                actual_idx = scroll_off + r_idx
                is_active = (actual_idx == self._selected_index)
                color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
                p.setPen(color)

                title = sess.get("label", "Session")
                turn_count = sess.get("turn_count", 0)
                display_str = title
                if len(display_str) > 20:
                    display_str = display_str[:19] + ".."
                p.drawText(start_x, start_y + r_idx * line_h, display_str)

                # Turn count badge
                p.setFont(self._font_small)
                p.setPen(QColor(157, 162, 196) if not is_active else QColor(255, 255, 120))
                p.drawText(start_x + 230, start_y + r_idx * line_h, f"{turn_count}t")
                p.setFont(self._font_body)

                if is_active and self._soul_heart:
                    p.drawPixmap(start_x - 24, start_y + r_idx * line_h - 13, self._soul_heart)

            # Row 4: Back
            back_idx = total_sessions
            is_back = (self._selected_index == back_idx)
            color = QColor(255, 255, 0) if is_back else QColor(255, 255, 255)
            p.setPen(color)
            p.drawText(start_x, start_y + 4 * line_h, "Back")
            if is_back and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + 4 * line_h - 13, self._soul_heart)

            # Scroll indicators
            p.setFont(self._font_small)
            p.setPen(QColor(255, 255, 0))
            if scroll_off > 0:
                p.drawText(380, 283, "▲")
            if scroll_off + 4 < total_sessions:
                p.drawText(380, 391, "▼")

            # Right Box: Session preview inside QRect(430, 269, 185, 175)
            p.setFont(self._font_body)
            p.setPen(QColor(255, 255, 255))
            if self._selected_index < total_sessions:
                sess = self._session_summaries[self._selected_index]
                label = sess.get("label", "Session")
                turn_count = sess.get("turn_count", 0)
                seen = sess.get("seen_summary", "")
                seen_line = f"\n* Sights: {seen}" if seen else ""
                desc = f"* {label}\n* ({turn_count} turns){seen_line}\n* [Enter to read]"
            else:
                desc = "* Return to the talk topics menu."
            p.drawText(QRect(430, 269, 185, 175), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, desc)

            p.setFont(self._font_small)
            p.setPen(QColor(255, 180, 220))
            p.drawText(430, 459, f"P$ {self._wallet.pink_dollars:06d}")

        elif self.state == ShopState.CHAT_HISTORY_VIEW:
            self._draw_dialogue_text(p, QRect(36, 271, 568, 175))
            p.setFont(self._font_small)
            p.setPen(QColor(157, 162, 196))
            total_t = len(self._history_view_turns)
            cur_t = self._history_turn_idx + 1 if total_t > 0 else 0
            p.drawText(QRect(36, 450, 568, 20), Qt.AlignRight | Qt.AlignVCenter, f"Turn {cur_t}/{total_t}  [◄/► Browse | Esc: Back]")

        elif self.state == ShopState.TALK_DIALOGUE:
            self._draw_dialogue_text(p, QRect(36, 271, 568, 175))
            p.setFont(self._font_small)
            p.setPen(QColor(157, 162, 196))
            p.drawText(530, 456, "[Z / Esc]")

    def _draw_item_action_state(self, p: QPainter) -> None:
        if self._inspect_item_kind == "fact":
            # Single wide talk box layout (matching talk.png)
            p.setFont(self._font_body)
            p.setPen(QColor(255, 255, 255))
            fm = p.fontMetrics()
            line_h = fm.height() + 4

            raw_text = self._inspect_item_text
            if not raw_text.startswith("* "):
                raw_text = "* " + raw_text

            wrapped_lines: list[str] = []
            for para in raw_text.split("\n"):
                words = para.split(" ")
                cur: list[str] = []
                for w in words:
                    test = " ".join(cur + [w])
                    if cur and fm.horizontalAdvance(test) > 540:
                        wrapped_lines.append(" ".join(cur))
                        cur = ["  " + w] if para.startswith("* ") else [w]
                    else:
                        cur.append(w)
                if cur:
                    wrapped_lines.append(" ".join(cur))

            visible_count = 4
            max_scroll = max(0, len(wrapped_lines) - visible_count)
            self._note_scroll_offset = max(0, min(self._note_scroll_offset, max_scroll))

            start_y = 275
            for l_idx, line in enumerate(wrapped_lines[self._note_scroll_offset : self._note_scroll_offset + visible_count]):
                p.drawText(36, start_y + l_idx * line_h, line)

            # Scroll indicators on right
            p.setFont(self._font_small)
            p.setPen(QColor(255, 255, 0))
            if self._note_scroll_offset > 0:
                p.drawText(586, 275, "▲")
            if self._note_scroll_offset + visible_count < len(wrapped_lines):
                p.drawText(586, 385, "▼")

            # Horizontal action choice buttons at bottom
            p.setFont(self._font_body)
            btn_y = 438
            buttons = [
                (50, "Edit Note"),
                (240, "Delete Note"),
                (430, "Back"),
            ]
            for b_idx, (bx, blabel) in enumerate(buttons):
                is_active = (b_idx == self._inspect_choice_idx)
                color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
                p.setPen(color)
                p.drawText(bx, btn_y, f"[ {blabel} ]")
                if is_active and self._soul_heart:
                    p.drawPixmap(bx - 22, btn_y - 13, self._soul_heart)

        else:
            # Goals / Tasks inspection: 2-box HUD (matching menu.png layout)
            # Left Box: Dialogue text
            self._draw_dialogue_text(p, QRect(32, 269, 355, 185))

            # Right Box: Action Choices at start_x=444, start_y=283, line_h=36
            p.setFont(self._font_body)
            start_x = 444
            start_y = 283
            line_h = 36

            for i, opt in enumerate(self._inspect_options):
                is_active = (i == self._inspect_choice_idx)
                color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
                p.setPen(color)
                p.drawText(start_x, start_y + i * line_h, opt)

                if is_active and self._soul_heart:
                    p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

            p.setFont(self._font_small)
            p.setPen(QColor(255, 180, 220))
            p.drawText(430, 459, f"P$ {self._wallet.pink_dollars:06d}")

    def _draw_task_confirm_state(self, p: QPainter) -> None:
        self._draw_dialogue_text(p, QRect(32, 269, 355, 185))

        p.setFont(self._font_body)
        options = ["CLAIM REWARD", "CANCEL"]
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

    def _draw_task_second_confirm_state(self, p: QPainter) -> None:
        self._draw_dialogue_text(p, QRect(32, 269, 355, 185))

        p.setFont(self._font_body)
        options = ["I REALLY DID!", "...CAUGHT ME"]
        start_x = 444
        start_y = 283
        line_h = 36

        for i, opt in enumerate(options):
            is_active = (i == self._selected_index)
            color = QColor(255, 64, 64) if (is_active and i == 1) else (QColor(255, 255, 0) if is_active else QColor(255, 255, 255))
            p.setPen(color)
            p.drawText(start_x, start_y + i * line_h, opt)

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

        p.setFont(self._font_small)
        p.setPen(QColor(255, 180, 220))
        p.drawText(430, 459, f"P$ {self._wallet.pink_dollars:06d}")
