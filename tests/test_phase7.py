"""Phase 7 (performance) regression tests. See temp/IMPLEMENTATION_PLAN.md §10.

M19 Gemini deadline / 429 back-off / context budget · M20 capture pipeline · M21 session search, history cap,
git info, worker cleanup, shop snapshot · M22 web image drops · L10 context-menu leak.
No test here talks to Gemini, downloads anything, or reads the real screen.
"""
from __future__ import annotations

import base64
import json
import threading
import time
import types

import pytest
import requests
from PyQt5.QtCore import QEvent, QMimeData, QUrl
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtWidgets import QApplication, QMenu

import yellows_pixel_buddies as ypb


class _Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _http_error(status: int) -> requests.exceptions.HTTPError:
    resp = requests.models.Response()
    resp.status_code = status
    resp._content = b"{}"
    return requests.exceptions.HTTPError(response=resp)


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(ypb, "_gemini_backoff_until", 0.0)


# =====================================================================================
# M19 - one deadline, no model hopping on 429, smaller ambient context
# =====================================================================================

def test_one_deadline_across_all_fallback_models():
    clock = _Clock()
    tried = []

    def attempt(model):
        tried.append(model)
        clock.t += 25.0                      # each model hangs until its read timeout
        raise requests.exceptions.Timeout()

    deadline = clock() + ypb.GEMINI_TOTAL_DEADLINE_S
    result, err = ypb.run_model_fallback(["a", "b", "c", "d"], attempt, deadline, clock=clock)
    assert result is None and "timed out" in err.lower()
    assert tried == ["a", "b"]               # not 4 x 35 s any more


def test_rate_limit_stops_and_backs_off():
    tried = []

    def attempt(model):
        tried.append(model)
        raise _http_error(429)

    result, err = ypb.run_model_fallback(["a", "b", "c"], attempt, time.monotonic() + 40)
    assert tried == ["a"] and "429" in err
    assert ypb.gemini_backoff_remaining() > 0


def test_missing_model_falls_back_but_auth_error_stops():
    def attempt(model):
        if model == "a":
            raise _http_error(404)
        return ("ok", model)

    assert ypb.run_model_fallback(["a", "b"], attempt, time.monotonic() + 40) == (("ok", "b"), "")
    tried = []

    def auth(model):
        tried.append(model)
        raise _http_error(401)

    assert ypb.run_model_fallback(["a", "b"], auth, time.monotonic() + 40)[0] is None and tried == ["a"]


def test_request_timeout_respects_deadline():
    assert ypb.request_timeout(None) == (ypb.GEMINI_CONNECT_TIMEOUT_S, float(ypb.GEMINI_TIMEOUT_S))
    assert ypb.request_timeout(110.0, now=100.0)[1] == 10.0
    assert ypb.request_timeout(100.5, now=100.0)[1] == 1.0


def _history(n):
    return [{"user": f"question {i}", "pink": f"* answer {i}", "timestamp": "2026-11-23T10:00:00"} for i in range(n)]


def _capture_posts(monkeypatch):
    sent = []

    def post(url, headers=None, json=None, timeout=None):
        sent.append({"json": json, "timeout": timeout})
        raise requests.exceptions.ConnectionError("offline")

    monkeypatch.setattr(ypb.requests, "post", post)
    return sent


def test_ambient_calls_carry_few_history_turns(qapp, monkeypatch):
    sent = _capture_posts(monkeypatch)
    th = ypb.GeminiWorkerThread(api_key="k", user_prompt="peek", system_instruction="sys", history=_history(30),
                                is_auto_peek=True)
    th.run()
    assert sent and len(sent[0]["json"]["contents"]) <= ypb.AMBIENT_HISTORY_TURNS + 1
    assert isinstance(sent[0]["timeout"], tuple)          # bounded by the shared deadline

    sent.clear()
    chat = ypb.GeminiWorkerThread(api_key="k", user_prompt="hi", system_instruction="sys", history=_history(30))
    chat.run()
    assert len(sent[0]["json"]["contents"]) == ypb.CHAT_HISTORY_TURNS + 1


