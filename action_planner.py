"""action_planner.py - Screen Coordinate Grounding, Action Planning & Desktop Automation Engine.

Part of Yellow's Pixel Buddies / Pink desktop companion.
Provides:
- Visual UI grounding using Gemini Multimodal API (normalized 0-1000 box -> desktop pixels).
- Multi-step action planning (decomposing user commands like 'reply to Mom on WhatsApp').
- Heuristic fast-paths for common apps (WhatsApp, Spotify, Web Browsers).
- Safe step-by-step execution loop with panic abort guards and animation callbacks.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import requests
from PIL import Image, ImageGrab

try:
    from PyQt5.QtCore import QObject, QThread, pyqtSignal
    HAS_PYQT = True
except Exception:
    HAS_PYQT = False

import os_interop

log = logging.getLogger("yellows_pixel_buddies.action_planner")

# ---------------------------------------------------------------------------
# Gemini Models & Grounding Defaults
# ---------------------------------------------------------------------------

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
FALLBACK_GEMINI_MODELS = ["gemini-3.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
GEMINI_API_TIMEOUT_S = 30


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class GroundedBox:
    """Bounding box returned by visual grounding."""
    ymin: int  # 0..1000
    xmin: int  # 0..1000
    ymax: int  # 0..1000
    xmax: int  # 0..1000
    label: str
    confidence: float
    pixel_x: int  # Desktop X coordinate (center of box)
    pixel_y: int  # Desktop Y coordinate (center of box)
    pixel_width: int
    pixel_height: int

    def to_dict(self) -> dict:
        return {
            "box_2d": [self.ymin, self.xmin, self.ymax, self.xmax],
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "pixel_center": [self.pixel_x, self.pixel_y],
            "pixel_size": [self.pixel_width, self.pixel_height],
        }


@dataclass
class ActionStep:
    """A single discrete action in a desktop automation plan."""
    action_type: str  # "focus_window", "click", "type_text", "press_key", "hotkey", "wait"
    target: str = ""  # Description of target UI element or app name
    text: Optional[str] = None  # Text to type if action_type == "type_text"
    key: Optional[str] = None  # Key to press if action_type == "press_key"
    keys: Optional[List[str]] = None  # Combination for "hotkey"
    coordinates: Optional[Tuple[int, int]] = None  # Pre-computed or grounded pixel (x, y)
    grounded_box: Optional[GroundedBox] = None
    wait_s: float = 0.1
    status: str = "pending"  # "pending", "running", "completed", "failed", "aborted"
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "target": self.target,
            "text": self.text,
            "key": self.key,
            "keys": self.keys,
            "coordinates": list(self.coordinates) if self.coordinates else None,
            "status": self.status,
            "error_message": self.error_message,
        }


@dataclass
class DesktopPlan:
    """A sequenced execution plan for completing a desktop automation task."""
    intent: str
    target_app: str
    steps: List[ActionStep] = field(default_factory=list)
    current_step_index: int = 0
    is_finished: bool = False
    success: bool = False
    summary_message: str = ""

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "target_app": self.target_app,
            "steps": [s.to_dict() for s in self.steps],
            "current_step_index": self.current_step_index,
            "is_finished": self.is_finished,
            "success": self.success,
            "summary_message": self.summary_message,
        }


# ---------------------------------------------------------------------------
# Screen Capture Utility
# ---------------------------------------------------------------------------

def capture_screen_region(
    bounds: Optional[Tuple[int, int, int, int]] = None,
    max_dimension: int = 1280,
    jpeg_quality: int = 80,
) -> Tuple[str, int, int, Tuple[int, int]]:
    """Capture full screen or specific window bounds.

    Returns:
        (base64_jpeg_str, captured_width, captured_height, (offset_x, offset_y))
    """
    with os_interop.ensure_input_desktop():
        if bounds and len(bounds) == 4 and bounds[2] > bounds[0] and bounds[3] > bounds[1]:
            # Crop to window bounds: (left, top, right, bottom)
            img = ImageGrab.grab(bbox=bounds)
            offset = (bounds[0], bounds[1])
        else:
            img = ImageGrab.grab()
            metrics = os_interop.get_screen_metrics()
            offset = (metrics.virtual_left, metrics.virtual_top)

    orig_w, orig_h = img.size

    # Downscale if exceeding max_dimension to keep API payload fast and responsive
    if max(orig_w, orig_h) > max_dimension:
        ratio = max_dimension / max(orig_w, orig_h)
        new_w = max(1, int(orig_w * ratio))
        new_h = max(1, int(orig_h * ratio))
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality)
    b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")

    return b64_str, orig_w, orig_h, offset


# ---------------------------------------------------------------------------
# Visual UI Grounding with Gemini
# ---------------------------------------------------------------------------

GROUNDING_SYSTEM_PROMPT = """You are a high-precision Computer Vision Grounding Agent for desktop UI automation.
Given a desktop screenshot and a target element description, your task is to pinpoint the exact 2D bounding box of the target UI element.

