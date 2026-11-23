"""Phase 6 (general bug fixes) regression tests. See temp/IMPLEMENTATION_PLAN.md §9.

6A dialogue & chat: H19, H20, M12, L7      6B parsers: H21, M13, M14, L8
6C alarms ship-off: H15                    6D shop: H17, H18, M17, L11, L12
6E voice & sound: M18, L9, M23             6F detection: M16, L6
"""
from __future__ import annotations

import json
import time
import types

import numpy as np
import pytest

from tests.conftest import shutdown_pet

import yellows_pixel_buddies as ypb


# =====================================================================================
# 6B: intent & time parsers (pure)
# =====================================================================================

@pytest.mark.parametrize("text,expected", [
    ("25m", 1500), ("10", 600), ("45s", 45), ("1h30m", 5400), ("2 hours and 15 minutes", 8100),
    ("1m30s", 90), ("1.5m", 90), ("1.5h", 5400), ("1h30", 5400), ("1 hour", 3600), ("30 seconds", 30),
    ("1 hour 20 min", 4800), ("15 menit", 900), ("1 jam", 3600), ("30 detik", 30),
    ("soon", None), ("pomodoro", None), ("5 apples", None), ("", None),
])
def test_parse_duration(text, expected):
    assert ypb.parse_duration_string(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("2:30pm", (14, 30)), ("12am", (0, 0)), ("12pm", (12, 0)), ("08:00", (8, 0)), ("8am", (8, 0)),
    ("7.30 pm", (19, 30)), ("7:30 a.m.", (7, 30)), ("7 malam", (19, 0)), ("07.30 pagi", (7, 30)),
    ("jam 3 sore", (15, 0)), ("12 malam", (0, 0)), ("1 siang", (13, 0)), ("11 siang", (11, 0)),
    ("13pm", None), ("25:00", None), ("later", None),
])
def test_parse_clock(text, expected):
    assert ypb.parse_clock_time(text) == expected


@pytest.mark.parametrize("text,parser,expected", [
    ("1 hour tea break", ypb.parse_duration_string, ("1 hour", "tea break")),
    ("25m Pomodoro", ypb.parse_duration_string, ("25m", "Pomodoro")),
    ("7:30 PM dinner", ypb.parse_clock_time, ("7:30 PM", "dinner")),
    ("08:00 AM Wake up", ypb.parse_clock_time, ("08:00 AM", "Wake up")),
    ("someday maybe", ypb.parse_duration_string, (None, "someday maybe")),
])
def test_split_leading_value(text, parser, expected):
    assert ypb.split_leading_value(text, parser) == expected


@pytest.mark.parametrize("text,expected", [
    ("ok I have to go now, bye!", True), ("brb", True), ("gtg", True), ("gotta run!", True), ("I'm going to bed", True),
    ("I'm off", True), ("see you later!", True), ("bye", True), ("aku pergi dulu", True), ("I have to go to the bank", True),
    ("I'm going to test the build, open VS Code", False), ("reply to Mom on WhatsApp saying bye", False),
    ("I need to run the tests", False), ("can you say bye to mom", False), ("the program went offline", False),
    ("/remind I have to go to the bank", False),
])
def test_departure(text, expected):
    assert ypb.check_is_departure_message(text) is expected


@pytest.mark.parametrize("text,expected", [
    ("I'm back", True), ("back", True), ("I came back from lunch", True), ("aku udah balik", True), ("back now", True),
    ("my API call returned 500, why?", False), ("I returned the book", False), ("the function returned None", False),
])
def test_return(text, expected):
    assert ypb.check_is_return_message(text) is expected


@pytest.mark.parametrize("text,expected", [
    ("I'm trying to focus", True), ("I need to focus for 15 minutes", True), ("I'm locked in", True), ("/focus 20", True),
    ("focus mode", True), ("aku mau fokus", True),
    ("help me stop focus assist muting my notifications", False), ("Turn on Windows focus mode for me", False),
    ("I'm locked in my account", False), ("you need to focus", False), ("how do I focus better?", False),
])
def test_focus(text, expected):
    assert ypb.check_is_focus_message(text)[0] is expected


def test_focus_custom_duration():
    assert ypb.check_is_focus_message("I need to focus for 15 minutes") == (True, 900.0)


@pytest.mark.parametrize("text,expected", [
    ("done focusing", True), ("stop focus", True), ("/unfocus", True),
    ("help me stop focus assist muting my notifications", False), ("how do I stop focus mode?", False),
])
def test_unfocus(text, expected):
    assert ypb.check_is_unfocus_message(text) is expected


