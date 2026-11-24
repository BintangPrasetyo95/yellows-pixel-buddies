"""Phase 5 (takeover architecture) tests. See temp/IMPLEMENTATION_PLAN.md §8.

M8 TakeoverController (one state, one teardown) · 5.2 InputBackend seam · 5.3 StepPolicy / Observer ·
5.4 per-session PanicLatch · L5 one input-transparency helper. Golden replays live in test_takeover_replay.py.
No real input is sent: controllers get fake hosts/workers, executors get RecordingInput.
"""
from __future__ import annotations

import types

import pytest

import action_planner
import os_interop
import takeover_controller as tc
import takeover_gate

ActionStep = action_planner.ActionStep
TS = tc.TakeoverState


# =====================================================================================
# TakeoverController with a fake host and worker
# =====================================================================================

class _Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def rec(*a, **k):
            self.calls.append(name)
            return True
        return rec


class _Overlay(_Recorder):
    def __init__(self):
        super().__init__()
        self.pending = False
        self.on_chosen = self.on_cancel = None

    def ask(self, text, choices, x, y, on_chosen=None, on_cancel=None, **k):
        self.calls.append("ask")
        self.pending, self.on_chosen, self.on_cancel, self.choices = True, on_chosen, on_cancel, choices
        return True

    def has_pending_fixed_decision(self):
        return self.pending

    def dismiss(self, clear_queue=False):
        self.calls.append("dismiss")
        self.pending = False


class _Worker:
    def __init__(self, plan=None, api_key="", parent=None, latch=None):
        self.plan, self.latch = plan, latch
        self.running = False
        self.aborts = 0
        self.answers = []

    def start(self):
        self.running = True

    def isRunning(self):  # noqa: N802 - Qt name
        return self.running

    def abort(self):
        self.aborts += 1
        self.running = False

    def deliver_confirmation(self, token, approved):
        self.answers.append((token, approved))
        return True


def _host():
    return types.SimpleNamespace(
        _takeover_mode=takeover_gate.TAKEOVER_MODE_SLASH_ONLY, _phase=types.SimpleNamespace(name="PAUSE"),
        _memory=None, _language="en", _dialogue_overlay=_Overlay(), _voice_overlay=None, _voice_mode_enabled=False,
        _takeover_banner=_Recorder(), _target_reticle=_Recorder(), _question_token=0,
        _decision_box_pos=lambda: (0, 0), said=[],
    )


@pytest.fixture
def ctrl(qapp, monkeypatch):
    monkeypatch.setattr(os_interop, "set_window_exclude_from_capture", lambda *a, **k: True)
    host = _host()
    host._say = lambda text, **k: host.said.append(text)
    workers = []

    def factory(*a, **k):
        w = _Worker(*a, **k)
        workers.append(w)
        return w

    c = tc.TakeoverController(host, worker_factory=factory, abort_reaction="laughing")
    states = []
    c.state_changed.connect(states.append)
    c.test_states, c.test_workers = states, workers
    return c


def _start(c):
    assert c.start({"type": "desktop_action", "app": "Desktop", "intent": "open notepad"}, user_request="open notepad")
    return c.test_workers[-1]


def test_start_runs_a_worker_with_a_fresh_latch(ctrl):
    w = _start(ctrl)
    assert ctrl.state is TS.RUNNING and ctrl.is_active and w.running
    assert w.latch is ctrl.latch is os_interop.current_panic_latch()
    assert ctrl.test_states == [TS.RUNNING]
    assert ctrl.host._question_token == 1          # no question may pop up mid-takeover


def test_start_refusals(ctrl):
    ctrl.host._takeover_mode = takeover_gate.TAKEOVER_MODE_OFF
    assert not ctrl.start({"intent": "x"}, "x")
    ctrl.host._takeover_mode = takeover_gate.TAKEOVER_MODE_SLASH_ONLY
    ctrl.host._phase = types.SimpleNamespace(name="HIDE_PEEK")
    assert not ctrl.start({"intent": "x"}, "x")
    ctrl.host._phase = types.SimpleNamespace(name="PAUSE")
    _start(ctrl)
    assert not ctrl.start({"intent": "y"}, "y")      # one session at a time
    assert len(ctrl.test_workers) == 1


def test_teardown_is_idempotent(ctrl):
    w = _start(ctrl)
    ctrl.abort("one")
    ctrl.abort("two")
    ctrl.abort("three")
    ctrl._on_plan_finished(True, "late finish signal")
    assert ctrl.teardown_count == 1
    assert w.aborts == 1
    assert ctrl.host._takeover_banner.calls.count("dismiss") == 1
    assert ctrl.state is TS.IDLE and ctrl.last_reaction == "laughing"
    assert ctrl.test_states == [TS.RUNNING, TS.STOPPING, TS.IDLE]
    assert len(ctrl.host.said) == 1                  # one "I let go" line, no "All done" afterwards


