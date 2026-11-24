"""Phase 4 (takeover correctness: "it clicks the wrong thing") regression tests. See temp/IMPLEMENTATION_PLAN.md §7.

H2 confirm focus · H5 window aliases · H6 stale steps · H7 live foreground context · M1 full-text view ·
M2 modal decisions · M3 strict decisions · M4 app inference / message payload · M5 voice HUD · M7 tag merge ·
L1 reticle mapping · L2 mouse coordinates · L4 second launch.
Every executor test uses fake_os_interop: no real input, no real screen reads.
"""
from __future__ import annotations

import os
import types

import pytest
from PIL import Image

import action_planner
import os_interop
import takeover_controller
import takeover_overlay
import yellows_pixel_buddies as ypb

ActionStep = action_planner.ActionStep


def _win(hwnd, title, proc, pid=None):
    return os_interop.WindowInfo(hwnd=hwnd, title=title, process_id=pid if pid is not None else 5000 + hwnd,
                                 process_name=proc, bounds=(0, 0, 800, 600), is_minimized=False, is_cloaked=False)


def _run_plan(monkeypatch, steps, on_confirm=None, request="reply to Mom saying on my way", img=None,
              decide_hook=None):
    image = img or Image.new("RGB", (64, 64), "white")

    def fake_capture(*_a, **_k):
        action_planner._LAST_RAW_SCREENSHOT = image
        return "ZmFrZQ==", image.width, image.height, (0, 0)

    scripted = iter(steps)

    def fake_decide(*_a, **_k):
        step = next(scripted, ActionStep(action_type="fail", target="script exhausted"))
        if decide_hook:
            decide_hook(step)
        return step

    monkeypatch.setattr(action_planner, "capture_screen_region", fake_capture)
    monkeypatch.setattr(action_planner, "ground_ui_element", lambda *a, **k: None)
    monkeypatch.setattr(action_planner.DesktopActionExecutor, "_decide_next_step", fake_decide)
    plan = action_planner.create_desktop_plan(intent=request, target_app="Desktop", user_request=request)
    action_planner.DesktopActionExecutor(api_key="test").execute_plan(plan, on_confirm_action=on_confirm)
    return plan


# =====================================================================================
# H2 - after approval, keystrokes go to the window focused AFTER the click, never to Pink
# =====================================================================================

def test_typing_targets_the_post_click_window(monkeypatch, fake_os_interop, no_sleep):
    chat = _win(77, "Mom - WhatsApp", "whatsapp.exe")

    def click(*args, **kwargs):
        fake_os_interop.calls.append(("click_mouse", args, kwargs))
        fake_os_interop.foreground = chat

    fake_os_interop.click_mouse = click
    step = ActionStep(action_type="click_and_type", target="Message box", text="on my way", coordinates=(10, 10))
    _run_plan(monkeypatch, [step])
    typed = [c for c in fake_os_interop.calls if c[0] == "type_text"]
    assert typed and typed[0][2]["expected_hwnd"] == 77


def test_never_types_into_pinks_own_window(monkeypatch, fake_os_interop, no_sleep):
    pink = _win(9, "Pink", "python.exe", pid=os.getpid())

    def click(*args, **kwargs):
        fake_os_interop.calls.append(("click_mouse", args, kwargs))
        fake_os_interop.foreground = pink   # e.g. the confirmation bubble kept focus

    fake_os_interop.click_mouse = click
    step = ActionStep(action_type="click_and_type", target="Message box", text="hello", coordinates=(10, 10))
    _run_plan(monkeypatch, [step])
    assert "type_text" not in fake_os_interop.names()


def test_bare_keys_refused_while_pink_has_focus(monkeypatch, fake_os_interop, no_sleep):
    fake_os_interop.foreground = _win(9, "Pink chat", "python.exe", pid=os.getpid())
    _run_plan(monkeypatch, [ActionStep(action_type="press_key", key="tab")], request="move focus")
    assert "press_key" not in fake_os_interop.names()


def test_approval_reanchors_the_cursor(monkeypatch, fake_os_interop, no_sleep):
    step = ActionStep(action_type="type_text", target="Message input", text="on my way", press_enter=True)
    _run_plan(monkeypatch, [step], on_confirm=lambda *a: True)
    assert "reanchor_automated_cursor" in fake_os_interop.names()


# =====================================================================================
# H5 - an app's identity is not "any window of a process that could host it"
# =====================================================================================

def _windows(monkeypatch, wins):
    monkeypatch.setattr(os_interop, "list_windows", lambda *a, **k: list(wins))