@pytest.mark.parametrize("text,day_first,expected", [
    ("05/12/2026", True, "2026-12-05"), ("05/12/2026", False, "2026-05-12"),
    ("25/12/2026", None, "2026-12-25"), ("12/25/2026", None, "2026-12-25"),
    ("5 desember 2026", None, "2026-12-05"), ("2026-12-05", None, "2026-12-05"),
    ("jan 1 2025", None, "2025-01-01"),   # explicit past year is kept, not rolled into next year
    ("31/02/2026", None, None),
])
def test_target_date(text, day_first, expected):
    assert ypb.parse_target_date(text, day_first=day_first) == expected


def test_target_date_relative_indonesian():
    import datetime
    today = datetime.date.today()
    assert ypb.parse_target_date("besok") == (today + datetime.timedelta(days=1)).isoformat()
    assert ypb.parse_target_date("lusa") == (today + datetime.timedelta(days=2)).isoformat()
    assert ypb.parse_target_date("minggu depan") == (today + datetime.timedelta(days=7)).isoformat()


def test_memory_manager_reads_dates_day_first(mem):
    mem.day_first_dates = True
    assert ypb.parse_target_date("05/12/2026", day_first=mem.day_first_dates) == "2026-12-05"


# =====================================================================================
# 6C: alarms & timers ship OFF until they can ring (H15)
# =====================================================================================

def test_alarms_feature_is_off_and_prompt_is_honest():
    assert ypb.ALARMS_ENABLED is False
    prompt = ypb.PINK_SYSTEM_INSTRUCTION
    assert "ACTIVE ALARM & COUNTDOWN TIMER system" not in prompt
    assert "TIMERS & ALARMS ARE UNDER CONSTRUCTION" in prompt
    assert "[set_alarm: 06:00 PM, dinner]" not in prompt


def test_alarm_context_never_reaches_prompts(mem):
    mem.add_alarm("08:00", "standup")
    assert mem.get_alarms_prompt() == ""


def test_nl_alarm_probe():
    assert ypb.nl_alarm_probe("set an alarm for 7:30 am standup")
    assert not ypb.nl_alarm_probe("I was alarmed by this")


# =====================================================================================
# Qt: dialogue queue (H19), chat timeout (H20), fingerprint (M16)
# =====================================================================================

@pytest.fixture
def overlay(qapp):
    ov = ypb.DialogueOverlay("Arial", ypb.DIALOGUE_BOX_PATH)
    yield ov
    ov.dismiss(clear_queue=True)
    ov.close()


def test_placeholder_step_advances_to_queued_line(overlay, qapp):
    """Summoning from hide-peek says '* ...' then '* ..?': the filtered placeholder must not stall the queue."""
    overlay.say("* ...", 100, 100, queue=["* ..?"])
    for _ in range(5):
        qapp.processEvents()
    assert overlay.is_active()
    assert overlay._full_text == "* ..?"


def test_placeholder_without_queue_stays_silent(overlay, qapp):
    """Empty-queue placeholders stay hidden (keeps the 4f1229a shop-loop fix)."""
    dismissed = []
    overlay.dismissed.connect(lambda: dismissed.append(True))
    overlay.say("* ...", 100, 100)
    for _ in range(5):
        qapp.processEvents()
    assert not overlay.is_active() and dismissed == []


def test_tag_only_lines_never_become_empty_steps():
    steps = ypb.split_dual_dialogue("[emotion: kesal]\n* Hmph! [anim: angry]")
    assert [s.text for s in steps] == ["* Hmph!"]


def test_chat_timeout_never_armed_while_hidden(qapp):
    chat = ypb.ChatInputOverlay("Arial", ypb.DIALOGUE_BOX_PATH)
    try:
        chat.open_at(200, 200)
        assert chat._timeout_timer.isActive()
        chat._text_edit.setPlainText("hi")
        chat._on_submit()                     # clear_attachment() runs before hide -> used to re-arm the timer
        assert not chat.isVisible()
        assert not chat._timeout_timer.isActive()
        chat.clear_attachment()               # any later text change while hidden must not arm it either
        chat.reset_timeout()
        assert not chat._timeout_timer.isActive()
    finally:
        chat.close()


