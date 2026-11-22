"""Test doubles for Pink Here.

``FakeOsInterop`` stands in for the ``os_interop`` module inside ``action_planner`` so the takeover
executor can be exercised without sending real input. Constants, dataclasses and exceptions are
delegated to the real module; every input or window-changing function is recorded instead of run.

This is the interim seam for Phase 0-4. Phase 5 replaces it with a proper ``InputBackend``.
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

import os_interop as _real

# Functions that would send input or change window state: recorded, never executed.
RECORDED = (
    "move_mouse", "smooth_move_mouse", "click_mouse", "scroll_mouse", "set_cursor_pos",
    "type_text", "press_key", "hotkey", "key_down", "key_up",
    "focus_window", "launch_or_focus", "trigger_panic_abort",
    "set_window_input_transparent", "set_window_exclude_from_capture",
)


class FakeOsInterop:
    def __init__(self) -> None:
        self.calls: List[Tuple[str, tuple, dict]] = []
        self.foreground: Optional[_real.WindowInfo] = _real.WindowInfo(
            hwnd=1001, title="Untitled - Notepad", process_id=4242, process_name="notepad.exe",
            bounds=(0, 0, 1920, 1080), is_minimized=False, is_cloaked=False,
        )
        self.windows: List[_real.WindowInfo] = []
        self.panic = False
        self.elevated: Tuple[bool, str] = (False, "")
        self.cursor = (0, 0)
        self.monitor = (0, 0, 1920, 1080)

    # ---- recorded side effects -------------------------------------------------------------
    def __getattr__(self, name: str) -> Any:
        if name in RECORDED:
            def _record(*args: Any, **kwargs: Any) -> Any:
                self.calls.append((name, args, kwargs))
                return None if name == "launch_or_focus" else True
            return _record
        return getattr(_real, name)  # constants, WindowInfo, EmergencyAbortError, VK_* ...

    def names(self) -> List[str]:
        """Just the function names that were called, in order."""
        return [c[0] for c in self.calls]

    # ---- queries with controllable answers ---------------------------------------------------
    def get_foreground_window(self) -> Optional[_real.WindowInfo]:
        return self.foreground

    def find_window(self, query: str, app_name: Optional[str] = None, exact: bool = False):
        q = (query or "").lower()
        for w in self.windows:
            if q and (q in w.title.lower() or q in w.process_name.lower()):
                return w
        return None

    def list_windows(self, *args: Any, **kwargs: Any) -> List[_real.WindowInfo]:
        return list(self.windows)

    def is_window_elevated(self, hwnd: int) -> Tuple[bool, str]:
        return self.elevated

    def is_panic_key_pressed(self, check_mouse_pull: bool = False) -> bool:
        return self.panic

    def check_emergency_abort(self, *args: Any, **kwargs: Any) -> None:
        if self.panic:
            raise _real.EmergencyAbortError("fake panic")

    def reset_panic_abort(self) -> None:
        self.panic = False

    def get_cursor_pos(self) -> Tuple[int, int]:
        return self.cursor

    def get_monitor_rect_for_window(self, hwnd: int) -> Tuple[int, int, int, int]:
        return self.monitor

    def get_monitor_rect_for_cursor(self) -> Tuple[int, int, int, int]:
        return self.monitor

    def get_screen_metrics(self) -> _real.ScreenMetrics:
        return _real.get_screen_metrics()

    def attach_worker_desktop(self) -> bool:
        return True

    def detach_worker_desktop(self) -> None:
        return None