def test_finish_tears_down_once_with_its_reaction(ctrl):
    _start(ctrl)
    ctrl._on_plan_finished(False, "Could not find it")
    ctrl.abort("after the fact")
    assert ctrl.teardown_count == 1 and ctrl.last_reaction == "angry"
    assert "Could not find it" in ctrl.host.said[0]


def test_confirmation_round_trip(ctrl):
    w = _start(ctrl)
    ctrl.show_confirmation(5, "type_text", "box", "on my way", "Mom - WhatsApp", "whatsapp.exe")
    assert ctrl.state is TS.AWAITING_CONFIRM and ctrl.awaiting_confirm
    ctrl.confirm(4, True)                            # stale token: ignored
    assert w.answers == []
    ctrl.host._dialogue_overlay.on_chosen("Proceed", "", None)
    assert w.answers == [(5, True)] and ctrl.state is TS.RUNNING


def test_closing_the_prompt_denies(ctrl):
    w = _start(ctrl)
    ctrl.show_confirmation(6, "press_key", "enter", "", "Chat", "discord.exe")
    ctrl.host._dialogue_overlay.on_cancel()
    assert w.answers == [(6, False)] and not ctrl.awaiting_confirm


def test_confirmation_after_the_session_is_denied(ctrl):
    w = _start(ctrl)
    ctrl.abort("gone")
    ctrl.show_confirmation(7, "type_text", "box", "x", "t", "p")
    assert w.answers == [(7, False)] and "ask" not in ctrl.host._dialogue_overlay.calls


def test_watchdog(ctrl):
    w = _start(ctrl)
    assert ctrl.check_watchdog(ctrl.last_progress + 1) is False
    ctrl.show_confirmation(8, "type_text", "box", "x", "t", "p")
    assert ctrl.check_watchdog(ctrl.last_progress + 10_000) is False    # waiting on the user is not a stall
    ctrl.confirm(8, False)
    assert ctrl.check_watchdog(ctrl.last_progress + ctrl.stall_timeout_s + 1) is True
    assert w.aborts == 1 and ctrl.state is TS.IDLE


def test_watchdog_worker_gone(ctrl):
    w = _start(ctrl)
    w.running = False
    assert ctrl.check_watchdog(ctrl.last_progress) is True and ctrl.teardown_count == 1


# =====================================================================================
# 5.4 per-session PanicLatch
# =====================================================================================

def test_each_session_gets_a_fresh_latch():
    old = os_interop.reset_panic_abort()
    old.trigger()
    assert os_interop.is_panic_key_pressed()
    new = os_interop.reset_panic_abort()
    assert new is not old and not new.triggered
    old.trigger()                                    # a late abort from the previous session...
    assert not os_interop.current_panic_latch().triggered   # ...can't touch the new one


def test_latch_pull_away_and_reanchor(monkeypatch):
    latch = os_interop.reset_panic_abort()
    latch.set_anchor(100, 100)
    assert latch.pulled_away((150, 150)) is False
    monkeypatch.setattr(os_interop, "get_cursor_pos", lambda: (900, 900))
    os_interop.reanchor_automated_cursor()           # the user moved to the confirmation bubble
    assert latch.cursor_anchor == (900, 900) and latch.pulled_away((910, 905)) is False
    assert latch.pulled_away((100, 100)) is True and latch.triggered
    os_interop.reset_panic_abort()


def test_executor_uses_the_controllers_latch(fake_os_interop, no_sleep, monkeypatch):
    latch = os_interop.PanicLatch()
    ex = action_planner.DesktopActionExecutor(api_key="t", latch=latch, input_backend=os_interop.RecordingInput())
    ex.abort()
    assert latch.triggered


# =====================================================================================
# 5.2 InputBackend
# =====================================================================================

def test_real_input_delegates_to_its_ops():
    ops = _Recorder()
    ri = os_interop.RealInput(ops)
    ri.move(1, 2)
    ri.click(1, 2)
    ri.type_text("hi", expected_hwnd=3)
    ri.press_key("tab")
    ri.hotkey("ctrl", "t")
    ri.scroll(-3)
    ri.foreground_window()
    assert ops.calls == ["smooth_move_mouse", "click_mouse", "type_text", "press_key", "hotkey", "scroll_mouse",
                         "get_foreground_window"]


def test_recording_input_without_inner_sends_nothing():
    rec = os_interop.RecordingInput(foreground=lambda: "FG")
    rec.type_text("secret", delay_between_chars_s=0.01, expected_hwnd=5)
    rec.click(1, 2, interval_s=0.06)
    assert rec.calls == [["type_text", ["secret"], {"expected_hwnd": 5}], ["click", [1, 2], {"button": "left", "clicks": 1}]]
    assert rec.foreground_window() == "FG"


def test_executor_input_goes_through_the_backend(fake_os_interop, no_sleep, monkeypatch):
    rec = os_interop.RecordingInput(foreground=lambda: fake_os_interop.foreground)
    ex = action_planner.DesktopActionExecutor(api_key="t", input_backend=rec)
    out = ex._execute_step(ActionStep(action_type="hotkey", keys=["ctrl", "t"], target="new tab"), "", (10, 10), (0, 0))
    assert out.startswith("Pressed hotkey") and rec.calls == [["hotkey", ["ctrl", "t"], {}]]
    assert "hotkey" not in fake_os_interop.names()