OUTPUT SPECIFICATION:
Respond ONLY with a valid JSON object in the following format:
```json
{
  "box_2d": [ymin, xmin, ymax, xmax],
  "label": "descriptive label of found element",
  "confidence": 0.95
}
```
Where:
- [ymin, xmin, ymax, xmax] are integers normalized between 0 and 1000.
  - (0, 0) is the top-left corner of the image.
  - (1000, 1000) is the bottom-right corner of the image.
- ymin is the top boundary, ymax is the bottom boundary.
- xmin is the left boundary, xmax is the right boundary.
- If the element is not found, return:
  {"box_2d": null, "label": "not_found", "confidence": 0.0}

DO NOT include any commentary, explanations, or text outside the JSON codeblock."""


def ground_ui_element(
    screenshot_b64: str,
    target_description: str,
    api_key: str,
    region_orig_size: Tuple[int, int],
    region_offset: Tuple[int, int] = (0, 0),
    model: str = DEFAULT_GEMINI_MODEL,
) -> Optional[GroundedBox]:
    """Query Gemini to locate a target UI element on screen and convert to desktop pixel coordinates."""
    if not api_key:
        log.warning("No Gemini API key provided for visual grounding.")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}

    prompt_text = (
        f'Locate the following UI element on the screen: "{target_description}".\n'
        f"Return its bounding box [ymin, xmin, ymax, xmax] normalized to 0-1000."
    )

    payload = {
        "systemInstruction": {
            "parts": [{"text": GROUNDING_SYSTEM_PROMPT}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt_text},
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": screenshot_b64,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 300,
        },
    }

    models_to_try = [model] + [m for m in FALLBACK_GEMINI_MODELS if m != model]
    raw_response_text = ""

    for attempt_model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{attempt_model}:generateContent?key={api_key}"
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=GEMINI_API_TIMEOUT_S)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    raw_response_text = "".join(p.get("text", "") for p in parts if "text" in p).strip()
                    if raw_response_text:
                        break
        except Exception as e:
            log.warning("Grounding model '%s' request failed: %s", attempt_model, e)
            continue

    if not raw_response_text:
        log.warning("No grounding response received from Gemini.")
        return None

    # Parse JSON from response
    parsed_json = _parse_grounding_json(raw_response_text)
    if not parsed_json or not parsed_json.get("box_2d"):
        log.info("Target '%s' was not detected in screenshot (response: %s)", target_description, raw_response_text[:80])
        return None

    box = parsed_json["box_2d"]
    if len(box) != 4:
        return None

    ymin, xmin, ymax, xmax = [int(v) for v in box]
    conf = float(parsed_json.get("confidence", 0.9))
    label = str(parsed_json.get("label", target_description))

    # Translate normalized (0..1000) coordinates to screen pixels
    orig_w, orig_h = region_orig_size
    off_x, off_y = region_offset

    pixel_xmin = off_x + int(round((xmin / 1000.0) * orig_w))
    pixel_xmax = off_x + int(round((xmax / 1000.0) * orig_w))
    pixel_ymin = off_y + int(round((ymin / 1000.0) * orig_h))
    pixel_ymax = off_y + int(round((ymax / 1000.0) * orig_h))

    center_x = (pixel_xmin + pixel_xmax) // 2
    center_y = (pixel_ymin + pixel_ymax) // 2
    w = max(1, pixel_xmax - pixel_xmin)
    h = max(1, pixel_ymax - pixel_ymin)

    return GroundedBox(
        ymin=ymin,
        xmin=xmin,
        ymax=ymax,
        xmax=xmax,
        label=label,
        confidence=conf,
        pixel_x=center_x,
        pixel_y=center_y,
        pixel_width=w,
        pixel_height=h,
    )


def _parse_grounding_json(text: str) -> Optional[dict]:
    """Extract and parse JSON from model output."""
    # Try finding markdown ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass

    # Try raw JSON block
    m2 = re.search(r"\{[^{}]*\"box_2d\"[^{}]*\}", text, re.DOTALL)
    if m2:
        try:
            return json.loads(m2.group(0))
        except Exception:
            pass

    # Regex fallback for [ymin, xmin, ymax, xmax]
    m_box = re.search(r"\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]", text)
    if m_box:
        return {
            "box_2d": [int(m_box.group(i)) for i in range(1, 5)],
            "label": "detected_element",
            "confidence": 0.8,
        }

    return None


# ---------------------------------------------------------------------------
# High-Level Action Plan Builder (Heuristics + LLM)
# ---------------------------------------------------------------------------

def create_desktop_plan(
    intent: str,
    api_key: Optional[str] = None,
) -> DesktopPlan:
    """Compile a user intent into an executable DesktopPlan.

    Uses high-speed heuristic templates for recognized apps (WhatsApp, Spotify, Web Search),
    or delegates to Gemini for dynamic multi-step planning.
    """
    clean_intent = intent.strip()

    # 1. Check for WhatsApp message reply heuristic
    wa_match = re.search(
        r"(?:reply|message|send|tell|text|answer)\s+(?:to\s+)?(.+?)(?:\s+on\s+whatsapp)?\s*(?:saying|with|:)\s*[\"']?([^\"']+)[\"']?",
        clean_intent,
        re.IGNORECASE,
    )
    if "whatsapp" in clean_intent.lower() or wa_match:
        contact = wa_match.group(1).strip() if wa_match else ""
        msg = wa_match.group(2).strip() if wa_match else clean_intent

        steps = [
            ActionStep(action_type="focus_window", target="WhatsApp", wait_s=0.3),
        ]
        if contact:
            steps.extend([
                # Search contact
                ActionStep(action_type="click", target=f"search bar or contact '{contact}' in chat list", wait_s=0.2),
                ActionStep(action_type="type_text", text=contact, wait_s=0.2),
                ActionStep(action_type="press_key", key="enter", wait_s=0.3),
            ])
        # Click message input bar, type, and press enter
        steps.extend([
            ActionStep(action_type="click", target="Type a message chat input box at bottom", wait_s=0.1),
            ActionStep(action_type="type_text", text=msg, wait_s=0.1),
            ActionStep(action_type="press_key", key="enter", wait_s=0.2),
        ])

        return DesktopPlan(
            intent=clean_intent,
            target_app="WhatsApp",
            steps=steps,
            summary_message=f"Sent message to {contact or 'chat'}: '{msg}'",
        )

    # 2. Check for Web Browser Search heuristic
    search_match = re.search(
        r"(?:search|google|lookup|find)\s+(?:for\s+)?[\"']?([^\"']+)[\"']?(?:\s+on\s+(?:google|chrome|browser))?",
        clean_intent,
        re.IGNORECASE,
    )
    if search_match and ("search" in clean_intent.lower() or "google" in clean_intent.lower()):
        query = search_match.group(1).strip()
        steps = [
            ActionStep(action_type="focus_window", target="Chrome", wait_s=0.2),
            # Ctrl+L focuses browser address / search bar
            ActionStep(action_type="hotkey", keys=["ctrl", "l"], wait_s=0.1),
            ActionStep(action_type="type_text", text=query, wait_s=0.1),
            ActionStep(action_type="press_key", key="enter", wait_s=0.3),
        ]
        return DesktopPlan(
            intent=clean_intent,
            target_app="Chrome",
            steps=steps,
            summary_message=f"Searched for '{query}' in browser.",
        )

    # 3. Fallback: Generic Single-Click or Text Input Step
    return DesktopPlan(
        intent=clean_intent,
        target_app="Active Window",
        steps=[
            ActionStep(action_type="click", target=clean_intent, wait_s=0.1)
        ],
        summary_message=f"Interacted with: {clean_intent}",
    )


# ---------------------------------------------------------------------------
# Action Plan Execution Engine
# ---------------------------------------------------------------------------

class DesktopActionExecutor:
    """Executes a DesktopPlan safely with visual grounding and panic abort checks."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self._is_aborted = False

    def abort(self) -> None:
        """Signal executor to immediately stop."""
        self._is_aborted = True

    def execute_plan(
        self,
        plan: DesktopPlan,
        on_step_start: Optional[Callable[[int, ActionStep], None]] = None,
        on_pink_action: Optional[Callable[[str, Optional[Tuple[int, int]]], None]] = None,
        on_step_complete: Optional[Callable[[int, ActionStep], None]] = None,
    ) -> bool:
        """Execute all steps in plan.

        Args:
            plan: The DesktopPlan to run.
            on_step_start: Callback invoked before each step (step_index, step).
            on_pink_action: Callback for Pink sprite animations (anim_state, target_coordinates).
            on_step_complete: Callback invoked after each step.

        Returns:
            True if all steps finished successfully, False if aborted or failed.
        """
        if self._is_aborted:
            plan.is_finished = True
            plan.success = False
            return False

        self._is_aborted = False
        log.info("Executing desktop plan: '%s' (%d steps)", plan.intent, len(plan.steps))

        try:
            for idx, step in enumerate(plan.steps):
                if self._is_aborted or os_interop.is_panic_key_pressed():
                    raise os_interop.EmergencyAbortError("Plan aborted by user.")

                step.status = "running"
                plan.current_step_index = idx
                if on_step_start:
                    on_step_start(idx, step)

                self._execute_step(step, on_pink_action)

                step.status = "completed"
                if on_step_complete:
                    on_step_complete(idx, step)

                if step.wait_s > 0:
                    time.sleep(step.wait_s)

            plan.is_finished = True
            plan.success = True
            log.info("Desktop plan '%s' completed successfully.", plan.intent)
            return True

        except os_interop.EmergencyAbortError as abort_err:
            log.warning("Desktop execution aborted: %s", abort_err)
            if plan.steps and plan.current_step_index < len(plan.steps):
                plan.steps[plan.current_step_index].status = "aborted"
                plan.steps[plan.current_step_index].error_message = str(abort_err)
            plan.is_finished = True
            plan.success = False
            return False

        except Exception as err:
            log.error("Desktop execution failed at step %d: %s", plan.current_step_index, err, exc_info=True)
            if plan.steps and plan.current_step_index < len(plan.steps):
                plan.steps[plan.current_step_index].status = "failed"
                plan.steps[plan.current_step_index].error_message = str(err)
            plan.is_finished = True
            plan.success = False
            return False

    def _execute_step(
        self,
        step: ActionStep,
        on_pink_action: Optional[Callable[[str, Optional[Tuple[int, int]]], None]] = None,
    ) -> None:
        """Dispatch a single ActionStep."""
        os_interop.check_emergency_abort()

        if step.action_type == "focus_window":
            win = os_interop.find_window(step.target)
            if win:
                os_interop.focus_window(win.hwnd)
            else:
                uri_fallback = f"{step.target.lower()}://" if step.target else None
                os_interop.launch_or_focus(step.target, uri_fallback=uri_fallback)
            time.sleep(0.15)

        elif step.action_type == "click":
            # If coordinates not set, ground them visually
            target_coords = step.coordinates
            if target_coords is None:
                target_coords = self._ground_and_locate(step.target)
                step.coordinates = target_coords

            if target_coords:
                if on_pink_action:
                    # Notify Pink sprite to leap to target and stomp
                    on_pink_action("jump_to", target_coords)

                os_interop.smooth_move_mouse(target_coords[0], target_coords[1], duration_s=0.2)
                os_interop.click_mouse(target_coords[0], target_coords[1], button="left")
            else:
                log.warning("Could not find coordinates to click for target: '%s'", step.target)

        elif step.action_type == "type_text":
            if step.text:
                if on_pink_action:
                    on_pink_action("typing", None)
                os_interop.type_text(step.text, delay_between_chars_s=0.015)

        elif step.action_type == "press_key":
            if step.key:
                os_interop.press_key(step.key)

        elif step.action_type == "hotkey":
            if step.keys:
                os_interop.hotkey(*step.keys)

        elif step.action_type == "wait":
            time.sleep(step.wait_s)

    def _ground_and_locate(self, target_description: str) -> Optional[Tuple[int, int]]:
        """Capture screen and invoke visual grounding to resolve desktop pixel coordinates."""
        fg = os_interop.get_foreground_window()
        bounds = fg.bounds if fg and fg.width > 100 and fg.height > 100 else None

        b64, orig_w, orig_h, offset = capture_screen_region(bounds=bounds)
        if not b64 or not self.api_key:
            # If no API key or capture failed, fallback to center of foreground window
            if fg and fg.width > 0:
                return fg.center_x, fg.center_y
            return None

        box = ground_ui_element(
            screenshot_b64=b64,
            target_description=target_description,
            api_key=self.api_key,
            region_orig_size=(orig_w, orig_h),
            region_offset=offset,
        )
        if box:
            return box.pixel_x, box.pixel_y

        # Fallback to window center
        if fg and fg.width > 0:
            return fg.center_x, fg.center_y

        return None


