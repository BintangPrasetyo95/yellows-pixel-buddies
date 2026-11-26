"""Record a real Pink Takeover run as a golden replay case for tests/test_takeover_replay.py (plan 5.2).

!!! THIS DRIVES YOUR REAL MOUSE AND KEYBOARD. Run it only by hand, with nothing important focused. !!!
Never run it in CI or from a test. Press Esc to abort at any time.

    set GEMINI_API_KEY=...            (read from the environment only; .env is never touched)
    python tools/record_takeover_case.py <case_name> "<goal>" [--app WhatsApp]

It writes tests/fixtures/takeover/<case_name>/: one JPEG per observed step plus case.json with the model's
decisions, the foreground window at each decision, your confirmation answers, every input call the executor made,
and the outcome. Review case.json before committing it: it contains window titles and the typed text.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import action_planner  # noqa: E402
import os_interop  # noqa: E402
import privacy  # noqa: E402


def _win(w):
    if w is None:
        return None
    return {"hwnd": w.hwnd, "title": w.title, "process_id": w.process_id, "process_name": w.process_name}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case")
    ap.add_argument("goal")
    ap.add_argument("--app", default="Desktop")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")   # show why a run stops
    privacy.install_log_redaction()   # the API key never reaches the terminal (REVIEW M9)

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("Set GEMINI_API_KEY in the environment first.")
        return 2
    if input(f"This will control your REAL mouse and keyboard to: {args.goal!r}. Type YES to continue: ") != "YES":
        return 1

    out = ROOT / "tests" / "fixtures" / "takeover" / args.case
    steps: list[dict] = []
    pending_obs_fg: list = [None]

    def on_decision(step_idx: int, decision: dict, screenshot_b64: str) -> None:
        out.mkdir(parents=True, exist_ok=True)
        shot = f"step{step_idx + 1}.jpg"
        (out / shot).write_bytes(base64.b64decode(screenshot_b64))
        obs_fg = pending_obs_fg[0]
        dec_fg = _win(os_interop.get_foreground_window())
        entry = {"decision": decision, "screenshot": shot,
                 "foreground": obs_fg or dec_fg, "confirm": None}
        if obs_fg and dec_fg and obs_fg.get("hwnd") != dec_fg.get("hwnd"):
            entry["foreground_during_decision"] = dec_fg
        steps.append(entry)

    def on_confirm(step, title, proc) -> bool:
        ok = input(f"\nPink wants to {step.action_type} {step.text or step.target!r} in {proc or title}. Approve? [y/N] ")
        approved = ok.strip().lower() == "y"
        if steps:
            steps[-1]["confirm"] = approved
        return approved

    recorder = os_interop.RecordingInput(inner=os_interop.RealInput())
    executor = action_planner.DesktopActionExecutor(api_key=api_key, input_backend=recorder, on_decision=on_decision)
    orig_observe = executor.observer.observe
    orig_stale = executor._stale_step_reason

    def wrapped_observe(target_hwnd):
        obs = orig_observe(target_hwnd)
        pending_obs_fg[0] = _win(os_interop.get_foreground_window())
        return obs

    def wrapped_stale(step, observed_at, observed_hwnd, observed_img, offset):
        reason = orig_stale(step, observed_at, observed_hwnd, observed_img, offset)
        if reason and steps and "around the target changed" in reason:
            steps[-1]["target_shifted"] = True
        return reason

    executor.observer.observe = wrapped_observe
    executor._stale_step_reason = wrapped_stale
    plan = action_planner.create_desktop_plan(intent=args.goal, target_app=args.app, user_request=args.goal)
    windows = [_win(w) for w in os_interop.list_windows(visible_only=True, exclude_cloaked=True, exclude_self=True)]
    start_fg = _win(os_interop.get_foreground_window())
    success = executor.execute_plan(plan, on_confirm_action=on_confirm)

    if not steps and not recorder.calls:
        # Nothing was decided or sent: a case.json now would be an empty fixture that "passes" without testing anything.
        print(f"\nNOT RECORDED: the takeover ended before any decision ({plan.outcome_state}): {plan.summary_message}")
        print("See the log lines above for the cause (API error, no screenshot, target app not found).")
        return 3

    case = {
        "goal": args.goal, "target_app": args.app, "windows": windows, "foreground": start_fg, "steps": steps,
        "expected": {"calls": recorder.calls, "outcome_state": plan.outcome_state, "success": success},
        "summary": plan.summary_message,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "case.json").write_text(json.dumps(case, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRecorded {len(steps)} steps -> {out / 'case.json'} (outcome: {plan.outcome_state}: {plan.summary_message})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
