"""Pink's AI reply tag protocol: one grammar for every ``[name: body]`` tag (REVIEW M24, plan 8.2).

Before this there were seven different "strip these tags" lists across three files and three different ghost-mode
grammars, and they had drifted (a tag hidden in one place showed up in another). Every parser and every strip now
uses the tables below. ``yellows_pixel_buddies.py``, ``shop_window.py`` and ``action_planner.py`` all import this
module (GEMINI.md §3: tag changes must reach both UI files).

Applying memory tags (facts, reminders, goals, timers...) is NOT done here: that belongs to Phase 2's memory_actions.
"""
from __future__ import annotations

import functools
import re
from typing import Iterable, Optional

# [name: body] / [name : body]. Bodies can't contain ']'.
TAG_RE = re.compile(r"\[(?P<name>[A-Za-z_]+)\s*:\s*(?P<body>[^\]]*)\]")

# Spelling variants the model uses -> canonical tag name.
ALIASES = {
    "ghost": "mode",
    "task": "add_reminder", "todo": "add_reminder", "add_task": "add_reminder", "add_todo": "add_reminder",
    "timer": "set_timer", "alarm": "set_alarm",
    "thought": "think",
}

# Tags that change Pink's look / voice for one line.
DISPLAY_TAGS = ("anim", "mode", "ghost", "emotion", "think", "thought")
MODE_TAGS = ("mode", "ghost")

# Tags that change memory: facts, temp facts, curiosities, reminders, goals, timers and alarms.
MEMORY_ACTION_TAGS = (
    "seen", "set_user_name", "add_fact", "add_temp_fact", "temp_fact", "delete_temp_fact", "del_temp_fact",
    "rm_temp_fact",
    "add_curiosity", "curiosity", "resolve_curiosity", "done_curiosity", "del_curiosity",
    "add_task", "add_reminder", "add_todo", "task", "todo", "delete_task", "del_task", "rm_task", "delete_reminder",
    "del_reminder", "rm_reminder", "delete_todo", "del_todo", "rm_todo",
    "edit_task", "update_task", "edit_reminder", "update_reminder", "edit_todo", "update_todo",
    "add_goal", "complete_goal", "finish_goal", "done_goal", "delete_goal", "del_goal", "rm_goal", "update_goal",
    "set_goal_deadline", "snooze_goals", "set_coaching_mode",
    "set_timer", "timer", "set_alarm", "alarm", "cancel_timer", "del_timer", "cancel_alarm", "del_alarm",
)

# Desktop takeover tags ([desktop_action] is the documented one; the rest are legacy, still stripped).
DESKTOP_TAGS = ("desktop_action", "quick_reply", "click_ui", "click_target", "click", "type_input", "type_text")

# Everything that must never be shown to the user as text.
ALL_TAGS = tuple(dict.fromkeys(DISPLAY_TAGS + MEMORY_ACTION_TAGS + DESKTOP_TAGS))

# [mode: <value>] values that mean "speak as the ghost".
GHOST_VALUES = frozenset({"ghost", "true", "yes", "spectral", "takeover"})


def canonical(name: str) -> str:
    n = (name or "").strip().lower()
    return ALIASES.get(n, n)


def parse_tags(line: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (text without any tags, [(canonical name, body), ...]) in order of appearance."""
    tags = [(canonical(m["name"]), m["body"].strip()) for m in TAG_RE.finditer(line or "")]
    return TAG_RE.sub("", line or "").strip(), tags


@functools.lru_cache(maxsize=32)
def _strip_re(names: tuple[str, ...]) -> re.Pattern:
    alt = "|".join(sorted((re.escape(n) for n in names), key=len, reverse=True))
    return re.compile(r"\[(?:" + alt + r")\s*:\s*[^\]]*\]", re.IGNORECASE)


def strip_tags(text: str, names: Iterable[str] = ALL_TAGS) -> str:
    """Remove ``[name: ...]`` tags for the given names (default: every known tag). Unknown brackets are kept."""
    if not text:
        return text or ""
    return _strip_re(tuple(names)).sub("", text)


_MODE_RE = re.compile(r"\[(?:mode|ghost)\s*:\s*([^\]]*)\]", re.IGNORECASE)


def ghost_mode(text: str) -> Optional[bool]:
    """The ONE ghost-mode grammar: None if the text has no [mode:]/[ghost:] tag, else whether it asks for the ghost.

    The value's first word decides ("[mode: ghost]", "[ghost: true]", "[mode: Ghost mode]" -> True;
    "[mode: normal]" -> False). Replaces three grammars that disagreed on prefixes and spaces.
    """
    m = _MODE_RE.search(text or "")
    if not m:
        return None
    words = re.findall(r"[a-z0-9_]+", m.group(1).lower())
    return bool(words) and words[0] in GHOST_VALUES


def split_mode(text: str) -> tuple[Optional[bool], str]:
    """(ghost_mode(text), text with every mode tag removed)."""
    return ghost_mode(text), strip_tags(text, MODE_TAGS)