def test_closed_whatsapp_is_not_a_random_chrome_tab(monkeypatch):
    _windows(monkeypatch, [_win(2, "GitHub - Google Chrome", "chrome.exe"), _win(3, "main.py - Visual Studio Code", "code.exe")])
    assert os_interop.find_window("whatsapp") is None
    assert os_interop.find_window("terminal") is None        # VS Code is not "the terminal"


def test_whatsapp_web_tab_and_native_app(monkeypatch):
    web = _win(4, "(2) WhatsApp - Google Chrome", "chrome.exe")
    native = _win(5, "WhatsApp", "WhatsApp.exe")
    _windows(monkeypatch, [web])
    assert os_interop.find_window("whatsapp") is web
    _windows(monkeypatch, [web, native])
    assert os_interop.find_window("whatsapp") is native     # the real app wins


def test_window_matches_app():
    assert os_interop.window_matches_app(_win(1, "WhatsApp - Google Chrome", "chrome.exe"), "WhatsApp")
    assert not os_interop.window_matches_app(_win(1, "GitHub - Google Chrome", "chrome.exe"), "WhatsApp")
    assert os_interop.window_matches_app(_win(1, "Untitled - Notepad", "notepad.exe"), "notepad")
    assert not os_interop.window_matches_app(None, "notepad")


def test_simple_open_reports_success_only_for_the_right_window(monkeypatch, fake_os_interop, no_sleep):
    # focus_window "succeeds" but the foreground is still some Chrome tab: not "Opened WhatsApp"
    fake_os_interop.foreground = _win(2, "GitHub - Google Chrome", "chrome.exe")
    plan = _run_plan(monkeypatch, [ActionStep(action_type="focus_window", target="WhatsApp")], request="open whatsapp")
    assert not plan.success


# =====================================================================================
# H6 - never act on a stale screenshot
# =====================================================================================

def test_step_skipped_when_focus_changed_while_deciding(monkeypatch, fake_os_interop, no_sleep):
    other = _win(55, "Visual Studio Code", "code.exe")

    def user_alt_tabs(_step):
        fake_os_interop.foreground = other   # happens while Gemini "thinks"

    steps = [ActionStep(action_type="hotkey", keys=["ctrl", "w"], target="close tab")]
    plan = _run_plan(monkeypatch, steps, request="close this chrome tab", decide_hook=user_alt_tabs)
    assert "hotkey" not in fake_os_interop.names()
    assert not plan.success


def test_step_skipped_when_decision_is_too_old(monkeypatch, fake_os_interop, no_sleep):
    clock = {"t": 1000.0}
    monkeypatch.setattr(action_planner.time, "monotonic", lambda: clock["t"])

    def slow_model(_step):
        clock["t"] += action_planner.STEP_DECISION_BUDGET_S + 5

    steps = [ActionStep(action_type="click", target="Send", coordinates=(10, 10))]
    _run_plan(monkeypatch, steps, request="click the button", decide_hook=slow_model)
    assert "click_mouse" not in fake_os_interop.names()


def test_step_skipped_when_target_area_moved(monkeypatch, fake_os_interop, no_sleep):
    observed = Image.new("RGB", (400, 300), "white")
    moved = Image.new("RGB", (240, 160), "black")            # a popup now covers the target
    fake_os_interop.screen_patches = [moved, moved.copy()]   # stable after the change -> a real shift
    steps = [ActionStep(action_type="click", target="Send", coordinates=(200, 150))]
    _run_plan(monkeypatch, steps, request="click the button", img=observed)
    assert "click_mouse" not in fake_os_interop.names()


def test_animated_target_area_is_not_a_shift(fake_os_interop):
    observed = Image.new("RGB", (400, 300), "white")
    fake_os_interop.screen_patches = [Image.new("RGB", (240, 160), "black"), Image.new("RGB", (240, 160), "red")]
    assert action_planner.target_region_shifted(observed, (0, 0), (200, 150)) is False


def test_unchanged_target_area_runs(monkeypatch, fake_os_interop, no_sleep):
    observed = Image.new("RGB", (400, 300), "white")
    fake_os_interop.screen_patches = [Image.new("RGB", (240, 160), "white")]
    steps = [ActionStep(action_type="click", target="Play", coordinates=(200, 150))]
    _run_plan(monkeypatch, steps, request="click the button", img=observed)
    assert "click_mouse" in fake_os_interop.names()


# =====================================================================================
# M3 - strict decision parsing
# =====================================================================================

def _decision(**kw):
    base = {"self_check": "initial", "action": "type_text", "target": "box", "text": "hi"}
    base.update(kw)
    return base