def test_coords_pure_with_metrics(monkeypatch):
    monkeypatch.setattr(os_interop, "get_screen_metrics", lambda: (_ for _ in ()).throw(AssertionError("live read")))
    m = os_interop.ScreenMetrics(virtual_left=-1920, virtual_top=0, virtual_width=3840, virtual_height=1080,
                                 primary_width=1920, primary_height=1080)
    nx, ny = os_interop.coords_to_normalized_virtual(-1920, 0, metrics=m)
    assert nx * 3840 // 65536 - 1920 == -1920 and ny * 1080 // 65536 == 0


# =====================================================================================
# L5 input transparency style math
# =====================================================================================

T, L, N = 0x20, 0x80000, 0x08000000


@pytest.mark.parametrize("style,enabled,kw,expected", [
    (0x100, True, {}, 0x100 | T | L | N),
    (0x100 | T | L | N, False, {}, 0x100 | L),                         # symmetric: NOACTIVATE removed, LAYERED kept
    (0x100 | L, True, {"noactivate": False, "layered": False}, 0x100 | L | T),   # Pink's own window
    (0x100 | L | T | N, False, {"noactivate": False}, 0x100 | L | N),   # not ours to remove
])
def test_input_transparent_style(style, enabled, kw, expected):
    assert os_interop.input_transparent_style(style, enabled, **kw) == expected


# =====================================================================================
# 5.3 StepPolicy (pure) and Observer
# =====================================================================================

def _progress(**kw):
    p = action_planner.PlanProgress(goal_lower=kw.pop("goal", "reply to mom saying hi"),
                                    needs_text_submission=kw.pop("needs_text", True), is_close_goal=False)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


POLICY = action_planner.StepPolicy()


def test_premature_done_rejected_until_text_typed():
    p = _progress()
    assert POLICY.review_done(p, ActionStep(action_type="done"), 2).kind == "skip"
    p.has_typed_final_text = True
    assert POLICY.review_done(p, ActionStep(action_type="done"), 3).kind == "finish"


def test_search_guard_rewrites_step():
    step = ActionStep(action_type="click_and_type", target="Search contacts", text="Mom", press_enter=True,
                      coordinates=(1, 1), done_after_this=True)
    assert POLICY.before_run(_progress(), step, 1, prevent_search_enter=True).kind == "run"
    assert step.press_enter is False and step.select_all_first is True and step.done_after_this is False


@pytest.mark.parametrize("prev_terminal,typed,expected", [(False, True, "skip"), (True, True, "finish")])
def test_duplicate_typing(prev_terminal, typed, expected):
    p = _progress(last_typed_text="hi", last_global_diff=5.0, prev_step_was_terminal_candidate=prev_terminal,
                  has_typed_final_text=typed)
    assert POLICY.before_run(p, ActionStep(action_type="type_text", target="box", text="Hi"), 3, True).kind == expected


def test_duplicate_click_skipped_when_screen_changed():
    p = _progress(last_click_coords=(100, 100), last_local_diff=5.0)
    v = POLICY.before_run(p, ActionStep(action_type="click", target="row", coordinates=(110, 105)), 2, True)
    assert v.kind == "skip" and "DUPLICATE CLICK" in v.note
    p2 = _progress(last_click_coords=(100, 100), last_global_diff=0.0, last_local_diff=0.0)   # nothing changed
    assert POLICY.before_run(p2, ActionStep(action_type="click", target="row", coordinates=(110, 105)), 2, True).kind == "run"


def test_record_executed_tracks_progress():
    p = _progress()
    POLICY.record_executed(p, ActionStep(action_type="click_and_type", target="Message box", text="hi",
                                         press_enter=True, coordinates=(5, 5)))
    assert p.has_typed_final_text and p.prev_step_was_terminal_candidate and p.last_click_coords == (5, 5)
    POLICY.record_executed(p, ActionStep(action_type="type_text", target="Search", text="mom"))
    assert p.last_typed_text == "mom"
    POLICY.record_failed(p)
    assert p.prev_step_was_terminal_candidate is False


def test_observer_bundles_one_observation(fake_os_interop, monkeypatch):
    from PIL import Image
    img = Image.new("RGB", (40, 30))

    def cap(*a, **k):
        action_planner._LAST_RAW_SCREENSHOT = img
        return "QUJD", 40, 30, (7, 8)

    monkeypatch.setattr(action_planner, "capture_screen_region", cap)
    obs = action_planner.Observer().observe(None)
    assert (obs.b64, obs.image, obs.size, obs.offset, obs.fg_hwnd) == ("QUJD", img, (40, 30), (7, 8), 1001)
    assert "Notepad" in obs.fg_desc and obs.captured_at > 0