def test_unprompted_call_skipped_during_backoff(qapp, monkeypatch):
    sent = _capture_posts(monkeypatch)
    ypb.note_gemini_rate_limited()
    th = ypb.GeminiWorkerThread(api_key="k", user_prompt="peek", system_instruction="s", history=[], is_auto_peek=True)
    errors = []
    th.error_occurred.connect(errors.append)
    th.run()
    assert sent == [] and errors and "rate limited" in errors[0].lower()


# =====================================================================================
# M20 - fingerprint first, encode on the worker, no hide/show
# =====================================================================================

def _solid(w, h, color="white"):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(color))
    return img


def test_fingerprint_on_4k_sees_lower_screen_changes(qapp):
    a = _solid(3840, 2160)
    b = _solid(3840, 2160)
    from PyQt5.QtGui import QPainter
    p = QPainter(b)
    p.fillRect(0, 1700, 3840, 460, QColor("black"))   # a change in the bottom fifth only
    p.end()
    fa, fb = ypb.compute_screen_fingerprint(a), ypb.compute_screen_fingerprint(b)
    assert len(fa) == ypb.FINGERPRINT_SIZE ** 2
    assert ypb.compute_fingerprint_diff(fa, ypb.compute_screen_fingerprint(_solid(3840, 2160))) == 0.0
    assert ypb.compute_fingerprint_diff(fa, fb) > 0.1


def test_encode_screenshot_works_off_the_gui_thread(qapp):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("b64", ypb.encode_screenshot(_solid(2560, 1440, "red"))))
    t.start()
    t.join(10)
    raw = base64.b64decode(out["b64"])
    assert raw[:2] == b"\xff\xd8"                         # a JPEG
    assert QImage.fromData(raw).width() == 1280            # downscaled for the API


def test_worker_encodes_the_raw_capture_and_releases_it(qapp, monkeypatch):
    sent = _capture_posts(monkeypatch)
    th = ypb.GeminiWorkerThread(api_key="k", user_prompt="look", system_instruction="s", history=[],
                                screenshot_image=_solid(1920, 1080))
    th.run()
    parts = sent[0]["json"]["contents"][-1]["parts"]
    assert any("inlineData" in p for p in parts)
    assert th.screenshot_image is None and th.screenshot_b64 is None and th.system_instruction == ""


@pytest.fixture(scope="module")
def pet(qapp):
    from tests.conftest import shutdown_pet

    p = ypb.YellowsPixelBuddies(ypb.SpriteBank(ypb.SPRITES_DIR, 1.0))
    yield p
    shutdown_pet(p)


@pytest.mark.slow
def test_capture_excludes_pink_instead_of_hiding_her(pet, monkeypatch):
    calls = []
    monkeypatch.setattr(ypb.os_interop, "set_window_exclude_from_capture", lambda w, on=True: calls.append(on) or True)
    monkeypatch.setattr(ypb.os_interop, "dwm_flush", lambda: None)
    monkeypatch.setattr(ypb, "grab_screen", lambda screen=None: ("PIX", b"fp"))
    pet.show()
    hidden = []
    monkeypatch.setattr(pet, "hide", lambda: hidden.append(True))
    assert pet._grab_screen_without_pink() == ("PIX", b"fp")
    assert hidden == [] and calls and calls[0] is True and calls[-1] is False


@pytest.mark.slow
def test_capture_falls_back_to_hiding_without_exclusion(pet, monkeypatch):
    monkeypatch.setattr(ypb.os_interop, "set_window_exclude_from_capture", lambda w, on=True: False)
    monkeypatch.setattr(ypb, "grab_screen", lambda screen=None: ("PIX", b"fp"))
    pet.show()
    events = []
    monkeypatch.setattr(pet, "hide", lambda: events.append("hide"))
    monkeypatch.setattr(pet, "show", lambda: events.append("show"))
    pet._grab_screen_without_pink()
    assert events[:1] == ["hide"] and events[-1] == "show"


