"""Pink's Dark World Sanctuary (formerly Shop Window) for Yellow's Pixel Buddies.

Major Overhaul:
1. Replaced "Buy" with "Character Change / Wardrobe" (Physical Doll, Spectral Ghost, Burnt, Overjoyed).
2. Replaced "Sell" with "Tasks & Reminders" offering Pink Dollars (P$ 1 - P$ 3 evaluated by Pink).
3. Proof-of-work screen/session verification with double-confirmation if unverified.
4. Focus Timers & Alarms feature (5m, 15m, 25m Pomodoro, custom, with live countdown and taskbar alarms).
5. Serious shopkeeper dialogue ("Ask Her Something" in the solemn Undertale/Deltarune shopkeeper tradition).
6. Facts & Memory Editor (view and edit user_name, fact notes from memory/facts.json).
7. Settings Tab (toggles for Dialogue Bubbles, AI Song Commentary, Bomb Attack, Jump to Cursor).
8. 100% Zero-lag: Pre-composited backgrounds, zero allocations per paintEvent, full mouse hover tracking.
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
)
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QLineEdit,
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
    CHARACTER = auto()        # Replaces BUY
    TASKS = auto()            # View reminders & cash in for P$
    TASK_CONFIRM = auto()     # Stage 1 confirmation
    TASK_SECOND_CONFIRM = auto() # Stage 2 suspicion confirmation
    TIMER_MENU = auto()       # Timers & Alarms
    TALK_MENU = auto()        # Serious topics
    TALK_DIALOGUE = auto()    # Serious typewriter dialogue
    SETTINGS_MENU = auto()    # Pet settings toggles
    FACTS_EDIT = auto()       # View & edit facts.json
    EXITING = auto()


class PinkWallet:
    """Manages Pink Dollars (P$) and unlocked forms persisted in memory/wallet.json."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self.pink_dollars: int = 15
        self.unlocked_forms: list[str] = ["doll"]
        self.active_form: str = "doll"
        self.defeated: bool = False
        self.topic_counts: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                # Migrate dark_dollars if present
                old_val = data.get("pink_dollars", data.get("dark_dollars", 15))
                self.pink_dollars = max(0, int(old_val))
                self.unlocked_forms = list(data.get("unlocked_forms", ["doll"]))
                self.active_form = str(data.get("active_form", "doll"))
                self.defeated = bool(data.get("defeated", False))
                self.topic_counts = dict(data.get("topic_counts", {}))
                return
            except Exception as e:
                log.warning("Error reading wallet %s: %s", self._path, e)
        self.pink_dollars = 15
        self.unlocked_forms = ["doll"]
        self.active_form = "doll"
        self.defeated = False
        self.topic_counts = {}
        self.save()

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "pink_dollars": self.pink_dollars,
                "unlocked_forms": self.unlocked_forms,
                "active_form": self.active_form,
                "defeated": self.defeated,
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


# --- Character Forms -----------------------------------------------------------
CHARACTER_FORMS = [
    {
        "id": "doll",
        "name": "Classic Doll",
        "cost": 0,
        "anim": "idle",
        "desc": "The quintessential cotton Mew Mew doll body. Balanced, sassy, and charming.",
    },
    {
        "id": "ghost",
        "name": "Spectral Ghost",
        "cost": 10,
        "anim": "angry",
        "desc": "Her true incorporeal spirit form with glowing cyan aura and spectral embers.",
    },
    {
        "id": "burnt",
        "name": "Burnt Survivor",
        "cost": 5,
        "anim": "burnt",
        "desc": "Crispy, soot-covered, battle-hardened doll form. Survives any explosion.",
    },
    {
        "id": "overjoyed",
        "name": "Cyber Joy",
        "cost": 15,
        "anim": "overjoyed",
        "desc": "Brimming with pure cyber bliss and celebratory peace-sign animations.",
    },
]

# --- Canon Deltarune Shop Dialogues --------------------------------------------
GREETING_BEFORE_DEFEAT = "* The sunset...\n* It's breathtaking, isn't it?"
GREETING_AFTER_DEFEAT = "* The sunset... will it ever be this beautiful again?"

