"""Characterization tests for temp/REVIEW.md (Phase 0.7 of temp/IMPLEMENTATION_PLAN.md).

Two kinds of tests live here:

* **Pins**: plain tests that lock in behaviour that is correct today and must survive the fixes.
* **Known bugs**: ``xfail(strict=True)`` tests whose ``reason`` is the review finding ID. They encode
  the *desired* behaviour, so they fail today. Because ``xfail_strict = true`` (pyproject.toml),
  the moment a fix makes one pass, the suite turns red until the marker is removed. That forces
  every fix PR to say which findings it closed.

Findings closed so far (markers removed, tests now guard the fix): C1, C2, C3, C4, H8 (Phase 1); H21, M14 (Phase 6).
"""
from __future__ import annotations

import datetime as _dt
import json
import types

import pytest
from PIL import Image

import action_planner
import os_interop
import yellows_pixel_buddies as ypb

ActionStep = action_planner.ActionStep
is_sensitive = action_planner.DesktopActionExecutor._is_sensitive_action


def bug(finding: str):
    return pytest.mark.xfail(strict=True, reason=f"REVIEW {finding}")


# =====================================================================================
# C2 - sensitive-action gate
# =====================================================================================

class TestSensitiveActionPins:
    def test_chat_message_with_enter_is_sensitive(self):
        assert is_sensitive(ActionStep(action_type="click_and_type", target="Message input box", text="hi", press_enter=True))

    def test_send_and_delete_clicks_are_sensitive(self):
        assert is_sensitive(ActionStep(action_type="click", target="Send button"))
        assert is_sensitive(ActionStep(action_type="click", target="Delete file button"))

    def test_delete_key_is_sensitive(self):
        assert is_sensitive(ActionStep(action_type="press_key", key="delete"))

    def test_terminal_typing_is_sensitive(self):
        assert is_sensitive(ActionStep(action_type="type_text", target="prompt", text="dir"), fg_proc="powershell.exe")

    def test_plain_navigation_click_is_not_sensitive(self):
        assert not is_sensitive(ActionStep(action_type="click", target="Chrome Tab"))


class TestSensitiveActionFixedInPhase1:  # was known bugs (REVIEW C2)
    def test_standalone_enter_key_is_sensitive(self):
        assert is_sensitive(ActionStep(action_type="press_key", key="enter"))

    def test_win_r_hotkey_is_sensitive(self):
        assert is_sensitive(ActionStep(action_type="hotkey", keys=["win", "r"]))

    def test_alt_f4_hotkey_is_sensitive(self):
        assert is_sensitive(ActionStep(action_type="hotkey", keys=["alt", "f4"]))

    def test_newline_in_text_counts_as_submit(self):
        step = ActionStep(action_type="type_text", target="message box", text="on my way\n", press_enter=False)
        assert is_sensitive(step, fg_proc="whatsapp.exe")

    def test_pwsh_terminal_is_sensitive(self):
        assert is_sensitive(ActionStep(action_type="type_text", target="prompt", text="iwr x | iex"), fg_proc="pwsh.exe")

    def test_run_dialog_is_sensitive(self):
        step = ActionStep(action_type="type_text", target="Open box", text="powershell", press_enter=False)
        assert is_sensitive(step, fg_title="Run", fg_proc="explorer.exe")


# =====================================================================================
# C3 / H8 - execute_plan harness (no real input: fake_os_interop records everything)
# =====================================================================================

