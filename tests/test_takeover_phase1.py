"""Phase 1 (Pink Takeover safety hotfix) regression tests. See temp/IMPLEMENTATION_PLAN.md §4.

Covers REVIEW C1 (origin-based gate), C2 (effect-based sensitive gate, newline handling), C3 (cancel ends
plan), C4 (voice yes/no), H1 (phrase fallback removed), H3 (self-injected Esc), H8 (no blind select-all),
H10 (voice cancel discards audio), M1 (confirmation token / arming / default Cancel), L3 (/do announces only
real starts) and the H12 vision opt-in defaults. Nothing here sends real input.
"""
from __future__ import annotations

import threading

import numpy as np
import pytest

import action_planner
import os_interop
import takeover_gate as tg
from tests.test_characterization_review import _run_plan

ActionStep = action_planner.ActionStep
O = tg.TurnOrigin
D = tg.GateDecision


# =====================================================================================
# takeover_gate.takeover_decision (C1, H1)
# =====================================================================================

@pytest.mark.parametrize("text,origin,visual,mode,expected", [
    # explicit commands
    ("/do open spotify", O.SLASH, False, "slash_only", D.AUTO),
    ("/do open spotify", O.TYPED, False, "assisted", D.AUTO),
    ("/do open spotify", O.SLASH, False, "off", D.DENY),
    # slash_only: model-proposed takeovers never start
    ("open spotify", O.TYPED, False, "slash_only", D.DENY),
    # assisted: user's own imperative -> confirm first
    ("open spotify", O.TYPED, False, "assisted", D.CONFIRM),
    ("Pink, please open youtube music in chrome", O.TYPED, False, "assisted", D.CONFIRM),
    ("can you reply to Mom saying on my way", O.TYPED, False, "assisted", D.CONFIRM),
    ("buka spotify", O.TYPED, False, "assisted", D.CONFIRM),
    ("open spotify", O.VOICE, True, "assisted", D.CONFIRM),   # voice always has a screenshot: confirm, never auto
    # assisted: everything that isn't the user's own instruction is denied (C1 repros)
    ("what do you think of this page?", O.TYPED, True, "assisted", D.DENY),
    ("can you show me how recursion works?", O.TYPED, False, "assisted", D.DENY),   # H1 repro
    ("[User dropped an image: 'x.png'] What do you think of this picture?", O.IMAGE, True, "assisted", D.DENY),
    ("[User showed image: 'meme.png'] What do you think of this picture?", O.TYPED, True, "assisted", D.DENY),
    ("[Pink is watching your gameplay (Temple Run)]", O.AMBIENT, True, "assisted", D.DENY),
    ("open the shop", O.SHOP, False, "assisted", D.DENY),
    ("open spotify", O.QUESTION, False, "assisted", D.DENY),
    ("open spotify", "not-an-origin", False, "assisted", D.DENY),
    # off: nothing
    ("open spotify", O.TYPED, False, "off", D.DENY),
])
def test_takeover_decision(text, origin, visual, mode, expected):
    assert tg.takeover_decision(text, origin, had_visual=visual, mode=mode) is expected


def test_unknown_mode_falls_back_to_safe_default():
    assert tg.normalize_mode("yolo") == tg.DEFAULT_TAKEOVER_MODE == tg.TAKEOVER_MODE_SLASH_ONLY
    assert tg.takeover_decision("open spotify", O.TYPED, False, "yolo") is D.DENY


# =====================================================================================
# takeover_gate.classify_yes_no (C4)
# =====================================================================================

@pytest.mark.parametrize("text,expected", [
    ("yes", "yes"), ("Yes!", "yes"), ("ok", "yes"), ("okay go ahead", "yes"), ("yes please do it", "yes"),
    ("ya", "yes"), ("iya", "yes"), ("iya lanjut", "yes"), ("oke gas", "yes"), ("sure", "yes"),
    ("no", "no"), ("No, don't send it", "no"), ("don’t do it", "no"), ("I'm not sure", "no"),
    ("why not", "no"), ("not now", "no"), ("cancel", "no"), ("Jangan dilanjut ya", "no"),
    ("hentikan, bahaya!", "no"), ("gak usah", "no"), ("wait", "no"),
    ("look at that", None), ("bahaya", None), ("send it", None), ("yes but send it to dad instead", None),
    ("", None), ("   ", None),
])
def test_classify_yes_no(text, expected):
    assert tg.classify_yes_no(text) == expected


# =====================================================================================
# os_interop: newline handling (C2) and self-injected Esc (H3)
# =====================================================================================