# ---------------------------------------------------------------------------
# Action Tag Parser for Yellow's Pixel Buddies
# ---------------------------------------------------------------------------

def extract_desktop_action_tags(text: str) -> List[Dict[str, str]]:
    """Parse structured action tags emitted by Pink's dialogue.

    Supported formats:
    - [desktop_action: WhatsApp, reply to Mom saying on my way]
    - [quick_reply: WhatsApp, Mom, on my way]
    - [click_ui: send button]
    - [type_input: hello world]
    """
    actions: List[Dict[str, str]] = []

    # [desktop_action: <app>, <instruction>]
    for m in re.finditer(r"\[desktop_action:\s*([^,\]]+)(?:,\s*([^\]]+))?\]", text, re.IGNORECASE):
        app = m.group(1).strip()
        intent = m.group(2).strip() if m.group(2) else ""
        actions.append({"type": "desktop_action", "app": app, "intent": intent or app})

    # [quick_reply: <app>, <contact>, <message>]
    for m in re.finditer(r"\[quick_reply:\s*([^,\]]+),\s*([^,\]]+),\s*([^\]]+)\]", text, re.IGNORECASE):
        app = m.group(1).strip()
        contact = m.group(2).strip()
        msg = m.group(3).strip()
        actions.append({"type": "quick_reply", "app": app, "contact": contact, "message": msg})

    # [click_ui: <target>]
    for m in re.finditer(r"\[(?:click_ui|click_target|click):\s*([^\]]+)\]", text, re.IGNORECASE):
        target = m.group(1).strip()
        actions.append({"type": "click_ui", "target": target})

    # [type_input: <text>]
    for m in re.finditer(r"\[(?:type_input|type_text):\s*([^\]]+)\]", text, re.IGNORECASE):
        inp_text = m.group(1).strip()
        actions.append({"type": "type_input", "text": inp_text})

    return actions