def _run_plan(monkeypatch, fake, steps, on_confirm=None):
    """Drive execute_plan with scripted model decisions and a fake screen."""
    img = Image.new("RGB", (64, 64), "white")

    def fake_capture(*_a, **_k):
        action_planner._LAST_RAW_SCREENSHOT = img
        return "ZmFrZQ==", 64, 64, (0, 0)

    scripted = iter(steps)

    def fake_decide(*_a, **_k):
        return next(scripted, ActionStep(action_type="fail", target="script exhausted"))

    monkeypatch.setattr(action_planner, "capture_screen_region", fake_capture)
    monkeypatch.setattr(action_planner, "ground_ui_element", lambda *a, **k: None)
    monkeypatch.setattr(action_planner.DesktopActionExecutor, "_decide_next_step", fake_decide)

    plan = action_planner.DesktopPlan(intent="reply to Mom saying on my way", target_app="Desktop",
                                      user_request="reply to Mom saying on my way")
    executor = action_planner.DesktopActionExecutor(api_key="test")
    executor.execute_plan(plan, on_confirm_action=on_confirm)
    return plan


def test_harness_records_instead_of_typing(monkeypatch, fake_os_interop, no_sleep):
    """Sanity pin: the harness works and input is recorded, not sent."""
    _run_plan(monkeypatch, fake_os_interop, [ActionStep(action_type="type_text", target="notes", text="hello")])
    assert "type_text" in fake_os_interop.names()


def test_cancel_ends_the_plan(monkeypatch, fake_os_interop, no_sleep):
    steps = [
        ActionStep(action_type="type_text", target="Message input box", text="on my way", press_enter=True),  # gated -> user cancels
        ActionStep(action_type="type_text", target="Message input box", text="on my way", press_enter=False),  # model routes around
        ActionStep(action_type="press_key", key="enter"),
    ]
    plan = _run_plan(monkeypatch, fake_os_interop, steps, on_confirm=lambda *a: False)
    assert plan.outcome_state == "aborted"
    assert not [c for c in fake_os_interop.names() if c in ("type_text", "press_key", "hotkey")]


def test_search_guard_never_select_all_without_click(monkeypatch, fake_os_interop, no_sleep):
    steps = [ActionStep(action_type="type_text", target="Find search box", text="budget")]  # no coordinates
    _run_plan(monkeypatch, fake_os_interop, steps)
    assert ("hotkey", ("ctrl", "a"), {}) not in fake_os_interop.calls


# =====================================================================================
# C1 / C4 - spec for Phase 1's pure gate module (doesn't exist yet -> ImportError)
# =====================================================================================

@pytest.mark.parametrize("user_text,origin,expected", [
    ("[User dropped an image: 'x.png'] What do you think of this picture?", "image", False),
    ("what do you think of this page?", "typed", False),
    ("[Pink is watching your gameplay (Temple Run)]", "ambient", False),
    ("/do open spotify", "slash", True),
])
def test_takeover_gate(user_text, origin, expected):
    import takeover_gate  # noqa: F401 - Phase 1.1

    decision = takeover_gate.takeover_decision(user_text, takeover_gate.TurnOrigin(origin), had_visual=False, mode="slash_only")
    assert (decision is takeover_gate.GateDecision.AUTO) is expected


@pytest.mark.parametrize("text,expected", [
    ("No, don't send it", "no"), ("Jangan dilanjut ya", "no"), ("I'm not sure", "no"),
    ("hentikan, bahaya!", "no"), ("yes", "yes"), ("iya lanjut", "yes"),
])
def test_voice_yes_no(text, expected):
    import takeover_gate  # Phase 1.5

    assert takeover_gate.classify_yes_no(text) == expected


# =====================================================================================
# H5 / L2 - os_interop window lookup and coordinate math
# =====================================================================================

def _win(hwnd, title, proc):
    return os_interop.WindowInfo(hwnd=hwnd, title=title, process_id=hwnd, process_name=proc,
                                 bounds=(0, 0, 800, 600), is_minimized=False, is_cloaked=False)


def test_find_window_finds_real_whatsapp(monkeypatch):
    monkeypatch.setattr(os_interop, "list_windows", lambda *a, **k: [_win(1, "WhatsApp", "WhatsApp.exe")])
    assert os_interop.find_window("whatsapp").hwnd == 1