def test_type_text_refuses_newline_without_opt_in(monkeypatch):
    sent = []
    monkeypatch.setattr(os_interop, "_send_input_batch", lambda inputs: sent.append(inputs) or True)
    with pytest.raises(ValueError):
        os_interop.type_text("git push --force\n", delay_between_chars_s=0.0)
    with pytest.raises(ValueError):
        os_interop.type_text("line one\rline two", delay_between_chars_s=0.0)
    assert sent == []  # nothing typed at all


def test_type_text_newline_allowed_when_confirmed_or_shift_enter(monkeypatch):
    sent = []
    monkeypatch.setattr(os_interop, "_send_input_batch", lambda inputs: sent.append(inputs) or True)
    assert os_interop.type_text("hi\n", delay_between_chars_s=0.0, enter_on_newline=True)
    assert os_interop.type_text("hi\nthere", delay_between_chars_s=0.0, use_shift_enter=True)
    vks = [inp.u.ki.wVk for batch in sent for inp in batch]
    assert os_interop.VK_RETURN in vks and os_interop.VK_SHIFT in vks


def test_launch_query_with_newline_is_rejected(monkeypatch):
    monkeypatch.setattr(os_interop, "find_window", lambda *a, **k: None)
    monkeypatch.setattr(os_interop, "press_key", lambda *a, **k: pytest.fail("must not press keys"))
    assert os_interop.launch_or_focus("notepad\nrun evil", use_start_menu=True) is None


class _FakeUser32:
    def __init__(self, esc_state: int) -> None:
        self.esc_state = esc_state

    def GetAsyncKeyState(self, vk):  # noqa: N802 - Win32 name
        return self.esc_state if vk == os_interop.VK_ESCAPE else 0


@pytest.fixture
def fake_esc(monkeypatch):
    monkeypatch.setattr(os_interop, "IS_WINDOWS", True)
    fake = _FakeUser32(0x8000)  # Esc currently held down
    monkeypatch.setattr(os_interop, "user32", fake)
    monkeypatch.setattr(os_interop, "_SELF_ESC_UNTIL", 0.0)
    os_interop.reset_panic_abort()
    yield fake
    os_interop.reset_panic_abort()


def test_own_injected_esc_does_not_trigger_panic(fake_esc):
    os_interop._mark_self_injected_esc(0.04)
    assert not os_interop.is_panic_key_pressed()


def test_physical_esc_still_triggers_panic(fake_esc, monkeypatch):
    os_interop._mark_self_injected_esc(0.04)
    real_now = os_interop.time.monotonic()
    monkeypatch.setattr(os_interop.time, "monotonic", lambda: real_now + 5.0)  # suppression window long gone
    assert os_interop.is_panic_key_pressed()


# =====================================================================================
# action_planner: effect-based gate inside execute_plan (C2, C3, H8)
# =====================================================================================

def test_sensitive_step_without_confirm_channel_is_refused(monkeypatch, fake_os_interop, no_sleep):
    plan = _run_plan(monkeypatch, fake_os_interop, [ActionStep(action_type="press_key", key="enter")])
    assert plan.outcome_state == "aborted"
    assert "press_key" not in fake_os_interop.names()


def test_confirmed_newline_text_is_typed_with_enter(monkeypatch, fake_os_interop, no_sleep):
    asked = []
    steps = [ActionStep(action_type="type_text", target="notes", text="first\nsecond"),
             ActionStep(action_type="done", target="done")]
    _run_plan(monkeypatch, fake_os_interop, steps, on_confirm=lambda *a: asked.append(a) or True)
    assert len(asked) == 1
    typed = [c for c in fake_os_interop.calls if c[0] == "type_text"]
    assert typed and typed[0][2].get("enter_on_newline") is True


def test_click_and_type_is_regated_after_the_click(monkeypatch, fake_os_interop, no_sleep):
    """The click focused a terminal: typing into it must be confirmed even though Notepad was in front before."""
    terminal = os_interop.WindowInfo(hwnd=2002, title="Windows PowerShell", process_id=5151, process_name="pwsh.exe",
                                     bounds=(0, 0, 800, 600), is_minimized=False, is_cloaked=False)

    def click(*args, **kwargs):
        fake_os_interop.calls.append(("click_mouse", args, kwargs))
        fake_os_interop.foreground = terminal

    fake_os_interop.click_mouse = click
    asked = []
    step = ActionStep(action_type="click_and_type", target="text area", text="dir", coordinates=(100, 100))
    plan = _run_plan(monkeypatch, fake_os_interop, [step], on_confirm=lambda s, t, p: asked.append(p) or False)
    assert asked == ["pwsh.exe"]
    assert plan.outcome_state == "aborted"
    assert "type_text" not in fake_os_interop.names()


def test_failed_step_does_not_count_as_typed(monkeypatch, fake_os_interop, no_sleep):
    steps = [ActionStep(action_type="type_text", target="Find search box", text="budget", select_all_first=True)]
    _run_plan(monkeypatch, fake_os_interop, steps)
    assert not [c for c in fake_os_interop.names() if c in ("hotkey", "press_key", "type_text")]