def strip_desktop_action_tags(text: str) -> str:
    """Remove desktop action tags from dialogue text so they are not shown to the user."""
    return re.sub(
        r"\[(?:desktop_action|quick_reply|click_ui|click_target|click|type_input|type_text):\s*[^\]]+\]",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()


# ---------------------------------------------------------------------------
# PyQt5 Thread-Safe Worker Thread
# ---------------------------------------------------------------------------

if HAS_PYQT:
    class DesktopActionWorkerThread(QThread):
        """Thread worker executing a DesktopPlan in background without freezing Qt GUI."""
        sig_step_started = pyqtSignal(int, str, str)  # (step_idx, action_type, target)
        sig_pink_action = pyqtSignal(str, int, int)   # (anim_name, target_x, target_y)
        sig_step_completed = pyqtSignal(int, str)     # (step_idx, action_type)
        sig_plan_finished = pyqtSignal(bool, str)     # (success, summary_message)

        def __init__(
            self,
            plan: DesktopPlan,
            api_key: str = "",
            parent: Optional[QObject] = None,
        ) -> None:
            super().__init__(parent)
            self.plan = plan
            self.api_key = api_key
            self.executor = DesktopActionExecutor(api_key=api_key)

        def abort(self) -> None:
            """Abort the active plan execution immediately."""
            self.executor.abort()

        def run(self) -> None:
            def on_start(idx: int, step: ActionStep) -> None:
                self.sig_step_started.emit(idx, step.action_type, step.target)

            def on_pink(anim: str, coords: Optional[Tuple[int, int]]) -> None:
                cx = coords[0] if coords else 0
                cy = coords[1] if coords else 0
                self.sig_pink_action.emit(anim, cx, cy)

            def on_complete(idx: int, step: ActionStep) -> None:
                self.sig_step_completed.emit(idx, step.action_type)

            success = self.executor.execute_plan(
                self.plan,
                on_step_start=on_start,
                on_pink_action=on_pink,
                on_step_complete=on_complete,
            )
            msg = self.plan.summary_message if success else "Action aborted or failed."
            self.sig_plan_finished.emit(success, msg)