def test_string_false_is_false():
    step = action_planner.step_from_decision(_decision(press_enter="false", select_all_first="False",
                                                       done_after_this="0"), (1000, 1000), (0, 0))
    assert step.press_enter is False and step.select_all_first is False and step.done_after_this is False
    assert action_planner.step_from_decision(_decision(press_enter="true"), (1000, 1000), (0, 0)).press_enter is True


@pytest.mark.parametrize("bad", [
    {"action": "format_disk"},
    {"action": "scroll", "scroll_clicks": "lots"},
    {"action": "hotkey", "keys": None},
    {"action": "press_key", "key": None},
    {"action": "click", "box_2d": [1, 2, 3]},
    {"action": "type_text", "text": None},
])
def test_schema_violations_raise(bad):
    with pytest.raises(action_planner.DecisionSchemaError):
        action_planner.step_from_decision(_decision(**bad), (1000, 1000), (0, 0))


def test_no_bare_box_fallback_for_decisions():
    assert action_planner._parse_json_object("I would click [100, 200, 300, 400] probably") is None
    assert action_planner._parse_grounding_json("[100, 200, 300, 400]")["box_2d"] == [100, 200, 300, 400]


def test_decide_reasks_once_then_fails(monkeypatch, fake_os_interop):
    replies = iter([{"action": "nonsense"}, _decision(action="wait")])
    calls = []

    def fake_call(*a, **k):
        calls.append(k)
        return next(replies)

    monkeypatch.setattr(action_planner, "_call_gemini_json", fake_call)
    ex = action_planner.DesktopActionExecutor(api_key="k")
    plan = action_planner.DesktopPlan(intent="x", target_app="Desktop")
    step = ex._decide_next_step(plan, 0, 5, [], "b64", (100, 100), (0, 0))
    assert step.action_type == "wait" and len(calls) == 2
    assert calls[0]["response_schema"] is action_planner.DECISION_RESPONSE_SCHEMA
    assert "INVALID" in calls[1]["user_prompt"]

    replies = iter([{"action": "nonsense"}, {"action": "still nonsense"}])
    step = ex._decide_next_step(plan, 0, 5, [], "b64", (100, 100), (0, 0))
    assert step.action_type == "fail"


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code, self._payload, self.headers, self.text = status, payload or {}, {}, ""

    def json(self):
        return self._payload


def _gemini(text, finish="STOP"):
    return _Resp(200, {"candidates": [{"finishReason": finish, "content": {"parts": [{"text": text}]}}]})


def test_schema_rejected_retries_without_it(monkeypatch):
    sent = []

    def post(url, headers=None, json=None, timeout=None):
        sent.append(dict(json["generationConfig"]))
        return _Resp(400) if "responseSchema" in json["generationConfig"] else _gemini('{"action": "wait"}')

    monkeypatch.setattr(action_planner.requests, "post", post)
    out = action_planner._call_gemini_json("s", "u", None, "k", response_schema={"type": "OBJECT"})
    assert out == {"action": "wait"} and "responseSchema" in sent[0] and "responseSchema" not in sent[1]
    assert sent[0]["responseMimeType"] == "application/json"


def test_truncated_reply_is_reasked_with_more_tokens(monkeypatch):
    budgets = []

    def post(url, headers=None, json=None, timeout=None):
        budgets.append(json["generationConfig"]["maxOutputTokens"])
        return _gemini('{"action": "cl', "MAX_TOKENS") if len(budgets) == 1 else _gemini('{"action": "wait"}')

    monkeypatch.setattr(action_planner.requests, "post", post)
    assert action_planner._call_gemini_json("s", "u", None, "k", max_tokens=300) == {"action": "wait"}
    assert budgets == [300, 600]


# =====================================================================================
# M4 - app inference and "does this goal need typing?"
# =====================================================================================

@pytest.mark.parametrize("text,app", [
    ("type my password into the login box", ""),
    ("find the keyword in this page", ""),
    ("that is an excellent idea", ""),
    ("open it in internet explorer", ""),
    ("open github desktop", ""),
    ("open word and write a letter", "Word"),
    ("open the budget in excel", "Excel"),
    ("open file explorer", "File Explorer"),
    ("tell claude to say hi", "Chrome"),
])
def test_app_inference_whole_words(text, app):
    assert action_planner.infer_target_app(text) == app


@pytest.mark.parametrize("text,payload", [
    ("did Mom reply?", ""),
    ("has Bob answered yet", ""),
    ("reply to Mom", ""),
    ("read Mom's message and Bob's reply", ""),
    ("reply to Mom saying on my way", "on my way"),
    ('send "see you at 5" to Bob', "see you at 5"),
    ("type git status in the terminal", "git status"),
])
def test_message_payload(text, payload):
    assert action_planner.extract_message_payload(text) == payload


