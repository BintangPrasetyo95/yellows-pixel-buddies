"""Phase 8 (decomposition) tests. See temp/IMPLEMENTATION_PLAN.md §11.

8.1 prompt_builder · 8.2 protocol · 8.3 slash-command router · 8.4 pure intents (T2/T4) · 8.5 no silent excepts in
persistence/takeover · 8.6 shop menu table (L13). Most of these need no QApplication at all, which is the point.
"""
from __future__ import annotations

import ast
import datetime
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from pink.ai import prompt_builder as pb
from pink.ai import protocol
from pink.chat import commands
from pink.shop import menus
from pink.text import intents

ROOT = Path(__file__).resolve().parents[1]


# =====================================================================================
# T2: the pure modules import without Qt, torch or whisper
# =====================================================================================

def test_pure_modules_do_not_load_qt_or_torch():
    code = ("import sys; import pink.text.intents, pink.ai.protocol, pink.ai.prompt_builder, pink.chat.commands, "
            "pink.shop.menus, pink.storage.manager, pink.storage.actions, pink.storage.sessions, pink.storage.json_store; heavy = [m for m in sys.modules if m.split('.')[0] in ('PyQt5', 'torch', 'whisper')]; "
            "print(heavy); sys.exit(1 if heavy else 0)")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_main_and_shop_share_the_same_functions():
    import shop_window
    import yellows_pixel_buddies as ypb
    assert ypb.parse_duration_string is intents.parse_duration_string
    assert ypb.evaluate_goal_value is intents.evaluate_goal_value
    assert shop_window.evaluate_task_value is intents.evaluate_task_value
    assert shop_window.DeltaruneShopWindow.evaluate_goal_value(None, "finish my thesis") == intents.evaluate_goal_value("finish my thesis")


# =====================================================================================
# T4: table tests for the highest-value pure functions
# =====================================================================================

@pytest.mark.parametrize("s,expected", [
    ("25m", 1500), ("1h30m", 5400), ("45s", 45), ("2 jam", 7200), ("10 menit", 600), ("1.5h", 5400), ("soon", None),
])
def test_parse_duration(s, expected):
    assert intents.parse_duration_string(s) == expected


@pytest.mark.parametrize("s,expected", [("7:30 pm", (19, 30)), ("07:05", (7, 5)), ("6 pagi", (6, 0)), ("25:00", None)])
def test_parse_clock_time(s, expected):
    assert intents.parse_clock_time(s) == expected


@pytest.mark.parametrize("msg", ["my API call returned 500, why?", "I'm going to test the build", "reply to Mom saying bye"])
def test_not_departure_or_return(msg):
    assert not intents.check_is_departure_message(msg)
    assert not intents.check_is_return_message(msg)


def test_departure_return_and_focus():
    assert intents.check_is_departure_message("brb, gotta go eat")
    assert intents.check_is_return_message("i'm back")
    is_focus, dur = intents.check_is_focus_message("I need to focus for 25 minutes")
    assert is_focus and dur == 25 * 60
    assert not intents.check_is_focus_message("how do I turn off focus assist?")[0]


def test_parse_target_date_day_first():
    year = datetime.date.today().year + 1
    assert intents.parse_target_date(f"25/12/{year}", day_first=True) == f"{year}-12-25"
    assert intents.parse_target_date(f"12/25/{year}", day_first=False) == f"{year}-12-25"


@pytest.mark.parametrize("text", ["drink water", "finish and publish my thesis chapter"])
def test_goal_value_in_range(text):
    assert 3 <= intents.evaluate_goal_value(text) <= 8


# =====================================================================================
# 8.2 protocol
# =====================================================================================

def test_parse_tags_canonicalises_aliases():
    clean, tags = protocol.parse_tags("* Fine! [timer: 5m, tea] [task: call mom] [ghost: true]")
    assert clean == "* Fine!"
    assert tags == [("set_timer", "5m, tea"), ("add_reminder", "call mom"), ("mode", "true")]


@pytest.mark.parametrize("text,expected", [
    ("[mode: ghost]", True), ("[ghost: true]", True), ("[mode: Ghost mode]", True), ("[MODE : spectral]", True),
    ("[mode: normal]", False), ("no tag here", None),
])
def test_one_ghost_grammar(text, expected):
    assert protocol.ghost_mode(text) is expected