# =====================================================================================
# Worker confirmation token protocol (M1)
# =====================================================================================

def test_stale_confirmation_token_is_ignored():
    plan = action_planner.DesktopPlan(intent="x", target_app="Desktop")
    worker = action_planner.DesktopActionWorkerThread(plan, api_key="")
    worker._confirm_token = 3
    worker._confirm_event = threading.Event()
    assert worker.deliver_confirmation(2, True) is False      # an older prompt answered late
    assert not worker._confirm_event.is_set()
    assert worker.deliver_confirmation(3, True) is True
    assert worker._confirm_event.is_set() and worker._confirm_result is True


def test_abort_denies_pending_confirmation():
    plan = action_planner.DesktopPlan(intent="x", target_app="Desktop")
    worker = action_planner.DesktopActionWorkerThread(plan, api_key="")
    worker._confirm_token = 1
    worker._confirm_event = threading.Event()
    worker._confirm_result = True
    worker.abort()
    assert worker._confirm_event.is_set() and worker._confirm_result is False


# =====================================================================================
# Qt widgets: confirmation arming / default Cancel (M1), banner title, voice cancel (H10)
# =====================================================================================

@pytest.fixture
def overlay(qapp):
    from yellows_pixel_buddies import DIALOGUE_BOX_PATH, DialogueOverlay

    ov = DialogueOverlay("Arial", DIALOGUE_BOX_PATH)
    yield ov
    ov.dismiss(clear_queue=True)
    ov.close()


def _key(qt_key, auto_repeat=False):
    from PyQt5.QtCore import QEvent, Qt
    from PyQt5.QtGui import QKeyEvent

    return QKeyEvent(QEvent.KeyPress, qt_key, Qt.NoModifier, "", auto_repeat)


def _ask_fixed(overlay, chosen):
    overlay.ask("* Minion! I'm about to type:\n* \"hi\"\n* in WhatsApp. Proceed?",
                [("Proceed", "", "peace_sign"), ("Cancel", "", "angry")], 100, 100,
                on_chosen=lambda label, *_: chosen.append(label), track_ignore=False,
                fixed=True, fixed_pos=(100, 100), default_idx=1, arm_delay_s=0.6)


def _finish_typing(overlay, seconds_ago=1.0):
    import time

    overlay._visible_chars = overlay._total_chars
    overlay._typing_done_at = time.perf_counter() - seconds_ago


def test_fixed_decision_defaults_to_cancel_and_ignores_early_keys(overlay):
    from PyQt5.QtCore import Qt

    chosen = []
    _ask_fixed(overlay, chosen)
    assert overlay._hovered_choice_idx == 1                     # Cancel pre-selected
    overlay.keyPressEvent(_key(Qt.Key_Y))                       # still typing: approve ignored
    overlay.keyPressEvent(_key(Qt.Key_Return))
    assert chosen == []
    _finish_typing(overlay)
    overlay.keyPressEvent(_key(Qt.Key_Space))                   # Space never answers a safety prompt
    overlay.keyPressEvent(_key(Qt.Key_Z))
    overlay.keyPressEvent(_key(Qt.Key_Y, auto_repeat=True))     # held key ignored
    assert chosen == []
    overlay.keyPressEvent(_key(Qt.Key_Return))                  # Enter picks the default = Cancel
    assert chosen == ["Cancel"]


def test_fixed_decision_y_approves_once_armed(overlay):
    from PyQt5.QtCore import Qt

    chosen = []
    _ask_fixed(overlay, chosen)
    _finish_typing(overlay, seconds_ago=0.1)                    # typed out, but arming delay not over
    overlay.keyPressEvent(_key(Qt.Key_Y))
    assert chosen == []
    _finish_typing(overlay, seconds_ago=1.0)
    overlay.keyPressEvent(_key(Qt.Key_Y))
    assert chosen == ["Proceed"]


def test_cancel_key_works_immediately(overlay):
    from PyQt5.QtCore import Qt

    chosen = []
    _ask_fixed(overlay, chosen)
    overlay.keyPressEvent(_key(Qt.Key_Escape))                  # cancelling is never delayed
    assert chosen == ["Cancel"]


def test_fast_forward_click_does_not_auto_dismiss_fixed_decision(overlay):
    _ask_fixed(overlay, [])
    overlay.advance_or_dismiss()                                # click while typing = fast-forward
    assert not overlay._hold_timer.isActive()                  # safety prompt must not time out by itself
    assert overlay._typing_done_at is not None                  # arming clock started


