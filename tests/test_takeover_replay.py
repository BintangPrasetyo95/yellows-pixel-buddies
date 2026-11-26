"""Golden replays of Pink Takeover cases (plan 5.2 / REVIEW T3).

Each tests/fixtures/takeover/<case>/case.json holds the model's decisions for a takeover, the windows involved,
the user's confirmation answers, and the EXACT input calls the executor must make. Decisions go through the real
parser (step_from_decision) and the real executor; input goes to os_interop.RecordingInput, window queries to the
fake_os_interop recorder. Nothing reaches the real mouse, keyboard, screen or Gemini.

Cases recorded from real runs come from tools/record_takeover_case.py; the hand-written ones pin the review fixes:
C2 (sensitive step gated), C3 (Cancel ends the plan), H2 (type into the post-click window), H3 (Pink's own Esc is not
a panic), H5 (a closed app isn't "opened"), H6 (focus changed while deciding -> skip), H8 (no blind Ctrl+A).

Optional per-step fields: "foreground" (window at the observation), "foreground_after_click",
"foreground_during_decision" (the user alt-tabs while the model thinks), "confirm" (the user's answer).
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import pytest
from PIL import Image, ImageOps

import action_planner
import os_interop

CASES_DIR = Path(__file__).parent / "fixtures" / "takeover"
CASES = sorted(p.name for p in CASES_DIR.iterdir() if (p / "case.json").is_file()) if CASES_DIR.is_dir() else []


def _window(d):
    if d is None:
        return None
    return os_interop.WindowInfo(hwnd=d["hwnd"], title=d["title"], process_id=d.get("process_id", 4000 + d["hwnd"]),
                                 process_name=d["process_name"], bounds=(0, 0, 1920, 1080),
                                 is_minimized=False, is_cloaked=False)


def _image(case_dir: Path, step: dict) -> Image.Image:
    name = step.get("screenshot")
    if name and (case_dir / name).is_file():
        return Image.open(case_dir / name).convert("RGB")
    return Image.new("RGB", (1920, 1080), "white")


def replay(case_dir: Path, fake, monkeypatch):
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    steps = case["steps"]
    fake.windows = [_window(w) for w in case.get("windows", [])]
    fake.foreground = _window(case.get("foreground"))
    rec = os_interop.RecordingInput(foreground=lambda: fake.foreground)
    cursor = {"obs": -1, "dec": -1}

    def fake_capture(*_a, **_k):
        cursor["obs"] += 1
        step = steps[min(cursor["obs"], len(steps) - 1)]
        if step.get("foreground"):
            fake.foreground = _window(step["foreground"])
        img = _image(case_dir, step)
        action_planner._LAST_RAW_SCREENSHOT = img
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return base64.b64encode(buf.getvalue()).decode(), img.width, img.height, (0, 0)

    def fake_gemini(*_a, **_k):
        cursor["dec"] += 1
        if cursor["dec"] >= len(steps):
            return {"self_check": "initial", "action": "fail", "target": "replay exhausted"}
        step = steps[cursor["dec"]]
        if step.get("foreground_during_decision"):
            fake.foreground = _window(step["foreground_during_decision"])
        if step.get("target_shifted"):
            obs_img = action_planner._LAST_RAW_SCREENSHOT or Image.new("RGB", (1920, 1200), "white")
            shifted = ImageOps.invert(obs_img.convert("RGB"))
            fake.screen_patches.extend([shifted, shifted.copy()])
        return step["decision"]

    def on_call(name, args, kwargs):
        step = steps[cursor["dec"]] if 0 <= cursor["dec"] < len(steps) else {}
        if name == "click" and step.get("foreground_after_click"):
            fake.foreground = _window(step["foreground_after_click"])

    def on_confirm(step_obj, title, proc):
        step = steps[cursor["dec"]] if 0 <= cursor["dec"] < len(steps) else {}
        return bool(step.get("confirm"))

    rec.on_call = on_call
    monkeypatch.setattr(action_planner, "capture_screen_region", fake_capture)
    monkeypatch.setattr(action_planner, "_call_gemini_json", fake_gemini)
    monkeypatch.setattr(action_planner, "ground_ui_element", lambda *a, **k: None)

    plan = action_planner.create_desktop_plan(intent=case["goal"], target_app=case.get("target_app", "Desktop"),
                                              user_request=case["goal"])
    executor = action_planner.DesktopActionExecutor(api_key="replay", input_backend=rec)
    success = executor.execute_plan(plan, on_confirm_action=on_confirm)
    return case, rec.calls, plan, success


@pytest.mark.parametrize("case_name", CASES)
def test_replay(case_name, fake_os_interop, no_sleep, monkeypatch):
    case, calls, plan, success = replay(CASES_DIR / case_name, fake_os_interop, monkeypatch)
    expected = case["expected"]
    assert json.loads(json.dumps(calls)) == expected["calls"]
    assert plan.outcome_state == expected["outcome_state"]
    assert success is expected["success"]
    # The executor must never reach the real input functions: only RecordingInput saw input.
    assert not [c for c in fake_os_interop.names() if c in ("click_mouse", "type_text", "press_key", "hotkey",
                                                             "smooth_move_mouse", "scroll_mouse")]


def test_replay_cases_exist():
    assert {"c2_sensitive_send_is_gated", "c3_cancel_ends_plan", "h2_types_into_post_click_window",
            "h3_own_esc_is_not_a_panic", "h5_closed_app_is_not_opened", "h6_focus_changed_while_deciding",
            "h8_no_blind_select_all"} <= set(CASES)