def test_read_only_goal_may_finish_without_typing(monkeypatch, fake_os_interop, no_sleep):
    done = ActionStep(action_type="done", target="Mom has not replied yet")
    plan = _run_plan(monkeypatch, [done], request="did Mom reply?")
    assert plan.success and plan.message_text == ""


# =====================================================================================
# M7 - tags are kept in text order and merged into one goal
# =====================================================================================

def test_tags_in_text_order_and_merged():
    text = "* Fine! [type_input: hello] then [desktop_action: Spotify, play lofi] [desktop_action: WhatsApp, reply to Mom saying hi]"
    tags = action_planner.extract_desktop_action_tags(text)
    assert [t["type"] for t in tags] == ["type_input", "desktop_action", "desktop_action"]
    merged = action_planner.merge_desktop_actions(tags)
    assert merged["app"] == "Desktop"
    assert merged["intent"].index("hello") < merged["intent"].index("play lofi") < merged["intent"].index("reply to Mom")
    assert "(in WhatsApp)" in merged["intent"]


def test_single_tag_is_unchanged():
    tags = action_planner.extract_desktop_action_tags("[desktop_action: Chrome, open YouTube Music]")
    assert action_planner.merge_desktop_actions(tags) == tags[0]
    assert action_planner.merge_desktop_actions([]) is None


def test_shop_strips_desktop_tags():
    import shop_window
    lines = shop_window.DeltaruneShopWindow._clean_history_dialogue(
        types.SimpleNamespace(), "* On it! [desktop_action: WhatsApp, reply to Mom] [set_timer: 5m, tea]")
    assert all("desktop_action" not in l and "set_timer" not in l for l in lines)


# =====================================================================================
# L1 reticle mapping · L2 mouse coordinates
# =====================================================================================

def test_reticle_maps_scaled_secondary_monitor():
    screens = [(0, 0, 1920, 1080, 1.0), (1920, 0, 1280, 720, 1.5)]   # second monitor: 1920 px wide at 150%
    assert takeover_overlay.physical_to_logical(960, 540, screens) == (960, 540)
    assert takeover_overlay.physical_to_logical(1920 + 300, 150, screens) == (1920 + 200, 100)
    assert takeover_overlay.physical_to_logical(1920 + 1919, 1079, screens)[0] < 1920 + 1280


@pytest.mark.parametrize("left,width", [(0, 1920), (-1920, 3840), (-1280, 2560)])
def test_mouse_coords_round_trip_every_pixel(monkeypatch, left, width):
    m = os_interop.ScreenMetrics(virtual_left=left, virtual_top=0, virtual_width=width, virtual_height=1080,
                                 primary_width=1920, primary_height=1080)
    monkeypatch.setattr(os_interop, "get_screen_metrics", lambda: m)
    for x in range(left, left + width):
        nx, _ = os_interop.coords_to_normalized_virtual(x, 0)
        assert nx * width // 65536 + left == x


# =====================================================================================
# Pet: M1 full text, M2 modal decisions, M5 voice HUD, H7 context, L4 activation
# =====================================================================================

class _FakeWorker:
    def __init__(self):
        self.answers = []

    def deliver_confirmation(self, token, approved):
        self.answers.append((token, approved))
        return True


class _FakeHud:
    def __init__(self):
        self.visible, self.shown = True, 0

    def isVisible(self):
        return self.visible

    def hide(self):
        self.visible = False

    def show_overlay(self):
        self.visible, self.shown = True, self.shown + 1


@pytest.fixture(scope="module")
def pet(qapp):
    from tests.conftest import shutdown_pet

    p = ypb.YellowsPixelBuddies(ypb.SpriteBank(ypb.SPRITES_DIR, 1.0))
    yield p
    shutdown_pet(p)


@pytest.fixture
def confirming(pet, qapp, monkeypatch):
    monkeypatch.setattr(pet, "_begin_hang", lambda *a, **k: None)   # no physics in these UI tests
    worker = _FakeWorker()
    pet._takeover._open_session(worker, 10)   # the controller adopts a fake worker: state RUNNING
    yield worker
    pet._takeover._teardown(None)
    pet._dialogue_overlay.dismiss(clear_queue=True)
    qapp.processEvents()