# =====================================================================================
# M21 - session search, history cap, git info, worker cleanup, shop snapshot
# =====================================================================================

@pytest.mark.parametrize("text,expected", [
    ("what did we talk about yesterday?", True),
    ("do you remember my cat's name", True),
    ("kemarin kita ngomongin apa?", True),
    ("open spotify", False),
    ("hi pink", False),
])
def test_session_search_only_for_past_questions(text, expected):
    assert ypb.wants_past_session_search(text) is expected


def test_session_search_reads_only_the_newest_files(mem):
    mem.sessions_dir.mkdir(parents=True, exist_ok=True)
    for day in range(1, 6):
        f = mem.sessions_dir / f"session_202611{day:02d}_100000.json"
        f.write_text(json.dumps({"messages": [{"user": f"pancake recipe day {day}", "pink": "* yum " + "x" * 120,
                                               "timestamp": f"2026-11-{day:02d}T10:00:00"}]}), encoding="utf-8")
    found = mem.search_past_sessions("pancake", max_files=2, max_results=10)
    assert "day 5" in found and "day 1" not in found


def test_worker_runs_extra_context_off_the_gui_thread(qapp, monkeypatch):
    sent = _capture_posts(monkeypatch)
    ran_on = []

    def suffix():
        ran_on.append(threading.current_thread().name)
        return "RELEVANT PAST MEMORIES: pancakes"

    th = ypb.GeminiWorkerThread(api_key="k", user_prompt="remember?", system_instruction="sys", history=[],
                                system_suffix_fn=suffix)
    t = threading.Thread(target=th.run, name="fake-worker")
    t.start()
    t.join(10)
    assert ran_on == ["fake-worker"]
    assert "pancakes" in sent[0]["json"]["systemInstruction"]["parts"][0]["text"]


def test_history_is_capped(mem):
    for i in range(ypb.MAX_HISTORY_TURNS_IN_MEMORY + 50):
        mem._append_history({"user": str(i)})
    assert len(mem.history) == ypb.MAX_HISTORY_TURNS_IN_MEMORY
    assert mem.history[-1]["user"] == str(ypb.MAX_HISTORY_TURNS_IN_MEMORY + 49)