def test_strip_tags_defaults_to_every_known_tag():
    line = "* Hi! [anim: smug] [add_task: x] [desktop_action: Chrome, open it] [set_timer: 5m] [keep: me]"
    assert protocol.strip_tags(line).split() == ["*", "Hi!", "[keep:", "me]"]
    assert "[anim: smug]" in protocol.strip_tags(line, protocol.MEMORY_ACTION_TAGS)


def test_tag_tables_are_consistent():
    assert set(protocol.MEMORY_ACTION_TAGS) | set(protocol.DESKTOP_TAGS) | set(protocol.DISPLAY_TAGS) == set(protocol.ALL_TAGS)
    assert len(protocol.ALL_TAGS) == len(set(protocol.ALL_TAGS))


def test_shop_and_bubble_hide_the_same_tags():
    import shop_window
    text = "* On it! [desktop_action: WhatsApp, reply] [add_goal: run] [anim: tongue] [thought: hmm]"
    lines = shop_window.DeltaruneShopWindow._clean_history_dialogue(None, text)
    assert lines == ["* On it!"]


# =====================================================================================
# 8.1 prompt builder
# =====================================================================================

def test_memory_sections_golden():
    ctx = pb.MemoryContext(facts="- likes cats", reminders="1. call mom", goals="1. thesis")
    assert pb.memory_sections(ctx) == (
        f"\n\n{pb.FACTS_HEADER}\n- likes cats"
        "\n\nACTIVE TEMPORARY REMINDERS & TO-DOS (Auto-expires after 30 days):\n1. call mom"
        "\n\nUSER'S TARGET MILESTONES & LONG-TERM GOALS (Earns P$ upon completion):\n1. thesis"
    )
    assert pb.memory_sections(pb.MemoryContext()) == ""


def test_header_golden():
    assert pb.system_header("PERSONA", "Monday", "LANG", "CODE") == "PERSONA\n- Current Local Time: Monday.\nLANG\nCODE"
    assert pb.system_header("PERSONA", "Monday") == "PERSONA\n- Current Local Time: Monday."
    assert pb.section("") == "" and pb.section("X") == "\n\nX"


def test_memory_context_reads_whatever_memory_has():
    class Mem:
        def get_long_term_facts(self):
            return "f"

        def get_reminders_prompt(self):
            return ""

    assert pb.MemoryContext.from_memory(Mem()) == pb.MemoryContext(facts="f")


@pytest.mark.parametrize("builder", ["_build_question_prompt", "_on_chat_submitted", "_trigger_auto_screen_comment",
                                     "_trigger_ai_song_comment", "_read_screen_while_in_tray", "_trigger_cinema_comment"])
def test_every_prompt_has_the_active_app_block_once(builder):
    import yellows_pixel_buddies as ypb
    src = inspect.getsource(getattr(ypb.YellowsPixelBuddies, builder))
    assert src.count("self._active_app_section()") == 1          # was missing in 3 and doubled in 1 (REVIEW M24)
    assert "get_active_app_prompt_block()" not in src


@pytest.mark.slow
def test_question_prompt_output_has_one_app_block(qapp, monkeypatch):
    import yellows_pixel_buddies as ypb
    from tests.conftest import shutdown_pet
    pet = ypb.YellowsPixelBuddies(ypb.SpriteBank(ypb.SPRITES_DIR, 1.0))
    try:
        monkeypatch.setattr(pet, "get_active_app_prompt_block", lambda: "[CURRENT DESKTOP FOREGROUND CONTEXT] X")
        system_inst, _user = pet._build_question_prompt("personality")
        assert system_inst.count("[CURRENT DESKTOP FOREGROUND CONTEXT]") == 1
        assert system_inst.startswith(ypb.PINK_SYSTEM_INSTRUCTION)
    finally:
        shutdown_pet(pet)


# =====================================================================================
# 8.3 slash-command router
# =====================================================================================