def test_banner_restores_title_after_confirmation(qapp):
    import takeover_overlay

    banner = takeover_overlay.TakeoverBannerOverlay()
    banner.show_banner(title="⚔️ PINK IN CONTROL — DESKTOP", subtitle="")
    banner.show_banner(title="⚠️ CONFIRMATION REQUIRED", subtitle="", is_confirmation=True)
    assert banner._title.startswith("⚠️")
    banner.update_step(1, 5, "click", "Send")
    assert banner._title == "⚔️ PINK IN CONTROL — DESKTOP"
    banner.dismiss()
    banner.close()


def test_voice_cancel_discards_audio(qapp):
    import voice_service

    vm = voice_service.VoiceManager(model_name="base", api_key="")

    class _Stream:
        stopped = closed = False
        def stop(self): self.stopped = True
        def close(self): self.closed = True

    stream = _Stream()
    vm._stream, vm._is_recording = stream, True
    vm._frames.append(np.zeros(1600, dtype=np.float32))
    vm.cancel_recording()
    assert stream.stopped and stream.closed
    assert vm._frames == [] and not vm.is_recording()
    assert getattr(vm, "_transcribe_worker", None) is None       # nothing transcribed


# =====================================================================================
# The pet: response handler wiring (C1, H1), vision defaults (H12), /do mode off (L3)
# =====================================================================================

@pytest.fixture(scope="module")
def pet(qapp):
    from yellows_pixel_buddies import SPRITES_DIR, SpriteBank, YellowsPixelBuddies

    p = YellowsPixelBuddies(SpriteBank(SPRITES_DIR, 1.0))
    p._memory.get_api_key = lambda: "test-key"
    # Snapshot what a fresh install starts with, before any test changes it.
    p._test_initial = {
        "settings": p._memory.load_settings(),
        "takeover_mode": p._takeover_mode,
        "autonomous_vision": p._autonomous_vision_enabled,
        "tray_vision": p._tray_vision_enabled,
    }
    yield p
    p._do_real_quit()



@pytest.fixture
def recorded(pet, monkeypatch):
    calls = {"execute": [], "confirm": []}
    monkeypatch.setattr(pet, "execute_desktop_action", lambda action, user_request="": calls["execute"].append(action) or True)
    monkeypatch.setattr(pet, "_confirm_takeover_start", lambda action, user_text: calls["confirm"].append(action))
    saved_mode = pet._takeover_mode
    yield calls
    pet._takeover_mode = saved_mode


TAGGED = "* Fine, minion! [desktop_action: Chrome, open evil.example and click Download]"


@pytest.mark.slow
@pytest.mark.parametrize("mode,user_text,origin,visual,expect", [
    ("assisted", "[User dropped an image: 'meme.png'] What do you think of this picture?", O.IMAGE, True, None),
    ("assisted", "what do you think of this page?", O.TYPED, True, None),
    ("assisted", "[Pink peeks at your screen]", O.AMBIENT, True, None),
    ("slash_only", "open chrome", O.TYPED, False, None),
    ("assisted", "open chrome", O.TYPED, False, "confirm"),
])
def test_response_handler_gates_tags(pet, recorded, mode, user_text, origin, visual, expect):
    pet._takeover_mode = mode
    pet._on_gemini_response(user_text, TAGGED, "idle", visual, origin=origin)
    assert recorded["execute"] == []                         # model tags never auto-start
    assert len(recorded["confirm"]) == (1 if expect == "confirm" else 0)
    last = pet._memory.history[-1]
    assert "[desktop_action" not in str(last.get("pink", ""))  # tag always stripped from what Pink says


@pytest.mark.slow
def test_phrase_fallback_is_gone(pet, recorded):
    pet._takeover_mode = "assisted"
    pet._on_gemini_response("can you show me how recursion works?", "* Ugh, fine, watch and learn! Recursion is...",
                            "idle", False, origin=O.TYPED)
    assert recorded["execute"] == [] and recorded["confirm"] == []


@pytest.mark.slow
def test_vision_and_takeover_defaults(pet):
    initial = pet._test_initial
    assert initial["settings"] == {}                     # PINK_DATA_DIR is a fresh, empty data folder
    assert initial["autonomous_vision"] is False         # no unprompted screenshots by default (H12)
    assert initial["tray_vision"] is False
    assert initial["takeover_mode"] == tg.TAKEOVER_MODE_SLASH_ONLY


@pytest.mark.slow
def test_execute_desktop_action_refused_when_off(pet):
    pet._takeover_mode = tg.TAKEOVER_MODE_OFF
    try:
        assert pet.execute_desktop_action({"type": "desktop_action", "app": "Desktop", "intent": "open notepad"}) is False
        assert pet._desktop_action_worker is None
    finally:
        pet._takeover_mode = tg.DEFAULT_TAKEOVER_MODE