def _img(qapp, bottom_value: int, size: int = 320):
    from PyQt5.QtGui import QColor, QImage

    img = QImage(size, size, QImage.Format_RGB32)
    img.fill(QColor(30, 30, 30))
    for y in range(size // 2, size):
        for x in range(0, size, 4):
            img.setPixelColor(x, y, QColor(bottom_value, bottom_value, bottom_value))
    return img


def test_fingerprint_sees_the_whole_screen(qapp):
    a = ypb.compute_screen_fingerprint(_img(qapp, 30))
    b = ypb.compute_screen_fingerprint(_img(qapp, 250))   # only the BOTTOM half differs
    assert len(a) == ypb.FINGERPRINT_SIZE ** 2
    assert ypb.compute_fingerprint_diff(a, a) == 0.0
    assert ypb.compute_fingerprint_diff(a, b) > 0.05     # old code sampled only the top 25% -> 0.0


# =====================================================================================
# 6F: run-at-startup reflects what logon will actually launch (L6)
# =====================================================================================

def test_startup_enabled_only_when_entry_launches_this_copy(monkeypatch):
    cmd = ypb.get_startup_command()
    values = {}
    monkeypatch.setattr(ypb, "_read_startup_value", lambda name: values.get(name, ""))
    assert ypb.is_run_at_startup_enabled() is False
    values[ypb.STARTUP_APP_NAME] = '"C:\\Program Files\\Pink\\Yellows-Pixel-Buddies.exe"'  # installed app's entry
    assert ypb.is_run_at_startup_enabled() is False      # from source, that is NOT us
    values[ypb.STARTUP_DEV_APP_NAME] = cmd
    assert ypb.is_run_at_startup_enabled() is True


# =====================================================================================
# 6D: shop (H17, H18, M17, L11, L12)
# =====================================================================================

@pytest.fixture
def shop(qapp, mem):
    import shop_window

    w = shop_window.DeltaruneShopWindow(pet_ref=None, memory=mem, font_family="Arial")
    yield w
    w.hide()
    w.close()


def test_shop_hit_test_is_pure(shop, monkeypatch):
    import shop_window
    from PyQt5.QtCore import QPoint

    scrolled = []
    monkeypatch.setattr(shop, "_scroll_up", lambda: scrolled.append("up"))
    monkeypatch.setattr(shop, "_scroll_down", lambda: scrolled.append("down"))
    shop.state = shop_window.ShopState.TALK_MENU
    for _ in range(20):                                   # hovering over the arrows = many mouse-move hit-tests
        assert shop._get_item_at_canvas_pos(QPoint(380, 280)) is None
        assert shop._get_item_at_canvas_pos(QPoint(380, 390)) is None
    assert scrolled == []
    assert shop._hit_scroll_arrow(QPoint(380, 280)) == -1
    assert shop._hit_scroll_arrow(QPoint(380, 390)) == 1
    assert shop._hit_scroll_arrow(QPoint(100, 300)) == 0


def test_shop_scroll_sound_only_when_list_moves(shop, monkeypatch):
    import shop_window

    played = []
    monkeypatch.setattr(shop_window, "play_sound", lambda name, *a, **k: played.append(name))
    shop.state = shop_window.ShopState.TALK_MENU
    shop._talk_scroll_offset = 0
    shop._scroll_up()                                     # already at the top
    assert played == []


def test_shop_ignores_replies_it_did_not_ask_for(shop):
    assert shop.deliver_ai_reply(["* a screen peek comment"]) is False
    shop._awaiting_ai_reply = True
    assert shop.deliver_ai_reply(["* Enjoy. Enjoy! ENJOY!!"]) is True
    assert shop.deliver_ai_reply(["* another unrelated reply"]) is False


def test_shop_back_from_toggles_keeps_position(shop):
    import shop_window

    shop.state = shop_window.ShopState.TOGGLES_MENU
    shop._cancel_or_back()
    assert shop.state == shop_window.ShopState.SETTINGS_MENU and shop._selected_index == 1
    shop.state = shop_window.ShopState.SCALES_MENU
    shop._cancel_or_back()
    assert shop._selected_index == 0


def test_shop_evidence_reads_real_sessions_dir(shop, mem):
    mem.sessions_dir.mkdir(parents=True, exist_ok=True)
    (mem.sessions_dir / "session_20261123_120000.json").write_text(json.dumps({"messages": [
        {"timestamp": "2026-11-23T12:00:00", "user": "I finished writing my essay", "pink": "* Good!"}]}), encoding="utf-8")
    found, _strong, _kw = shop._scan_task_evidence("write essay")
    assert found


def test_shop_persona_hint_is_not_the_users_message():
    import shop_window
    assert "SHOPKEEPER MODE" in shop_window.SHOPKEEPER_PERSONA_HINT


# =====================================================================================
# 6E: voice & sound (M18, L9, M23)
# =====================================================================================

def _fake_sd(devices, hostapis, default_in):
    return types.SimpleNamespace(
        query_devices=lambda *a, **k: devices if not k else devices[default_in],
        query_hostapis=lambda: hostapis,
        default=types.SimpleNamespace(device=(default_in, 0)),
    )


def test_mic_prefers_windows_default_input(monkeypatch):
    import voice_service

    hostapis = [{"name": "MME"}, {"name": "Windows WASAPI"}]
    devices = [
        {"name": "Microphone Array (Realtek(R) Au", "hostapi": 0, "max_input_channels": 2, "default_samplerate": 44100},
        {"name": "Headset (WH-1000XM4 Hands-Free", "hostapi": 0, "max_input_channels": 1, "default_samplerate": 16000},
        {"name": "Microphone Array (Realtek(R) Audio)", "hostapi": 1, "max_input_channels": 2, "default_samplerate": 48000},
        {"name": "Headset (WH-1000XM4 Hands-Free AG Audio)", "hostapi": 1, "max_input_channels": 1, "default_samplerate": 16000},
    ]
    monkeypatch.setattr(voice_service, "HAS_SOUNDDEVICE", True)
    monkeypatch.setattr(voice_service, "sd", _fake_sd(devices, hostapis, default_in=1))
    idx, sr, ch = voice_service.find_best_input_device()
    assert idx == 3 and sr == 16000 and ch == 1               # WASAPI twin of the default headset, not the laptop array


def test_near_silence_is_not_transcribed(qapp, monkeypatch):
    import voice_service

    monkeypatch.setattr(voice_service, "HAS_WHISPER", True)
    monkeypatch.setattr(voice_service, "whisper", types.SimpleNamespace(load_model=lambda *a: pytest.fail("must not load")),
                        raising=False)
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal(voice_service.TARGET_SAMPLE_RATE) * 0.0003).astype(np.float32)   # muted-mic hiss
    th = voice_service.WhisperTranscribeThread(audio_data=noise, model=None, api_key="")
    out = []
    th.sig_transcribed.connect(out.append)
    th.run()                                                    # synchronous: no thread started
    assert out == [""]