@pytest.mark.slow
def test_say_during_confirmation_is_queued_not_replacing(pet, confirming, qapp):
    pet._takeover.show_confirmation(7, "type_text", "box", "on my way", "Mom - WhatsApp", "whatsapp.exe")
    ov = pet._dialogue_overlay
    assert ov.has_pending_fixed_decision()
    pet._say("* An alarm went off!", force=True, record_memory=False)
    assert ov.has_pending_fixed_decision() and ov._deferred_says        # still asking; line waits
    assert not ov.ask("* Wanna play?", [("Yes", "", None), ("No", "", None)], 0, 0, on_chosen=lambda *a: None)
    ov.choose_option(1)                                                   # Cancel
    qapp.processEvents()
    assert confirming.answers == [(7, False)]
    assert not ov._deferred_says                                          # flushed after the answer


@pytest.mark.slow
def test_dismissing_a_confirmation_cancels_it_immediately(pet, confirming, qapp):
    pet._takeover.show_confirmation(8, "type_text", "box", "hi", "Chat", "discord.exe")
    pet._dialogue_overlay.dismiss(clear_queue=True)                       # something else closed the prompt
    qapp.processEvents()
    assert confirming.answers == [(8, False)] and not pet._takeover.awaiting_confirm


@pytest.mark.slow
def test_long_payload_has_show_all_and_banner_restores(pet, confirming, qapp):
    long_text = "x" * 600
    pet._takeover.show_confirmation(9, "type_text", "box", long_text, "Notes", "notepad.exe")
    ov = pet._dialogue_overlay
    labels = [c[0] for c in ov._choices]
    assert labels == ["Proceed", "Cancel", "Show all"]
    ov.choose_option(2)                                                    # Show all: viewer + ask again
    assert pet._takeover.text_viewer is not None
    assert pet._takeover.text_viewer.findChild(ypb.QPlainTextEdit).toPlainText() == long_text
    assert ov.has_pending_fixed_decision() and confirming.answers == []
    ov.choose_option(0)                                                    # Proceed
    assert confirming.answers == [(9, True)] and pet._takeover.text_viewer is None
    assert "CONFIRMATION" not in pet._takeover_banner._title


@pytest.mark.slow
def test_choice_callback_typeerror_is_not_retried(pet, qapp):
    calls = []

    def cb(label, text, anim):
        calls.append(label)
        raise TypeError("bug inside the callback")

    ov = pet._dialogue_overlay
    ov.ask("* Q?", [("A", "", None), ("B", "", None)], 0, 0, on_chosen=cb)
    ov.choose_option(0)
    assert calls == ["A"]
    ov.dismiss(clear_queue=True)


@pytest.mark.slow
def test_voice_hud_returns_for_confirmation_and_after_takeover(pet, confirming, qapp):
    hud = _FakeHud()
    pet._voice_overlay, pet._voice_mode_enabled = hud, True
    pet._takeover.voice_hud_hidden = True
    hud.visible = False
    try:
        pet._takeover.show_confirmation(10, "type_text", "box", "hi", "Chat", "discord.exe")
        assert hud.visible                                  # back so the user can say yes/no
        pet._dialogue_overlay.choose_option(1)
        assert not hud.visible                              # hidden again while the plan runs
        pet._takeover._teardown(None)
        assert hud.visible and not pet._takeover.voice_hud_hidden
    finally:
        pet._voice_overlay, pet._voice_mode_enabled = None, False


@pytest.mark.slow
def test_stale_question_is_dropped(pet):
    pet._question_token += 1
    assert pet._question_may_show(pet._question_token - 1) is False
    pet._takeover._state = takeover_controller.TakeoverState.RUNNING   # bypass signals: no physics here
    try:
        assert pet._question_may_show(None) is False
    finally:
        pet._takeover._state = takeover_controller.TakeoverState.IDLE


def test_foreground_context_skips_pink_and_is_timestamped(monkeypatch):
    ns = types.SimpleNamespace(_current_app_context={"display_name": "Old App"})
    monkeypatch.setattr(ypb, "get_foreground_process_info", lambda: (1, "python.exe", "", "Pink", os.getpid()))
    assert ypb.YellowsPixelBuddies._refresh_foreground_context(ns)["display_name"] == "Old App"
    monkeypatch.setattr(ypb, "get_foreground_process_info",
                        lambda: (2, "chrome.exe", "C:/chrome.exe", "Inbox - Gmail - Google Chrome", 4242))
    ctx = ypb.YellowsPixelBuddies._refresh_foreground_context(ns)
    assert ctx["exe"] == "chrome.exe" and "ts" in ctx


def test_second_launch_ignored_during_takeover():
    ns = types.SimpleNamespace(_takeover=types.SimpleNamespace(is_active=True))   # no show()/raise_()
    ypb.YellowsPixelBuddies.handle_instance_activation(ns)
