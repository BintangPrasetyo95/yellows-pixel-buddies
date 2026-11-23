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
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import action_planner  # noqa: E402
import os_interop  # noqa: E402


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

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("Set GEMINI_API_KEY in the environment first.")
        return 2
    if input(f"This will control your REAL mouse and keyboard to: {args.goal!r}. Type YES to continue: ") != "YES":
        return 1

    out = ROOT / "tests" / "fixtures" / "takeover" / args.case
    out.mkdir(parents=True, exist_ok=True)
    steps: list[dict] = []

    def on_decision(step_idx: int, decision: dict, screenshot_b64: str) -> None:
        shot = f"step{step_idx + 1}.jpg"
        (out / shot).write_bytes(base64.b64decode(screenshot_b64))
        steps.append({"decision": decision, "screenshot": shot,
                      "foreground": _win(os_interop.get_foreground_window()), "confirm": None})

    def on_confirm(step, title, proc) -> bool:
        ok = input(f"\nPink wants to {step.action_type} {step.text or step.target!r} in {proc or title}. Approve? [y/N] ")
        approved = ok.strip().lower() == "y"
        if steps:
            steps[-1]["confirm"] = approved
        return approved

    recorder = os_interop.RecordingInput(inner=os_interop.RealInput())
    executor = action_planner.DesktopActionExecutor(api_key=api_key, input_backend=recorder, on_decision=on_decision)
    plan = action_planner.create_desktop_plan(intent=args.goal, target_app=args.app, user_request=args.goal)
    windows = [_win(w) for w in os_interop.list_windows(visible_only=True, exclude_cloaked=True, exclude_self=True)]
    start_fg = _win(os_interop.get_foreground_window())
    success = executor.execute_plan(plan, on_confirm_action=on_confirm)

    case = {
        "goal": args.goal, "target_app": args.app, "windows": windows, "foreground": start_fg, "steps": steps,
        "expected": {"calls": recorder.calls, "outcome_state": plan.outcome_state, "success": success},
    }
    (out / "case.json").write_text(json.dumps(case, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRecorded {len(steps)} steps -> {out / 'case.json'} (outcome: {plan.outcome_state})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