def test_router_first_match_wins_and_can_fall_through():
    calls = []

    class Owner:
        def _a(self, c, l):
            calls.append("a")
            return False          # e.g. "/fact " with nothing after it: continue to normal chat

        def _b(self, c, l):
            calls.append("b")
            return True

    r = commands.CommandRouter([commands.Command("a", commands.prefix("/fact"), "_a"),
                                commands.Command("b", commands.prefix("/f"), "_b")])
    assert r.dispatch(Owner(), "/fact ", "/fact ") is False and calls == ["a"]      # b never considered
    assert r.dispatch(Owner(), "/foo", "/foo") is True and calls == ["a", "b"]
    assert r.dispatch(Owner(), "hello", "hello") is False


def test_pet_command_table_is_complete():
    import yellows_pixel_buddies as ypb
    table = ypb.YellowsPixelBuddies._SLASH_COMMANDS
    assert len(table.commands) == 44
    for cmd in table.commands:
        assert callable(getattr(ypb.YellowsPixelBuddies, cmd.handler)), cmd.handler
    m = lambda text: table.match(text, text.lower()).name   # noqa: E731
    assert m("/name Bob") == "name" and m("/do open notepad") == "do" and m("/timers") == "timers"
    assert table.match("hello pink", "hello pink") is None


# =====================================================================================
# 8.6 shop menus (L13)
# =====================================================================================

@pytest.mark.parametrize("sel,off,count,back,expected", [
    (0, 2, 10, True, 0), (6, 2, 10, True, 3), (3, 0, 10, True, 0), (10, 2, 10, True, 7), (10, 2, 10, False, 2),
])
def test_follow_selection(sel, off, count, back, expected):
    assert menus.follow_selection(sel, off, count, back) == expected


def test_list_rows():
    assert menus.list_index_at_row(0, 3, 10) == 3
    assert menus.list_index_at_row(menus.BACK_ROW, 3, 10) == 10
    assert menus.list_index_at_row(5, 3, 10) is None        # the row below Back used to hit an invisible item
    assert menus.list_index_at_row(2, 9, 10) is None


def test_layouts_match_what_is_drawn():
    assert menus.LEFT_LIST.draw_origin() == (44, 283, 36) and menus.LEFT_LIST.row_at(100, 265) == 0
    assert menus.LEFT_LIST.row_at(100, 301) == 1 and menus.LEFT_LIST.row_at(10, 300) is None
    assert menus.TOGGLES_LIST.row_at(100, 262) == 0 and menus.TOGGLES_LIST.row_at(100, 290) == 1
    assert menus.RIGHT_LIST.row_at(500, 470) is None


@pytest.fixture
def shop(qapp, mem):
    import shop_window
    w = shop_window.DeltaruneShopWindow(pet_ref=None, memory=mem, font_family="Arial")
    yield w
    w._focus_timer.stop()
    w.hide()
    w.close()


def test_shop_nav_and_hit_test_share_the_rules(shop):
    import shop_window
    from PyQt5.QtCore import QPoint
    shop.state = shop_window.ShopState.TALK_MENU
    shop._talk_scroll_offset, shop._selected_index = 0, 0
    for _ in range(5):
        shop._nav_down()
    assert shop._talk_scroll_offset == 2                           # selection 5 kept in view
    assert shop._get_item_at_canvas_pos(QPoint(100, 265)) == 2     # first visible row
    assert shop._get_item_at_canvas_pos(QPoint(100, 265 + 5 * 36)) is None   # below Back: nothing


def test_shop_timer_actually_ticks(shop):
    shop.start_timer(5, "tea")
    assert shop._focus_timer.isActive()


# =====================================================================================
# 8.5 no silent exception swallowing in persistence and takeover
# =====================================================================================

def _silent_handlers(path: str, cls: str | None = None) -> list[int]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    scope = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls) if cls else tree
    return [h.lineno for h in ast.walk(scope)
            if isinstance(h, ast.ExceptHandler) and len(h.body) == 1 and isinstance(h.body[0], ast.Pass)
            and h.body[0].lineno != h.lineno]


@pytest.mark.parametrize("path,cls", [("pink/storage/manager.py", "MemoryManager"), ("takeover_controller.py", None),
                                      ("action_planner.py", None)])
def test_no_silent_excepts(path, cls):
    assert _silent_handlers(path, cls) == []


def test_torch_dll_helper_is_idempotent():
    from pink import torch_dll
    assert torch_dll.register_torch_dll_dirs() is torch_dll.register_torch_dll_dirs()