def test_whisper_model_loaded_on_demand_is_cached(qapp):
    import voice_service

    vm = voice_service.VoiceManager(model_name="base", api_key="")
    sentinel = object()
    vm._on_model_loaded(sentinel)
    assert vm._whisper_model is sentinel


def test_failed_preload_is_retried_with_backoff(qapp, monkeypatch):
    import voice_service

    scheduled = []
    monkeypatch.setattr(voice_service.QTimer, "singleShot", staticmethod(lambda ms, fn: scheduled.append(ms)))
    vm = voice_service.VoiceManager(model_name="base", api_key="")
    for _ in range(voice_service.PRELOAD_MAX_RETRIES + 2):
        vm._on_model_failed("offline")
    assert scheduled == [30000, 60000, 120000]


def test_sound_init_is_not_retried_on_every_blip(monkeypatch):
    import sound_manager

    sm = sound_manager.SoundManager(muted=False)
    attempts = []
    monkeypatch.setattr(sm, "_init_engine", lambda: attempts.append(1) or False)
    monkeypatch.setattr(sm, "_play_qt_fallback", lambda *a, **k: False)
    sm._mixer_initialized = False
    sm._last_init_attempt = time.perf_counter()
    for name in ("text_blip", "menu_move", "text_blip"):
        sm._last_played_time.clear()
        sm.play(name)
    assert attempts == []                                       # within the retry interval: straight to Qt fallback


# =====================================================================================
# The pet: question loader (M12), unavailable alarms (H15), sequence area (L7)
# =====================================================================================

@pytest.fixture(scope="module")
def pet(qapp):
    p = ypb.YellowsPixelBuddies(ypb.SpriteBank(ypb.SPRITES_DIR, 1.0))
    p._memory.get_api_key = lambda: "test-key"
    yield p
    shutdown_pet(p)


@pytest.mark.slow
def test_question_while_locked_does_not_freeze_pink(pet, monkeypatch):
    monkeypatch.setattr(ypb, "is_workstation_locked", lambda: True)
    pet._phase = ypb.Phase.PAUSE
    pet._brain_timer.stop()
    pet._dialogue_overlay.say("* ...?", 100, 100, skippable=False, auto_dismiss=False)
    pet._on_ai_question_ready(ypb.QuestionItem("* Q?", [("A", "", None), ("B", "", None)]), "memory")
    assert not (pet._dialogue_overlay.is_active() and pet._dialogue_overlay._full_text == "* ...?")
    assert pet._brain_timer.isActive()


@pytest.mark.slow
def test_timer_command_says_unavailable(pet, monkeypatch):
    said = []
    monkeypatch.setattr(pet, "_say", lambda text, *a, **k: said.append(text))
    pet._on_chat_submitted("/timer 10m tea")
    pet._on_chat_submitted("set an alarm for 7:30 am standup")
    assert len(said) == 2 and all("under construction" in s for s in said)
    assert pet._memory.get_active_alarms() == []


@pytest.mark.slow
def test_sequence_area_uses_captured_screen(pet):
    from PyQt5.QtCore import QRect

    pet._sequence_area_rect = QRect(1920, 0, 1920, 1040)        # e.g. a monitor to the right of primary
    assert pet._sequence_area() == QRect(1920, 0, 1920, 1040)
    pet._capture_sequence_area()
    assert pet._sequence_area() == pet._current_screen().availableGeometry()