@bug("H5")
def test_find_window_does_not_return_any_chrome_for_whatsapp(monkeypatch):
    monkeypatch.setattr(os_interop, "list_windows", lambda *a, **k: [_win(2, "GitHub - Google Chrome", "chrome.exe")])
    assert os_interop.find_window("whatsapp") is None


@bug("L2")
def test_absolute_mouse_coords_round_trip(monkeypatch):
    m = os_interop.ScreenMetrics(virtual_left=0, virtual_top=0, virtual_width=1920, virtual_height=1080,
                                 primary_width=1920, primary_height=1080)
    monkeypatch.setattr(os_interop, "get_screen_metrics", lambda: m)
    for x in range(0, 1920, 7):
        nx, _ = os_interop.coords_to_normalized_virtual(x, 0)
        assert nx * 1920 // 65536 == x  # how Windows maps 0-65535 back to a pixel


# =====================================================================================
# C6 / H14 - persistence
# =====================================================================================

def test_add_fact_round_trip(mem):
    assert mem.add_fact("likes tea")
    assert "likes tea" in json.loads(mem.facts_path.read_text(encoding="utf-8"))["notes"]


@bug("C6")
def test_corrupt_facts_file_is_not_overwritten(mem):
    mem.facts_path.parent.mkdir(parents=True, exist_ok=True)
    mem.facts_path.write_text('{"user_name": "Bin", "notes": ["a"]', encoding="utf-8")  # truncated mid-write
    try:
        mem.add_fact("b")
    except Exception:
        pass  # refusing loudly is fine; silently wiping is not
    survivors = mem.facts_path.read_text(encoding="utf-8") + "".join(
        p.read_text(encoding="utf-8") for p in mem.facts_path.parent.glob("facts.corrupt-*"))
    assert "Bin" in survivors


@pytest.fixture
def frozen_now(monkeypatch):
    """Freeze datetime.datetime.now() inside yellows_pixel_buddies (IDs are built from it)."""
    class _Frozen(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 23, 12, 0, 0, tzinfo=tz)

    shim = types.SimpleNamespace(**{k: getattr(_dt, k) for k in dir(_dt) if not k.startswith("__")})
    shim.datetime = _Frozen
    monkeypatch.setattr(ypb, "datetime", shim)


@bug("H14")
def test_reminders_added_in_same_second_get_unique_ids(mem, frozen_now):
    for text in ("call mom", "buy milk", "pay rent"):
        assert mem.add_reminder(text)
    ids = [r["id"] for r in mem.get_active_reminders()]
    assert len(ids) == 3 and len(set(ids)) == 3


# =====================================================================================
# H21 / M14 - intent and time parsers
# =====================================================================================

@pytest.mark.parametrize("text,expected", [
    ("25m", 1500), ("10", 600), ("45s", 45), ("1h30m", 5400), ("2 hours and 15 minutes", 8100), ("soon", None),
])
def test_duration_pins(text, expected):
    assert ypb.parse_duration_string(text) == expected


@pytest.mark.parametrize("text,expected", [("1m30s", 90), ("1.5m", 90)])
def test_duration_known_gaps(text, expected):
    assert ypb.parse_duration_string(text) == expected


@pytest.mark.parametrize("text,expected", [("2:30pm", (14, 30)), ("12am", (0, 0)), ("08:00", (8, 0)), ("13pm", None)])
def test_clock_pins(text, expected):
    assert ypb.parse_clock_time(text) == expected


def test_clock_accepts_dot_separator():
    assert ypb.parse_clock_time("7.30 pm") == (19, 30)


def test_real_departure_is_detected():
    assert ypb.check_is_departure_message("ok I have to go now, bye!")


@pytest.mark.parametrize("text", [
    "I'm going to test the build, open VS Code",
    "reply to Mom on WhatsApp saying bye",
])
def test_ordinary_chat_is_not_departure(text):
    assert not ypb.check_is_departure_message(text)


def test_returned_status_code_is_not_a_return():
    assert not ypb.check_is_return_message("my API call returned 500, why?")