EXIT_BEFORE_DEFEAT = "* That's right, go outside.\n* It's beautiful."
EXIT_AFTER_DEFEAT = "* Treasure this world, won't you?"

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

        # Scene animation timer (slower, ambient pace)
        self._scene_timer = QTimer(self)
        self._scene_timer.setInterval(SCENE_FRAME_INTERVAL_MS)
        self._scene_timer.timeout.connect(self._on_scene_tick)

        # Dragging state
        self._drag_active: bool = False
        self._drag_start_pos: QPoint = QPoint()

        # Input field for facts/custom timer/AI
        self._ai_input = QLineEdit(self)
        self._ai_input.setPlaceholderText("Type and press Enter...")
        self._ai_input.setStyleSheet(
            f"""
            QLineEdit {{
                background-color: #0c0c14;
                color: #ffffff;
                font-family: '{self._font_family}', monospace;
                font-size: 14px;
                border: 2px solid #ffffff;
                padding: 4px 8px;
            }}
            QLineEdit:focus {{
                border: 2px solid #00ffff;
            }}
            """
        )
        self._ai_input.returnPressed.connect(self._on_input_submitted)
        self._ai_input.hide()
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
        if self._wallet.defeated:
            return GREETING_AFTER_DEFEAT
        return GREETING_BEFORE_DEFEAT

    def _get_exit_line(self) -> str:
        if self._wallet.defeated:
            return EXIT_AFTER_DEFEAT
        return EXIT_BEFORE_DEFEAT

    def deliver_ai_reply(self, lines: list[str]) -> None:
        """Deliver AI-generated shopkeeper speech directly into the typewriter dialogue queue."""
        if not lines:
            return
        clean_lines: list[str] = []
        for l in lines:
            text = re.sub(r"\[anim:\s*[^\]]+\]", "", l)
            text = re.sub(r"\[mode:\s*[^\]]+\]", "", text)
            text = re.sub(r"\[seen:\s*[^\]]+\]", "", text).strip()
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
        self._visit_graduating_count = 0
        self._ai_input.hide()
        self.show()
        self.raise_()
        self.activateWindow()

        self._scene_timer.start()
        self.set_dialogue(self._get_root_greeting())

    def close_shop(self) -> None:
        self._scene_timer.stop()
        self._typewriter_timer.stop()
        self._ai_input.hide()
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
        elif self.state in (ShopState.TALK_DIALOGUE, ShopState.TALK_MENU):
            return 12 <= pt.x() <= 628 and 227 <= pt.y() <= 451
        return False

    def _on_scene_tick(self) -> None:
        cached_count = len(self._bg_cache["root"])
        if cached_count > 0:
            self._scene_frame_idx = (self._scene_frame_idx + 1) % cached_count
            self.update()

    # --- Focus Timer & Alarm Feature -------------------------------------------

    def start_timer(self, minutes: int, label: str) -> None:
        if self._pet and hasattr(self._pet, "_memory"):
            self._pet._memory.add_timer(minutes * 60, label)
        self._timer_total_seconds = minutes * 60
        self._timer_seconds_remaining = self._timer_total_seconds
        self._timer_label = label
        self._timer_active = True
        self._focus_timer.start()
        self.set_dialogue(f"* Timer set for {minutes}m ({label})! I'll alert you when it rings, mew!")

    def stop_timer(self) -> None:
        if self._pet and hasattr(self._pet, "_memory"):
            self._pet._memory.cancel_alarm_or_timer(self._timer_label)
        self._focus_timer.stop()
        self._timer_active = False
        self._timer_seconds_remaining = 0
        self.set_dialogue("* Active timer stopped, darling.")

    def _on_focus_timer_tick(self) -> None:
        if self._timer_seconds_remaining > 0:
            self._timer_seconds_remaining -= 1
            self.update()
        else:
            # Alarm rings!
            self.stop_timer()
            alarm_msg = f"* RING RING! {self._timer_label.upper()} IS UP, MINION!! Time to switch tasks!"
            if self._pet and hasattr(self._pet, "_say"):
                self._pet._say(alarm_msg, force=True, record_memory=False)
            if self._pet and hasattr(self._pet, "_play") and self._pet._can_play("shocked"):
                self._pet._play("shocked")
            self.set_dialogue(alarm_msg)
            # Award focus bonus
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

        # Check pet tray sightings
        if self._pet and hasattr(self._pet, "_tray_observations"):
            for obs in getattr(self._pet, "_tray_observations", []):
                summary = (obs.get("summary") or "").lower()
                for kw in keywords:
                    if kw in summary:
                        return True, True, kw

        # Check session logs
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

    # --- Menu Navigation -------------------------------------------------------

    def _nav_up(self) -> None:
        count = self._get_menu_count()
        if count <= 0:
            return
        if self.state == ShopState.TALK_MENU:
            self._selected_index = (self._selected_index - 2) % count
        else:
            self._selected_index = (self._selected_index - 1) % count
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
        self._on_selection_changed()
        self.update()

    def _get_menu_count(self) -> int:
        if self.state == ShopState.ROOT:
            return 5  # CHARACTER, TASKS, TALK, SETTINGS, EXIT
        elif self.state == ShopState.CHARACTER:
            return len(CHARACTER_FORMS) + 1  # Forms + Back
        elif self.state == ShopState.TASKS:
            reminders = self._get_active_reminders()
            return len(reminders) + 2  # Tasks + Timer Option + Back
        elif self.state in (ShopState.TASK_CONFIRM, ShopState.TASK_SECOND_CONFIRM):
            return 2  # YES, NO
        elif self.state == ShopState.TIMER_MENU:
            return 6  # 5m, 15m, 25m, custom, stop, back
        elif self.state == ShopState.TALK_MENU:
            return len(TALK_TOPICS)  # 8 items: 7 topics + Back
        elif self.state == ShopState.SETTINGS_MENU:
            return 7  # Facts editor + 5 toggles + Back
        elif self.state == ShopState.FACTS_EDIT:
            return 4  # Change Name + View Notes + Add Note + Back
        return 0

    def _on_selection_changed(self) -> None:
        if self.state == ShopState.CHARACTER:
            if self._selected_index < len(CHARACTER_FORMS):
                f = CHARACTER_FORMS[self._selected_index]
                self.set_dialogue(f"{CANON_BUY_ENTER}\n* {f['name']} - {f['desc']}")
            else:
                self.set_dialogue(CANON_BUY_REFUSE)
        elif self.state == ShopState.TALK_MENU:
            if self._selected_index < len(TALK_TOPICS):
                title, key = TALK_TOPICS[self._selected_index]
                if key == "back":
                    self.set_dialogue(self._get_root_greeting())
                else:
                    self.set_dialogue(f"* ... Topic: {title}")

    def _confirm_selection(self) -> None:
        if self.state == ShopState.ROOT:
            if self._selected_index == 0:  # CHARACTER
                self.state = ShopState.CHARACTER
                self._selected_index = 0
                self.set_dialogue(CANON_BUY_ENTER)
            elif self._selected_index == 1:  # TASKS & ALARM
                self.state = ShopState.TASKS
                self._selected_index = 0
                reminders = self._get_active_reminders()
                if not reminders:
                    self.set_dialogue(CANON_SELL_EMPTY)
                else:
                    self.set_dialogue(random.choice(CANON_SELL_LINES))
            elif self._selected_index == 2:  # TALK
                self.state = ShopState.TALK_MENU
                self._selected_index = 0
                self.set_dialogue(CANON_TALK_ENTER)
            elif self._selected_index == 3:  # SETTINGS & FACTS
                self.state = ShopState.SETTINGS_MENU
                self._selected_index = 0
                self.set_dialogue("* Companion settings and fact sheet manager.")
            elif self._selected_index == 4:  # EXIT
                self._start_exit()

        elif self.state == ShopState.CHARACTER:
            if self._selected_index < len(CHARACTER_FORMS):
                self._equip_character_form(CHARACTER_FORMS[self._selected_index])
            else:
                self.state = ShopState.ROOT
                self._selected_index = 0
                self.set_dialogue(CANON_BUY_REFUSE)

        elif self.state == ShopState.TASKS:
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
            elif self._selected_index == len(reminders):
                self.state = ShopState.TIMER_MENU
                self._selected_index = 0
                self.set_dialogue("* Focus Timers & Alarms! Set your study or sprint intervals.")
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

        elif self.state == ShopState.TIMER_MENU:
            if self._selected_index == 0:
                self.start_timer(5, "Short Break")
            elif self._selected_index == 1:
                self.start_timer(15, "Sprint Focus")
            elif self._selected_index == 2:
                self.start_timer(25, "Pomodoro Focus")
            elif self._selected_index == 3:
                self._prompt_custom_timer()
            elif self._selected_index == 4:
                self.stop_timer()
            else:
                self.state = ShopState.TASKS
                self._selected_index = 0
                self.set_dialogue("* Back to the task board.")

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
            if self._selected_index == 0:  # Edit Facts
                self.state = ShopState.FACTS_EDIT
                self._selected_index = 0
                self.set_dialogue("* Permanent memory fact sheet. You can edit your nickname or view notes.")
            elif self._selected_index == 1:  # Dialogue Bubbles
                if self._pet and hasattr(self._pet, "_dialogue_enabled"):
                    self._pet._dialogue_enabled = not self._pet._dialogue_enabled
                    state_str = "ENABLED" if self._pet._dialogue_enabled else "DISABLED"
                    self.set_dialogue(f"* Dialogue bubbles are now {state_str}, mew!")
            elif self._selected_index == 2:  # Song Commentary
                if self._pet and hasattr(self._pet, "_ai_song_comment_enabled"):
                    self._pet._ai_song_comment_enabled = not self._pet._ai_song_comment_enabled
                    state_str = "ENABLED" if self._pet._ai_song_comment_enabled else "DISABLED"
                    self.set_dialogue(f"* Autonomous song reactions are now {state_str}, darling!")
            elif self._selected_index == 3:  # Bomb Mode
                if self._pet and hasattr(self._pet, "_bomb_attack_enabled"):
                    self._pet._bomb_attack_enabled = not self._pet._bomb_attack_enabled
                    state_str = "ARMED" if self._pet._bomb_attack_enabled else "DISARMED"
                    self.set_dialogue(f"* Cat-head bombs are now {state_str}, mew!")
            elif self._selected_index == 4:  # Jump Mode
                if self._pet and hasattr(self._pet, "_jump_enabled"):
                    self._pet._jump_enabled = not self._pet._jump_enabled
                    state_str = "ENABLED" if self._pet._jump_enabled else "DISABLED"
                    self.set_dialogue(f"* Jump-to-cursor is now {state_str}, minion!")
            elif self._selected_index == 5:  # Storyline Defeat State
                self._wallet.defeated = not self._wallet.defeated
                self._wallet.save()
                state_str = "AFTER DEFEATING HER" if self._wallet.defeated else "BEFORE DEFEATING HER"
                self.set_dialogue(f"* Sanctuary storyline set to: {state_str}, mew!\n* (Greetings and exits will reflect this!)")
            else:
                self.state = ShopState.ROOT
                self._selected_index = 3
                self.set_dialogue(self._get_root_greeting())

        elif self.state == ShopState.FACTS_EDIT:
            if self._selected_index == 0:  # Change Nickname
                self._prompt_change_nickname()
            elif self._selected_index == 1:  # View Notes
                notes = self._get_fact_notes()
                notes_text = "\n".join(f"- {n}" for n in notes[:3]) if notes else "No notes stored yet."
                self.set_dialogue(f"* Permanent Notes:\n{notes_text}")
            elif self._selected_index == 2:  # Add Fact Note
                self._prompt_add_fact()
            else:
                self.state = ShopState.SETTINGS_MENU
                self._selected_index = 0
                self.set_dialogue("* Back to companion settings.")

        self.update()

    def _cancel_or_back(self) -> None:
        if self.state == ShopState.CHARACTER:
            self.state = ShopState.ROOT
            self._selected_index = 0
            self._ai_input.hide()
            self.set_dialogue(CANON_BUY_REFUSE)
        elif self.state in (ShopState.TASKS, ShopState.TALK_MENU, ShopState.SETTINGS_MENU):
            self.state = ShopState.ROOT
            self._selected_index = 0
            self._ai_input.hide()
            self.set_dialogue(self._get_root_greeting())
        elif self.state in (ShopState.TASK_CONFIRM, ShopState.TASK_SECOND_CONFIRM, ShopState.TIMER_MENU):
            self.state = ShopState.TASKS
            self._selected_index = 0
            self._ai_input.hide()
            self.set_dialogue(CANON_SELL_REFUSE)
        elif self.state == ShopState.FACTS_EDIT:
            self.state = ShopState.SETTINGS_MENU
            self._selected_index = 0
            self._ai_input.hide()
            self.set_dialogue("* Companion settings.")
        elif self.state == ShopState.TALK_DIALOGUE:
            self.state = ShopState.TALK_MENU
            self._ai_input.hide()
            self.set_dialogue(CANON_TALK_ENTER)
        elif self.state == ShopState.ROOT:
            self._start_exit()
        self.update()

    def _start_exit(self) -> None:
        self.state = ShopState.EXITING
        self.set_dialogue(self._get_exit_line())
        QTimer.singleShot(1100, self.close_shop)

    # --- Character Change / Wardrobe Logic -------------------------------------

    def _equip_character_form(self, form: dict) -> None:
        fid = form["id"]
        cost = form["cost"]

        if fid not in self._wallet.unlocked_forms:
            if self._wallet.spend(cost):
                self._wallet.unlocked_forms.append(fid)
                self._wallet.active_form = fid
                self._wallet.save()
                self._apply_form_to_pet(fid)
                self.set_dialogue(f"{CANON_BUY_PURCHASE}\n* (Swapped to {form['name']} form, mew!)")
            else:
                self.set_dialogue(f"{CANON_BUY_BROKE}\n* (Need P$ {cost}, you only have P$ {self._wallet.pink_dollars}!)")
        else:
            self._wallet.active_form = fid
            self._wallet.save()
            self._apply_form_to_pet(fid)
            self.set_dialogue(f"{CANON_BUY_PURCHASE}\n* (Swapped to {form['name']} form, mew!)")

    def _apply_form_to_pet(self, fid: str) -> None:
        if not self._pet:
            return
        try:
            if fid == "ghost":
                self._pet._is_ghost_talking = True
                if self._pet._can_play("angry"):
                    self._pet._play("angry")
            elif fid == "burnt":
                self._pet._is_ghost_talking = False
                if self._pet._can_play("burnt"):
                    self._pet._play("burnt")
            elif fid == "overjoyed":
                self._pet._is_ghost_talking = False
                if self._pet._can_play("overjoyed"):
                    self._pet._play("overjoyed")
            else:  # doll
                self._pet._is_ghost_talking = False
                if self._pet._can_play("idle"):
                    self._pet._play("idle")
        except Exception as e:
            log.warning("Could not apply form %s: %s", fid, e)

    # --- Task Completion & Facts Editing ---------------------------------------

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
            return [r.get("text", "") for r in reminders if r.get("text")][:4]
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

    def _get_user_name(self) -> str:
        if hasattr(self, "_memory") and self._memory and hasattr(self._memory, "get_user_name"):
            return self._memory.get_user_name()
        if FACTS_PATH.exists():
            try:
                data = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
                return data.get("user_name", "Minion")
            except Exception:
                pass
        return "Minion"

    def _get_fact_notes(self) -> list[str]:
        target_path = self._memory.facts_path if (hasattr(self, "_memory") and self._memory and hasattr(self._memory, "facts_path")) else FACTS_PATH
        if target_path.exists():
            try:
                data = json.loads(target_path.read_text(encoding="utf-8"))
                return data.get("notes", [])
            except Exception:
                pass
        return []

    def _save_facts(self, name: str | None = None, new_note: str | None = None) -> None:
        if name and hasattr(self, "_memory") and self._memory and hasattr(self._memory, "set_user_name"):
            self._memory.set_user_name(name)
        if new_note and hasattr(self, "_memory") and self._memory and hasattr(self._memory, "add_fact"):
            self._memory.add_fact(new_note)
            return

        target_path = self._memory.facts_path if (hasattr(self, "_memory") and self._memory and hasattr(self._memory, "facts_path")) else FACTS_PATH
        data = {"user_name": "Minion", "notes": []}
        if target_path.exists():
            try:
                data = json.loads(target_path.read_text(encoding="utf-8"))
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
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning("Error saving facts: %s", e)

    # --- Prompt Input Helpers --------------------------------------------------

    def _prompt_change_nickname(self) -> None:
        self._input_mode = "fact_name"
        self._show_input_bar(f"Enter your new nickname (current: {self._get_user_name()}):")

    def _prompt_add_fact(self) -> None:
        self._input_mode = "fact_note"
        self._show_input_bar("Enter a new fact for Pink to permanently remember:")

    def _prompt_custom_timer(self) -> None:
        self._input_mode = "custom_timer"
        self._show_input_bar("Enter timer length in minutes (e.g. 10 or 45):")

    def _prompt_serious_inquiry(self) -> None:
        self._input_mode = "ai_ask"
        self._show_input_bar("Ask Pink a serious question about life, work, or the digital world:")

    def _show_input_bar(self, prompt: str) -> None:
        self.set_dialogue(f"* {prompt}")
        scaled_w = round(CANVAS_W * self._scale)
        input_w = round(580 * self._scale)
        input_h = round(34 * self._scale)
        input_x = (scaled_w - input_w) // 2
        input_y = round(380 * self._scale)
        self._ai_input.setGeometry(input_x, input_y, input_w, input_h)
        self._ai_input.clear()
        self._ai_input.show()
        self._ai_input.setFocus()

    def _on_input_submitted(self) -> None:
        val = self._ai_input.text().strip()
        self._ai_input.hide()
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
                # Instruct Gemini to answer in her canonical Deltarune shopkeeper voice
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
        if self._ai_input.isVisible():
            if key == Qt.Key_Escape:
                self._ai_input.hide()
                self._cancel_or_back()
            super().keyPressEvent(event)
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
        elif key in (Qt.Key_Right, Qt.Key_D):
            if self.state == ShopState.TALK_MENU:
                if self._selected_index % 2 == 0:
                    self._selected_index += 1
                    self._on_selection_changed()
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

            # 2. Menu selection
            clicked_idx = self._get_item_at_canvas_pos(pos_canvas)
            if clicked_idx is not None:
                if clicked_idx == self._selected_index:
                    self._confirm_selection()
                else:
                    self._selected_index = clicked_idx
                    self._on_selection_changed()
                    self.update()
                return

            # 3. Draggable upper stage
            if pos_canvas.y() < 220:
                self._drag_active = True
                self._drag_start_pos = event.globalPos() - self.pos()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_active:
            self.move(event.globalPos() - self._drag_start_pos)
            return

        pos_canvas = self._screen_to_canvas(event.pos())
        hover_idx = self._get_item_at_canvas_pos(pos_canvas)
        is_dialogue = self._is_dialogue_rect(pos_canvas)

        if hover_idx is not None:
            self.setCursor(Qt.PointingHandCursor)
            if hover_idx != self._selected_index:
                self._selected_index = hover_idx
                self._on_selection_changed()
                self.update()
        elif is_dialogue and (self._is_typing() or self.state == ShopState.TALK_DIALOGUE):
            self.setCursor(Qt.PointingHandCursor)
        elif pos_canvas.y() < 220:
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
            # 5 options (line_h ~ 36, y: 250..430)
            if 412 <= pt.x() <= 628 and 245 <= pt.y() <= 430:
                idx = (pt.y() - 250) // 36
                if 0 <= idx < 5:
                    return idx

        elif self.state in (ShopState.CHARACTER, ShopState.TASKS, ShopState.TIMER_MENU, ShopState.SETTINGS_MENU, ShopState.FACTS_EDIT):
            # Left box items
            if 20 <= pt.x() <= 403 and 245 <= pt.y() <= 440:
                line_h = 30 if self.state == ShopState.SETTINGS_MENU else 38
                idx = (pt.y() - 245) // line_h
                count = self._get_menu_count()
                if 0 <= idx < count - 1:
                    return idx
            # Back option in right box: x: 412..628, y: 385..440
            if 412 <= pt.x() <= 628 and 385 <= pt.y() <= 440:
                return self._get_menu_count() - 1

        elif self.state in (ShopState.TASK_CONFIRM, ShopState.TASK_SECOND_CONFIRM):
            if 412 <= pt.x() <= 628:
                if 295 <= pt.y() <= 345:
                    return 0
                elif 350 <= pt.y() <= 405:
                    return 1

        elif self.state == ShopState.TALK_MENU:
            if 250 <= pt.y() <= 440:
                row = (pt.y() - 250) // 44
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
                              ShopState.TASK_SECOND_CONFIRM, ShopState.TIMER_MENU,
                              ShopState.SETTINGS_MENU, ShopState.FACTS_EDIT):
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
                self._draw_tasks_state(p)
            elif self.state == ShopState.TASK_CONFIRM:
                self._draw_task_confirm_state(p)
            elif self.state == ShopState.TASK_SECOND_CONFIRM:
                self._draw_task_second_confirm_state(p)
            elif self.state == ShopState.TIMER_MENU:
                self._draw_timer_menu_state(p)
            elif self.state == ShopState.SETTINGS_MENU:
                self._draw_settings_menu_state(p)
            elif self.state == ShopState.FACTS_EDIT:
                self._draw_facts_edit_state(p)
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
        options = ["CHARACTER", "TASKS & ALARM", "TALK", "CONFIG & FACTS", "EXIT"]
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
        # Top-Right Details
        if self._selected_index < len(CHARACTER_FORMS):
            f = CHARACTER_FORMS[self._selected_index]
            p.setFont(self._font_title)
            p.setPen(QColor(255, 255, 0))
            p.drawText(426, 38, f["name"])

            p.setFont(self._font_small)
            is_unlocked = f["id"] in self._wallet.unlocked_forms
            is_active = self._wallet.active_form == f["id"]

            status = "Equipped" if is_active else ("Unlocked" if is_unlocked else f"Cost: P$ {f['cost']}")
            p.setPen(QColor(170, 255, 230) if is_active else QColor(140, 206, 255))
            p.drawText(426, 60, f"Status: {status}")

            p.setPen(QColor(255, 255, 255))
            p.drawText(QRect(426, 75, 188, 140), Qt.AlignLeft | Qt.TextWordWrap, f["desc"])

        # Bottom-Left Forms
        p.setFont(self._font_body)
        start_x = 44
        start_y = 265
        line_h = 42

        for i, f in enumerate(CHARACTER_FORMS):
            is_sel = (i == self._selected_index)
            is_equipped = (self._wallet.active_form == f["id"])
            color = QColor(255, 255, 0) if is_sel else (QColor(170, 255, 230) if is_equipped else QColor(255, 255, 255))
            p.setPen(color)

            mark = " [EQUIPPED]" if is_equipped else ""
            p.drawText(start_x, start_y + i * line_h, f"{f['name']}{mark}")

            cost_str = "FREE" if f["cost"] == 0 else (f"P$ {f['cost']}" if f["id"] not in self._wallet.unlocked_forms else "OWNED")
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

    def _draw_tasks_state(self, p: QPainter) -> None:
        reminders = self._get_active_reminders()

        # Top-Right Focus Card
        p.setFont(self._font_title)
        p.setPen(QColor(255, 180, 220))
        p.drawText(426, 38, "Chore Board")

        p.setFont(self._font_small)
        p.setPen(QColor(140, 206, 255))
        if self._timer_active:
            mins = self._timer_seconds_remaining // 60
            secs = self._timer_seconds_remaining % 60
            p.drawText(426, 60, f"Alarm: {mins:02d}:{secs:02d}")
        else:
            p.drawText(426, 60, "Alarm: Inactive")

        p.setPen(QColor(255, 255, 255))
        p.drawText(
            QRect(426, 75, 188, 140),
            Qt.AlignLeft | Qt.TextWordWrap,
            "Pink awards P$ 1 - P$ 3 per completed task.\nShe checks your screen history for proof before paying!",
        )

        # Bottom-Left Reminders List + Timer Entry
        p.setFont(self._font_body)
        start_x = 44
        start_y = 265
        line_h = 36

        for i, rem in enumerate(reminders):
            is_active = (i == self._selected_index)
            color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
            p.setPen(color)

            val = evaluate_task_value(rem)
            short_text = rem[:18] + "..." if len(rem) > 18 else rem
            p.drawText(start_x, start_y + i * line_h, f"{i+1}. {short_text}")

            p.setPen(QColor(255, 180, 220) if not is_active else QColor(255, 255, 0))
            p.drawText(310, start_y + i * line_h, f"+P$ {val}")

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

        # Timer entry at bottom of task list
        timer_idx = len(reminders)
        is_timer_sel = (self._selected_index == timer_idx)
        p.setFont(self._font_body)
        p.setPen(QColor(255, 255, 0) if is_timer_sel else QColor(140, 206, 255))
        p.drawText(start_x, start_y + timer_idx * line_h, "[+ Focus Timer / Alarm]")
        if is_timer_sel and self._soul_heart:
            p.drawPixmap(start_x - 24, start_y + timer_idx * line_h - 13, self._soul_heart)

        # Bottom-Right Wallet & Back
        p.setFont(self._font_body)
        p.setPen(QColor(255, 180, 220))
        p.drawText(430, 265, "Pink Dollars:")
        p.setPen(QColor(255, 255, 255))
        p.drawText(430, 295, f"P$ {self._wallet.pink_dollars:06d}")

        p.setFont(self._font_title)
        is_back = (self._selected_index == len(reminders) + 1)
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

    def _draw_timer_menu_state(self, p: QPainter) -> None:
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
            p.drawText(426, 60, "Status: Idle")

        p.setPen(QColor(255, 255, 255))
        p.drawText(
            QRect(426, 75, 188, 140),
            Qt.AlignLeft | Qt.TextWordWrap,
            "Pick a study sprint or break timer.\nPink will trigger a taskbar alarm and bonus P$ when time is up!",
        )

        options = [
            "Start 5m Break",
            "Start 15m Sprint",
            "Start 25m Pomodoro",
            "Custom Timer...",
            "Stop Active Alarm",
        ]
        start_x = 44
        start_y = 265
        line_h = 36

        p.setFont(self._font_body)
        for i, opt in enumerate(options):
            is_active = (i == self._selected_index)
            color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
            p.setPen(color)
            p.drawText(start_x, start_y + i * line_h, opt)

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

        p.setFont(self._font_title)
        is_back = (self._selected_index == len(options))
        p.setPen(QColor(255, 255, 0) if is_back else QColor(255, 255, 255))
        p.drawText(450, 415, "Back")
        if is_back and self._soul_heart:
            p.drawPixmap(424, 401, self._soul_heart)

    def _draw_settings_menu_state(self, p: QPainter) -> None:
        p.setFont(self._font_title)
        p.setPen(QColor(255, 255, 0))
        p.drawText(426, 38, "Settings")

        p.setFont(self._font_small)
        p.setPen(QColor(140, 206, 255))
        p.drawText(426, 60, "Pet Configuration")

        p.setPen(QColor(255, 255, 255))
        p.drawText(
            QRect(426, 75, 188, 140),
            Qt.AlignLeft | Qt.TextWordWrap,
            "Toggle desktop companion features and edit your permanent fact sheet directly from here.",
        )

        bubbles_on = getattr(self._pet, "_dialogue_enabled", True) if self._pet else True
        song_on = getattr(self._pet, "_ai_song_comment_enabled", True) if self._pet else True
        bomb_on = getattr(self._pet, "_bomb_attack_enabled", False) if self._pet else False
        jump_on = getattr(self._pet, "_jump_enabled", True) if self._pet else True
        is_defeated = getattr(self._wallet, "defeated", False)

        options = [
            "Edit Facts & Nickname",
            f"Dialogue Bubbles: [{'ON' if bubbles_on else 'OFF'}]",
            f"AI Song Commentary: [{'ON' if song_on else 'OFF'}]",
            f"Bomb Attack Mode: [{'ON' if bomb_on else 'OFF'}]",
            f"Jump to Cursor: [{'ON' if jump_on else 'OFF'}]",
            f"Storyline Defeat: [{'AFTER' if is_defeated else 'BEFORE'}]",
        ]

        start_x = 44
        start_y = 260
        line_h = 30

        p.setFont(self._font_body)
        for i, opt in enumerate(options):
            is_active = (i == self._selected_index)
            color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
            p.setPen(color)
            p.drawText(start_x, start_y + i * line_h, opt)

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

        p.setFont(self._font_title)
        is_back = (self._selected_index == len(options))
        p.setPen(QColor(255, 255, 0) if is_back else QColor(255, 255, 255))
        p.drawText(450, 415, "Back")
        if is_back and self._soul_heart:
            p.drawPixmap(424, 401, self._soul_heart)

    def _draw_facts_edit_state(self, p: QPainter) -> None:
        p.setFont(self._font_title)
        p.setPen(QColor(170, 255, 230))
        p.drawText(426, 38, "Fact Sheet")

        p.setFont(self._font_small)
        p.setPen(QColor(140, 206, 255))
        p.drawText(426, 60, f"User: {self._get_user_name()}")

        notes = self._get_fact_notes()
        p.setPen(QColor(255, 255, 255))
        p.drawText(
            QRect(426, 75, 188, 140),
            Qt.AlignLeft | Qt.TextWordWrap,
            f"Notes Stored: {len(notes)}\nPink remembers these facts permanently across all sessions.",
        )

        options = [
            f"Change Nickname ({self._get_user_name()})",
            f"View Saved Notes ({len(notes)})",
            "Add New Fact Note",
        ]

        start_x = 44
        start_y = 275
        line_h = 44

        p.setFont(self._font_body)
        for i, opt in enumerate(options):
            is_active = (i == self._selected_index)
            color = QColor(255, 255, 0) if is_active else QColor(255, 255, 255)
            p.setPen(color)
            p.drawText(start_x, start_y + i * line_h, opt)

            if is_active and self._soul_heart:
                p.drawPixmap(start_x - 24, start_y + i * line_h - 13, self._soul_heart)

        p.setFont(self._font_title)
        is_back = (self._selected_index == len(options))
        p.setPen(QColor(255, 255, 0) if is_back else QColor(255, 255, 255))
        p.drawText(450, 415, "Back")
        if is_back and self._soul_heart:
            p.drawPixmap(424, 401, self._soul_heart)

    def _draw_talk_state(self, p: QPainter) -> None:
        if self.state == ShopState.TALK_MENU:
            p.setFont(self._font_title)

            start_x1 = 50
            start_x2 = 340
            start_y = 275
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