def test_git_info_never_blocks(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(ypb, "_exe_dir", tmp_path)
    started = threading.Event()

    def slow_read():
        started.set()
        time.sleep(0.5)
        return {"branch": "main", "commit": "abc", "is_dirty": False, "dirty_count": 0}

    monkeypatch.setattr(ypb.CodebaseStateProvider, "_read_git_info", staticmethod(slow_read))
    prov = ypb.CodebaseStateProvider()
    t0 = time.perf_counter()
    assert prov.get_git_info() is None                     # no cache yet, and no waiting for git
    assert time.perf_counter() - t0 < 0.2
    assert started.wait(2)
    deadline = time.time() + 3
    while prov._git_cache is None and time.time() < deadline:
        time.sleep(0.05)
    assert prov.get_git_info()["branch"] == "main"


@pytest.mark.slow
def test_finished_worker_is_deleted_when_replaced(pet, qapp):
    old = ypb.GeminiWorkerThread(api_key="", user_prompt="", system_instruction="", history=[], parent=pet)
    pet._gemini_thread = old
    destroyed = []
    old.destroyed.connect(lambda *_: destroyed.append(True))
    pet._gemini_thread = None
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert destroyed == [True]


@pytest.fixture
def shop(qapp, mem):
    import shop_window

    w = shop_window.DeltaruneShopWindow(pet_ref=None, memory=mem, font_family="Arial")
    yield w
    w.hide()
    w.close()


def test_shop_reads_from_a_snapshot(shop, monkeypatch):
    import shop_window

    reads = []
    real = shop._memory.get_active_goals
    monkeypatch.setattr(shop._memory, "get_active_goals", lambda: reads.append(1) or real())
    shop.refresh_snapshot()
    for _ in range(5):
        shop._get_goals()
    assert len(reads) == 1
    shop.state = shop_window.ShopState.TASKS                # state change -> fresh data
    shop._get_goals()
    assert len(reads) == 2
    shop._add_goal("Write the thesis")                      # an edit -> fresh data
    assert "Write the thesis" in shop._get_goals()


def test_shop_paint_does_no_reads_once_snapshotted(shop, monkeypatch):
    import shop_window

    shop.state = shop_window.ShopState.TASKS
    shop.grab()                                             # first paint fills the snapshot

    def boom(*a, **k):
        raise AssertionError("I/O during paint")

    for name in ("get_active_goals", "get_active_reminders", "get_user_name", "get_reminders"):
        if hasattr(shop._memory, name):
            monkeypatch.setattr(shop._memory, name, boom)
    monkeypatch.setattr(shop_window.Path, "read_text", boom)
    shop.grab()
    shop.grab()


def test_snapshot_copies_are_independent(shop):
    goals = shop._get_goals()
    goals.append("mutated by a caller")
    assert "mutated by a caller" not in shop._get_goals()


# =====================================================================================
# M22 - web image drops
# =====================================================================================

class _Stream:
    def __init__(self, chunks, length=None):
        self._chunks, self.headers = chunks, ({"content-length": str(length)} if length else {})

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=65536):
        yield from self._chunks


def test_fetch_url_capped_limits(monkeypatch):
    monkeypatch.setattr(ypb.requests, "get", lambda *a, **k: _Stream([b"a" * 10, b"b" * 10]))
    assert ypb.fetch_url_capped("https://x.test/cat.png") == b"a" * 10 + b"b" * 10
    with pytest.raises(ValueError):
        ypb.fetch_url_capped("https://x.test/cat.png", max_bytes=15)
    monkeypatch.setattr(ypb.requests, "get", lambda *a, **k: _Stream([], length=99_000_000))
    with pytest.raises(ValueError):
        ypb.fetch_url_capped("https://x.test/huge.png")
    with pytest.raises(ValueError):
        ypb.fetch_url_capped("file:///C:/secret.png")

    clock = _Clock()

    def slow_chunks():
        for _ in range(5):
            clock.t += 5.0
            yield b"x"

    monkeypatch.setattr(ypb.requests, "get", lambda *a, **k: _Stream(slow_chunks()))
    with pytest.raises(TimeoutError):
        ypb.fetch_url_capped("https://x.test/slow.png", clock=clock)


def test_drop_never_downloads_on_the_gui_thread(qapp, monkeypatch):
    monkeypatch.setattr(ypb.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("blocking GET")))
    mime = QMimeData()
    mime.setUrls([QUrl("https://example.test/meme.jpg?size=large")])
    assert ypb.process_dropped_image_to_base64(mime) == (None, "")
    assert ypb.web_image_url_in_mime(mime) == "https://example.test/meme.jpg?size=large"


# =====================================================================================
# L10 - the right-click menu is deleted after use
# =====================================================================================

@pytest.mark.slow
def test_context_menu_is_not_leaked(pet, qapp, monkeypatch):
    monkeypatch.setattr(QMenu, "exec_", lambda self, *a, **k: None)
    monkeypatch.setattr(pet, "_save_live_settings", lambda *a, **k: None)   # keep the shared test data folder clean
    pet._phase = ypb.Phase.PAUSE
    before = len(pet.findChildren(QMenu))
    event = types.SimpleNamespace(globalPos=lambda: pet.pos())
    for _ in range(3):
        pet.contextMenuEvent(event)
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert len(pet.findChildren(QMenu)) == before
    pet.set_language("en", notify=False)                    # no dangling menu actions to touch
