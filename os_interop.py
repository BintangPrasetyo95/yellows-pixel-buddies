"""os_interop.py - Native Windows OS Interop, Window Management, and Input Automation Engine.

Part of Yellow's Pixel Buddies / Pink desktop companion.
Provides safe, robust OS-level capabilities:
- Multi-monitor aware window discovery, enumeration, and focus management.
- Frame bounds calculation via DWM (excluding invisible window drop-shadows).
- Atomic hardware-level input synthesis via Win32 SendInput (mouse moves, clicks, scrolling).
- Full Unicode keyboard injection (UTF-16 surrogate pairs supported for emojis and special symbols).
- Panic abort guards (Emergency ESC key detection and mouse-shake killswitch).
"""

from __future__ import annotations

import ctypes
import logging
import math
import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Callable, Generator, List, Optional, Tuple

log = logging.getLogger("yellows_pixel_buddies.os_interop")

IS_WINDOWS = sys.platform == "win32"

# ---------------------------------------------------------------------------
# Win32 Constants & Type Definitions
# ---------------------------------------------------------------------------

# Virtual Keys
VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # ALT key
VK_PAUSE = 0x13
VK_CAPITAL = 0x14
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21  # Page Up
VK_NEXT = 0x22  # Page Down
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_SNAPSHOT = 0x2C  # Print Screen
VK_INSERT = 0x2D
VK_DELETE = 0x2E
VK_LWIN = 0x5B
VK_RWIN = 0x5C

# Extended Key Map
VIRTUAL_KEY_MAP = {
    "enter": VK_RETURN,
    "return": VK_RETURN,
    "tab": VK_TAB,
    "space": VK_SPACE,
    "backspace": VK_BACK,
    "esc": VK_ESCAPE,
    "escape": VK_ESCAPE,
    "delete": VK_DELETE,
    "del": VK_DELETE,
    "insert": VK_INSERT,
    "home": VK_HOME,
    "end": VK_END,
    "pageup": VK_PRIOR,
    "page_up": VK_PRIOR,
    "pagedown": VK_NEXT,
    "page_down": VK_NEXT,
    "left": VK_LEFT,
    "up": VK_UP,
    "right": VK_RIGHT,
    "down": VK_DOWN,
    "ctrl": VK_CONTROL,
    "control": VK_CONTROL,
    "shift": VK_SHIFT,
    "alt": VK_MENU,
    "win": VK_LWIN,
    "windows": VK_LWIN,
    "super": VK_LWIN,
    "meta": VK_LWIN,
    "cmd": VK_CONTROL,
    "plus": 0xBB,
    "=": 0xBB,
    "minus": 0xBD,
    "-": 0xBD,
    "comma": 0xBC,
    ",": 0xBC,
    "period": 0xBE,
    ".": 0xBE,
    "slash": 0xBF,
    "/": 0xBF,
    "backtick": 0xC0,
    "grave": 0xC0,
    "`": 0xC0,
    "~": 0xC0,
    "lbracket": 0xDB,
    "[": 0xDB,
    "backslash": 0xDC,
    "\\": 0xDC,
    "rbracket": 0xDD,
    "]": 0xDD,
    "semicolon": 0xBA,
    ";": 0xBA,
    "quote": 0xDE,
    "'": 0xDE,
    "volume_mute": 0xAD,
    "volume_down": 0xAE,
    "volume_up": 0xAF,
    "media_next": 0xB0,
    "media_prev": 0xB1,
    "media_stop": 0xB2,
    "media_play_pause": 0xB3,
}
for i in range(1, 13):
    VIRTUAL_KEY_MAP[f"f{i}"] = 0x6F + i
for _ch_code in range(ord("a"), ord("z") + 1):
    VIRTUAL_KEY_MAP[chr(_ch_code)] = _ch_code - 32  # 0x41..0x5A
for _d_code in range(ord("0"), ord("9") + 1):
    VIRTUAL_KEY_MAP[chr(_d_code)] = _d_code          # 0x30..0x39

EXTENDED_KEYS = {
    VK_INSERT,
    VK_DELETE,
    VK_HOME,
    VK_END,
    VK_PRIOR,
    VK_NEXT,
    VK_LEFT,
    VK_UP,
    VK_RIGHT,
    VK_DOWN,
    VK_RWIN,
}

# Input Types
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

# Mouse Event Flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

# Keyboard Event Flags
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

# System Metrics
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

# ShowWindow Commands
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_MAXIMIZE = 3
SW_SHOW = 5
SW_MINIMIZE = 6
SW_RESTORE = 9

# DWM Window Attributes
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14

# Process Permissions
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# ---------------------------------------------------------------------------
# Ctypes Structs (Properly aligned for 32-bit & 64-bit Windows)
# ---------------------------------------------------------------------------

if IS_WINDOWS:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    try:
        advapi32 = ctypes.windll.advapi32
    except Exception:
        advapi32 = None
    try:
        dwmapi = ctypes.windll.dwmapi
    except Exception:
        dwmapi = None

    TOKEN_QUERY = 0x0008
    TokenElevation = 20

    class TOKEN_ELEVATION(ctypes.Structure):
        _fields_ = [("TokenIsElevated", wintypes.DWORD)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", wintypes.DWORD),
            ("u", _INPUT_UNION),
        ]

    MONITOR_DEFAULTTONULL = 0
    MONITOR_DEFAULTTOPRIMARY = 1
    MONITOR_DEFAULTTONEAREST = 2

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
else:
    user32 = None
    kernel32 = None
    dwmapi = None
    INPUT = None


# ---------------------------------------------------------------------------
# Custom Exceptions & Data Classes
# ---------------------------------------------------------------------------

class EmergencyAbortError(Exception):
    """Raised when the user triggers the emergency killswitch (e.g. Esc or rapid mouse shake)."""
    pass


@dataclass
class WindowInfo:
    """Detailed information about an open OS window."""
    hwnd: int
    title: str
    process_id: int
    process_name: str
    bounds: Tuple[int, int, int, int]  # (left, top, right, bottom)
    is_minimized: bool
    is_cloaked: bool

    @property
    def left(self) -> int:
        return self.bounds[0]

    @property
    def top(self) -> int:
        return self.bounds[1]

    @property
    def right(self) -> int:
        return self.bounds[2]

    @property
    def bottom(self) -> int:
        return self.bounds[3]

    @property
    def width(self) -> int:
        return max(0, self.bounds[2] - self.bounds[0])

    @property
    def height(self) -> int:
        return max(0, self.bounds[3] - self.bounds[1])

    @property
    def center_x(self) -> int:
        return self.bounds[0] + self.width // 2

    @property
    def center_y(self) -> int:
        return self.bounds[1] + self.height // 2

    def to_dict(self) -> dict:
        return {
            "hwnd": self.hwnd,
            "title": self.title,
            "process_id": self.process_id,
            "process_name": self.process_name,
            "bounds": list(self.bounds),
            "width": self.width,
            "height": self.height,
            "center": [self.center_x, self.center_y],
            "is_minimized": self.is_minimized,
        }


@dataclass
class ScreenMetrics:
    """Desktop resolution and multi-monitor virtual bounds."""
    virtual_left: int
    virtual_top: int
    virtual_width: int
    virtual_height: int
    primary_width: int
    primary_height: int


# ---------------------------------------------------------------------------
# Thread Desktop Management & Elevation Checks
# ---------------------------------------------------------------------------

_THREAD_LOCAL = threading.local()


def attach_worker_desktop() -> bool:
    """Attach the calling background worker thread to the active user input desktop.

    Should be called once per background worker thread.
    Returns True if successfully attached or not on Windows/GUI thread,
    or False if desktop cannot be accessed (e.g. UAC secure desktop or workstation locked).
    """
    if not IS_WINDOWS or not user32:
        return True

    # Do not call SetThreadDesktop on the Qt main GUI thread
    if threading.current_thread() is threading.main_thread():
        return True

    if getattr(_THREAD_LOCAL, "desktop_attached", False):
        return True

    # DESKTOP_ALL = 0x01FF
    desk = user32.OpenInputDesktop(0, False, 0x01FF)
    if not desk:
        log.warning("Could not open input desktop (UAC secure desktop or workstation locked).")
        return False

    if user32.SetThreadDesktop(desk):
        _THREAD_LOCAL.desktop_attached = True
        _THREAD_LOCAL.desktop_handle = desk
        return True
    else:
        user32.CloseDesktop(desk)
        return False


def detach_worker_desktop() -> None:
    """Detach thread from input desktop and close desktop handle."""
    desk = getattr(_THREAD_LOCAL, "desktop_handle", None)
    if desk and IS_WINDOWS and user32:
        try:
            user32.CloseDesktop(desk)
        except Exception:
            pass
    _THREAD_LOCAL.desktop_attached = False
    _THREAD_LOCAL.desktop_handle = None


@contextmanager
def ensure_input_desktop() -> Generator[None, None, None]:
    """Context manager ensuring calling thread is attached to input desktop without per-call churn."""
    if not IS_WINDOWS or not user32:
        yield
        return

    # If on main thread or already attached, yield directly without churn
    if threading.current_thread() is threading.main_thread() or getattr(_THREAD_LOCAL, "desktop_attached", False):
        yield
        return

    # Background thread not yet attached: attach once and cache
    attach_worker_desktop()
    yield


def is_window_elevated(hwnd: int) -> Tuple[bool, str]:
    """Check if the process owning the window is running with elevated (Administrator) privileges.

    Returns:
        (is_elevated, reason_or_token_description)
    """
    if not IS_WINDOWS or not user32 or not kernel32 or not advapi32:
        return False, "Non-Windows or missing Win32 APIs"

    if not user32.IsWindow(hwnd):
        return False, "Invalid window handle"

    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value <= 0:
        return False, "No valid PID associated with window"

    # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h_proc:
        err = ctypes.GetLastError()
        # 5 = ERROR_ACCESS_DENIED: Standard-integrity processes cannot open elevated/protected processes
        if err == 5:
            return True, "Access denied opening process (likely elevated/protected Administrator window)"
        return False, f"Failed to open process (error {err})"

    h_token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(h_proc, TOKEN_QUERY, ctypes.byref(h_token)):
            err = ctypes.GetLastError()
            if err == 5:
                return True, "Access denied opening process token (likely elevated/protected Administrator window)"
            return False, f"Failed to open process token (error {err})"

        elevation = TOKEN_ELEVATION()
        ret_len = wintypes.DWORD(0)
        if advapi32.GetTokenInformation(
            h_token,
            TokenElevation,
            ctypes.byref(elevation),
            ctypes.sizeof(elevation),
            ctypes.byref(ret_len),
        ):
            is_elevated = bool(elevation.TokenIsElevated != 0)
            reason = "Process has elevated Administrator token" if is_elevated else "Standard non-elevated user token"
            return is_elevated, reason

        return False, "Failed to query TokenElevation"
    finally:
        if h_token:
            kernel32.CloseHandle(h_token)
        kernel32.CloseHandle(h_proc)


# ---------------------------------------------------------------------------
# Screen Metrics & Coordinate Transformation
# ---------------------------------------------------------------------------

def get_screen_metrics() -> ScreenMetrics:
    """Retrieve virtual and primary screen dimensions."""
    if not IS_WINDOWS or not user32:
        return ScreenMetrics(0, 0, 1920, 1080, 1920, 1080)

    vl = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vt = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    pw = user32.GetSystemMetrics(SM_CXSCREEN)
    ph = user32.GetSystemMetrics(SM_CYSCREEN)

    return ScreenMetrics(
        virtual_left=vl,
        virtual_top=vt,
        virtual_width=vw if vw > 0 else pw,
        virtual_height=vh if vh > 0 else ph,
        primary_width=pw,
        primary_height=ph,
    )


def coords_to_normalized_virtual(x: int, y: int) -> Tuple[int, int]:
    """Convert desktop pixel coordinates into normalized (0..65535) coordinates for SendInput."""
    metrics = get_screen_metrics()
    norm_x = int(math.floor(((x - metrics.virtual_left) * 65536) / max(1, metrics.virtual_width)))
    norm_y = int(math.floor(((y - metrics.virtual_top) * 65536) / max(1, metrics.virtual_height)))
    # Clamp to valid 16-bit range
    norm_x = max(0, min(65535, norm_x))
    norm_y = max(0, min(65535, norm_y))
    return norm_x, norm_y


def ensure_process_dpi_aware() -> bool:
    """Ensure the process is configured for Per-Monitor DPI Awareness v2.

    Guarantees coordinates in SendInput, GetCursorPos, and GetWindowRect
    match physical device screen pixels across mixed-DPI monitors.
    """
    if not IS_WINDOWS or not user32:
        return True
    try:
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
            res = user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            if res:
                return True
        try:
            shcore = ctypes.windll.shcore
            # PROCESS_PER_MONITOR_DPI_AWARE = 2
            if shcore.SetProcessDpiAwareness(2) == 0:
                return True
        except Exception:
            pass
        if hasattr(user32, "SetProcessDPIAware"):
            return bool(user32.SetProcessDPIAware())
    except Exception as e:
        log.debug("ensure_process_dpi_aware error: %s", e)
    return False


def get_monitor_rect_for_window(hwnd: int) -> Tuple[int, int, int, int]:
    """Return the physical pixel bounds (left, top, right, bottom) of the monitor displaying the window."""
    if not IS_WINDOWS or not user32 or not hwnd or not user32.IsWindow(hwnd):
        metrics = get_screen_metrics()
        return (0, 0, metrics.primary_width, metrics.primary_height)

    try:
        h_mon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if h_mon:
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(h_mon, ctypes.byref(mi)):
                r = mi.rcMonitor
                return (r.left, r.top, r.right, r.bottom)
    except Exception as e:
        log.debug("get_monitor_rect_for_window error: %s", e)

    metrics = get_screen_metrics()
    return (0, 0, metrics.primary_width, metrics.primary_height)


def get_monitor_rect_for_point(x: int, y: int) -> Tuple[int, int, int, int]:
    """Return the physical pixel bounds (left, top, right, bottom) of the monitor containing (x, y)."""
    if not IS_WINDOWS or not user32:
        metrics = get_screen_metrics()
        return (0, 0, metrics.primary_width, metrics.primary_height)

    try:
        pt = wintypes.POINT(int(x), int(y))
        h_mon = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
        if h_mon:
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(h_mon, ctypes.byref(mi)):
                r = mi.rcMonitor
                return (r.left, r.top, r.right, r.bottom)
    except Exception as e:
        log.debug("get_monitor_rect_for_point error: %s", e)

    metrics = get_screen_metrics()
    return (0, 0, metrics.primary_width, metrics.primary_height)


def get_monitor_rect_for_cursor() -> Tuple[int, int, int, int]:
    """Return the physical pixel bounds (left, top, right, bottom) of the monitor containing the cursor."""
    cx, cy = get_cursor_pos()
    return get_monitor_rect_for_point(cx, cy)


if IS_WINDOWS:
    ensure_process_dpi_aware()


# ---------------------------------------------------------------------------
# Window Management & Introspection
# ---------------------------------------------------------------------------

def _get_process_name(pid: int) -> str:
    """Retrieve executable name from process ID."""
    if not IS_WINDOWS or not kernel32 or pid <= 0:
        return ""
    h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h_proc:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    except Exception:
        pass
    finally:
        kernel32.CloseHandle(h_proc)
    return ""


def get_window_bounds(hwnd: int) -> Tuple[int, int, int, int]:
    """Get accurate window bounds excluding invisible drop shadows via DWM."""
    if not IS_WINDOWS:
        return 0, 0, 0, 0

    rect = wintypes.RECT()
    # Try DWM extended frame bounds first (precise client+border rect)
    if dwmapi:
        try:
            hr = dwmapi.DwmGetWindowAttribute(
                hwnd,
                DWMWA_EXTENDED_FRAME_BOUNDS,
                ctypes.byref(rect),
                ctypes.sizeof(rect),
            )
            if hr == 0:
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            pass

    # Fallback to standard GetWindowRect
    if user32 and user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return rect.left, rect.top, rect.right, rect.bottom

    return 0, 0, 0, 0


def is_window_cloaked(hwnd: int) -> bool:
    """Return True if the window is cloaked (e.g. suspended UWP app in background)."""
    if not IS_WINDOWS or not dwmapi:
        return False
    cloaked = wintypes.DWORD(0)
    try:
        hr = dwmapi.DwmGetWindowAttribute(
            hwnd,
            DWMWA_CLOAKED,
            ctypes.byref(cloaked),
            ctypes.sizeof(cloaked),
        )
        return hr == 0 and cloaked.value != 0
    except Exception:
        return False


def get_window_info(hwnd: int) -> Optional[WindowInfo]:
    """Build a WindowInfo object from an HWND handle."""
    if not IS_WINDOWS or not user32 or not user32.IsWindow(hwnd):
        return None

    length = user32.GetWindowTextLengthW(hwnd)
    title = ""
    if length > 0:
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    proc_name = _get_process_name(pid.value)

    bounds = get_window_bounds(hwnd)
    is_min = bool(user32.IsIconic(hwnd))
    is_cloak = is_window_cloaked(hwnd)

    return WindowInfo(
        hwnd=hwnd,
        title=title,
        process_id=pid.value,
        process_name=proc_name,
        bounds=bounds,
        is_minimized=is_min,
        is_cloaked=is_cloak,
    )


def list_windows(
    visible_only: bool = True,
    exclude_cloaked: bool = True,
    exclude_self: bool = True,
) -> List[WindowInfo]:
    """Enumerate top-level desktop windows."""
    if not IS_WINDOWS or not user32:
        return []

    windows: List[WindowInfo] = []
    self_pid = os.getpid()

    with ensure_input_desktop():
        def enum_callback(hwnd: int, _: int) -> bool:
            if visible_only and not user32.IsWindowVisible(hwnd):
                return True

            info = get_window_info(hwnd)
            if not info:
                return True

            if exclude_self and info.process_id == self_pid:
                return True

            if exclude_cloaked and info.is_cloaked:
                return True

            # Exclude zero-size or empty-title utility windows unless requested
            if visible_only and (not info.title.strip() or info.width <= 0 or info.height <= 0):
                return True

            windows.append(info)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_callback), 0)

    return windows


APP_SEARCH_ALIASES = {
    "vscode": ("visual studio code", "code.exe", "antigravity"),
    "vs code": ("visual studio code", "code.exe", "antigravity"),
    "code": ("visual studio code", "code.exe", "antigravity"),
    "chrome": ("google chrome", "chrome.exe"),
    "claude": ("claude", "chrome.exe", "msedge.exe"),
    "chatgpt": ("chatgpt", "chrome.exe", "msedge.exe"),
    "browser": ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"),
    "edge": ("microsoft edge", "msedge.exe"),
    "firefox": ("mozilla firefox", "firefox.exe"),
    "whatsapp": ("whatsapp", "chrome.exe", "msedge.exe"),
    "youtube music": ("youtube music", "music.youtube", "chrome.exe", "msedge.exe"),
    "youtube": ("youtube", "chrome.exe", "msedge.exe"),
    "spotify": ("spotify", "spotify.exe"),
    "terminal": ("windowsterminal.exe", "powershell.exe", "pwsh.exe", "cmd.exe", "visual studio code", "code.exe"),
    "powershell": ("powershell.exe", "pwsh.exe", "windowsterminal.exe"),
    "explorer": ("file explorer", "explorer.exe"),
    "files": ("file explorer", "explorer.exe"),
    "word": ("winword.exe", "word"),
    "excel": ("excel.exe", "excel"),
    "discord": ("discord", "discord.exe"),
}


def find_window(query: str, app_name: Optional[str] = None, exact: bool = False) -> Optional[WindowInfo]:
    """Find the best matching window using exact matching, process names, aliases, or word-boundary title search.

    Avoids false positives (e.g. 'word' matching 'Password Manager' or 'edge' matching 'Knowledge Base').
    """
    q_lower = query.strip().lower()
    app_lower = app_name.strip().lower() if app_name else None

    candidates = list_windows(visible_only=True, exclude_cloaked=True, exclude_self=True)

    # 1. Exact title match
    for w in candidates:
        if exact and w.title == query:
            return w
        if not exact and w.title.strip().lower() == q_lower:
            return w

    # 2. Exact process name match (e.g. 'chrome.exe' or 'notepad')
    if app_lower:
        for w in candidates:
            if w.process_name.lower() == app_lower or w.process_name.lower() == f"{app_lower}.exe":
                return w
    if q_lower:
        for w in candidates:
            if w.process_name.lower() == q_lower or w.process_name.lower() == f"{q_lower}.exe":
                return w

    # 3. Known application search aliases (prioritizing process name, then word-boundary title)
    alias_terms = APP_SEARCH_ALIASES.get(q_lower, ())
    for term in alias_terms:
        # Check process name first
        for w in candidates:
            if term.endswith(".exe") and w.process_name.lower() == term:
                return w
        # Check title using word boundaries
        term_clean = re.sub(r"\.exe$", "", term)
        for w in candidates:
            if re.search(r"\b" + re.escape(term_clean) + r"\b", w.title, re.IGNORECASE):
                return w

    # 4. Word-boundary search in title (e.g. 'word' matches 'Document - Word' but NOT 'Password Manager')
    if q_lower:
        word_pattern = r"\b" + re.escape(q_lower) + r"\b"
        for w in candidates:
            if re.search(word_pattern, w.title, re.IGNORECASE):
                return w

    # 5. Process name prefix or word-boundary match (e.g. 'code' matches 'code.exe' or 'code-oss.exe', but 'word' never matches 'password.exe')
    if q_lower:
        for w in candidates:
            proc_base = re.sub(r"\.exe$", "", w.process_name.lower())
            if proc_base.startswith(q_lower) or re.search(r"(?:^|[_\-\.])" + re.escape(q_lower) + r"(?:$|[_\-\.])", proc_base):
                return w

    # 6. Fallback: loose substring in title ONLY if query is at least 5 characters long
    if q_lower and len(q_lower) >= 5:
        for w in candidates:
            if q_lower in w.title.lower():
                return w

    return None


def get_foreground_window() -> Optional[WindowInfo]:
    """Retrieve details for the active foreground window."""
    if not IS_WINDOWS or not user32:
        return None

    with ensure_input_desktop():
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            return get_window_info(hwnd)
    return None


def focus_window(hwnd: int) -> bool:
    """Robustly restore and bring a window into foreground focus.

    Bypasses Windows UIPI and foreground-lock restrictions by attaching thread
    input and un-minimizing if iconic.
    """
    if not IS_WINDOWS or not user32 or not user32.IsWindow(hwnd):
        return False

    with ensure_input_desktop():
        # Restore if minimized
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        else:
            user32.ShowWindow(hwnd, SW_SHOW)

        fg_hwnd = user32.GetForegroundWindow()
        if fg_hwnd == hwnd:
            return True

        cur_thread = kernel32.GetCurrentThreadId() if kernel32 else 0
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0

        attached = False
        if fg_thread and cur_thread and fg_thread != cur_thread:
            attached = bool(user32.AttachThreadInput(cur_thread, fg_thread, True))

        try:
            user32.BringWindowToTop(hwnd)
            success = bool(user32.SetForegroundWindow(hwnd))
            user32.SetActiveWindow(hwnd)
            return success or (user32.GetForegroundWindow() == hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(cur_thread, fg_thread, False)


def set_window_input_transparent(target: Any, enabled: bool = True) -> bool:
    """Toggle WS_EX_TRANSPARENT | WS_EX_LAYERED so mouse clicks pass straight through the window."""
    if not IS_WINDOWS or not user32:
        return False
    try:
        hwnd = int(target.winId()) if hasattr(target, "winId") else int(target)
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_LAYERED = 0x00080000
        WS_EX_NOACTIVATE = 0x08000000
        get_style = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
        set_style = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
        get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
        get_style.restype = ctypes.c_ssize_t
        set_style.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        set_style.restype = ctypes.c_ssize_t

        old_style = get_style(hwnd, GWL_EXSTYLE)
        if enabled:
            new_style = old_style | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE
        else:
            new_style = old_style & ~WS_EX_TRANSPARENT
        if new_style != old_style:
            set_style(hwnd, GWL_EXSTYLE, new_style)
            SWP_FRAMECHANGED = 0x0020
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            HWND_TOPMOST = -1
            user32.SetWindowPos(
                ctypes.c_void_p(hwnd),
                ctypes.c_void_p(HWND_TOPMOST),
                0, 0, 0, 0,
                SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
        return True
    except Exception as e:
        log.warning("Failed to set window input transparency: %s", e)
        return False


def set_window_exclude_from_capture(target: Any, enabled: bool = True) -> bool:
    """Exclude window from screen captures (WDA_EXCLUDEFROMCAPTURE) while keeping it visible to the user."""
    if not IS_WINDOWS or not user32:
        return False
    try:
        hwnd = int(target.winId()) if hasattr(target, "winId") else int(target)
        WDA_NONE = 0x00000000
        WDA_EXCLUDEFROMCAPTURE = 0x00000011
        affinity = WDA_EXCLUDEFROMCAPTURE if enabled else WDA_NONE
        return bool(user32.SetWindowDisplayAffinity(hwnd, affinity))
    except Exception as e:
        log.debug("SetWindowDisplayAffinity not available: %s", e)
        return False


ALLOWED_START_MENU_APPS = {
    # Web Browsers
    "chrome", "google chrome", "msedge", "edge", "microsoft edge", "firefox", "brave",
    # Development / Editors
    "code", "visual studio code", "vscode", "notepad", "notepad++", "sublime text",
    # Communication / Social
    "whatsapp", "discord", "slack", "telegram", "teams", "microsoft teams", "zoom",
    # Media & Audio
    "spotify", "vlc", "youtube music",
    # Utilities & Office
    "calc", "calculator", "explorer", "file explorer", "paint", "mspaint", "snipping tool",
    "word", "excel", "powerpoint", "onenote",
}


def launch_or_focus(query: str, uri_fallback: Optional[str] = None, use_start_menu: bool = True) -> Optional[WindowInfo]:
    """Find an open window or launch it via URI / Start menu search, then focus it.

    Example:
        launch_or_focus("WhatsApp", uri_fallback="whatsapp://")
    """
    win = find_window(query)
    if win:
        focus_window(win.hwnd)
        time.sleep(0.2)
        return win

    if uri_fallback:
        try:
            os.startfile(uri_fallback)
            time.sleep(1.2)
            win = find_window(query)
            if win:
                focus_window(win.hwnd)
                return win
        except Exception as e:
            log.debug("URI fallback '%s' did not launch directly: %s", uri_fallback, e)

    if use_start_menu and query.strip():
        q_raw = query.strip()
        # Security Guard: Block metacharacters and arbitrary command injection
        if any(c in q_raw for c in (";", "&", "|", ">", "<", "`", "$", "%", "\\", "/", '"', "'")):
            log.warning("Start menu launch rejected due to suspicious characters in query: %r", q_raw)
            return None

        # Security Guard: Whitelist check
        q_clean = q_raw.lower()
        is_allowed = any(
            q_clean == app or q_clean.startswith(f"{app} ") or app in q_clean
            for app in ALLOWED_START_MENU_APPS
        )
        if not is_allowed:
            log.warning("Start menu launch blocked for unvetted application '%s'.", query)
            return None

        try:
            press_key("win")
            time.sleep(0.45)
            type_text(q_raw, delay_between_chars_s=0.02)
            time.sleep(0.45)
            press_key("enter")
            time.sleep(1.2)
            win = find_window(query)
            if win:
                focus_window(win.hwnd)
                return win
        except Exception as e:
            log.warning("Start menu launch failed for '%s': %s", query, e)

    return None


# ---------------------------------------------------------------------------
# Safety & Panic Abort Killswitch
# ---------------------------------------------------------------------------

_PANIC_ABORT_TRIGGERED: bool = False
_LAST_AUTOMATED_CURSOR_POS: Optional[Tuple[int, int]] = None
_IS_AUTOMATED_MOVE_IN_PROGRESS: bool = False
_ABORT_SHAKE_THRESHOLD_PX: int = 280


def reset_panic_abort() -> None:
    """Reset the emergency abort latch at the start of a new automation session."""
    global _PANIC_ABORT_TRIGGERED, _LAST_AUTOMATED_CURSOR_POS, _IS_AUTOMATED_MOVE_IN_PROGRESS
    _PANIC_ABORT_TRIGGERED = False
    _IS_AUTOMATED_MOVE_IN_PROGRESS = False
    if IS_WINDOWS and user32:
        # Clear any stale 0x0001 transition bit on VK_ESCAPE from before this session started
        user32.GetAsyncKeyState(VK_ESCAPE)
    _LAST_AUTOMATED_CURSOR_POS = None


def trigger_panic_abort() -> None:
    """Explicitly latch the global emergency abort state."""
    global _PANIC_ABORT_TRIGGERED
    _PANIC_ABORT_TRIGGERED = True


def is_panic_key_pressed(check_mouse_pull: bool = False) -> bool:
    """Check if the user pressed Escape (even briefly) or yanked the physical mouse away."""
    global _PANIC_ABORT_TRIGGERED
    if _PANIC_ABORT_TRIGGERED:
        return True
    if not IS_WINDOWS or not user32:
        return False

    # 0x8000 = currently held down; 0x0001 = pressed since last GetAsyncKeyState call
    if bool(user32.GetAsyncKeyState(VK_ESCAPE) & 0x8001):
        _PANIC_ABORT_TRIGGERED = True
        return True

    if check_mouse_pull and not _IS_AUTOMATED_MOVE_IN_PROGRESS and _LAST_AUTOMATED_CURSOR_POS is not None:
        cur_x, cur_y = get_cursor_pos()
        dist = math.hypot(cur_x - _LAST_AUTOMATED_CURSOR_POS[0], cur_y - _LAST_AUTOMATED_CURSOR_POS[1])
        if dist > _ABORT_SHAKE_THRESHOLD_PX:
            log.info("User pulled mouse %dpx away from automated cursor position %s -> triggering abort.", int(dist), _LAST_AUTOMATED_CURSOR_POS)
            _PANIC_ABORT_TRIGGERED = True
            return True

    return False


def check_emergency_abort(
    expected_cursor_pos: Optional[Tuple[int, int]] = None,
    shake_threshold_px: int = 280,
) -> None:
    """Check for user-initiated abort (Escape key pressed or user jerking the physical mouse).

    Raises:
        EmergencyAbortError: If abort condition is triggered.
    """
    global _PANIC_ABORT_TRIGGERED
    if is_panic_key_pressed(check_mouse_pull=(expected_cursor_pos is None)):
        raise EmergencyAbortError("Emergency abort triggered by user (ESC or mouse pull).")

    if expected_cursor_pos is not None:
        current_pos = get_cursor_pos()
        dx = current_pos[0] - expected_cursor_pos[0]
        dy = current_pos[1] - expected_cursor_pos[1]
        dist = math.hypot(dx, dy)
        if dist > shake_threshold_px:
            _PANIC_ABORT_TRIGGERED = True
            raise EmergencyAbortError(
                f"Emergency abort triggered: Mouse moved {int(dist)}px away from target."
            )


# ---------------------------------------------------------------------------
# Hardware-Level Mouse Control (Win32 SendInput)
# ---------------------------------------------------------------------------

def get_cursor_pos() -> Tuple[int, int]:
    """Return the current (x, y) coordinates of the mouse cursor."""
    if not IS_WINDOWS or not user32:
        return 0, 0
    pt = wintypes.POINT()
    with ensure_input_desktop():
        user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def set_cursor_pos(x: int, y: int) -> bool:
    """Instantly teleport cursor to (x, y)."""
    global _LAST_AUTOMATED_CURSOR_POS
    if not IS_WINDOWS or not user32:
        return False
    with ensure_input_desktop():
        ok = bool(user32.SetCursorPos(int(x), int(y)))
        if ok:
            _LAST_AUTOMATED_CURSOR_POS = (int(x), int(y))
        return ok


def _send_mouse_input(dw_flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> bool:
    """Low-level wrapper for mouse events in SendInput."""
    if not IS_WINDOWS or not user32:
        return False

    with ensure_input_desktop():
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.u.mi.dx = dx
        inp.u.mi.dy = dy
        inp.u.mi.mouseData = data
        inp.u.mi.dwFlags = dw_flags
        inp.u.mi.time = 0
        inp.u.mi.dwExtraInfo = 0

        res = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        return res == 1


def move_mouse(x: int, y: int) -> bool:
    """Move cursor to (x, y) absolute desktop coordinates using SendInput."""
    global _LAST_AUTOMATED_CURSOR_POS
    norm_x, norm_y = coords_to_normalized_virtual(x, y)
    flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    _LAST_AUTOMATED_CURSOR_POS = (int(x), int(y))
    ok = _send_mouse_input(flags, dx=norm_x, dy=norm_y)
    return ok


def smooth_move_mouse(
    target_x: int,
    target_y: int,
    duration_s: float = 0.28,
    steps: int = 25,
    abort_on_shake: bool = True,
) -> bool:
    """Smoothly glide mouse cursor to (target_x, target_y) with cubic ease-out."""
    global _IS_AUTOMATED_MOVE_IN_PROGRESS
    start_x, start_y = get_cursor_pos()
    if start_x == target_x and start_y == target_y:
        return True

    steps = max(5, steps)
    interval = duration_s / steps
    expected_pos = (start_x, start_y)

    _IS_AUTOMATED_MOVE_IN_PROGRESS = True
    try:
        for step in range(1, steps + 1):
            if abort_on_shake:
                check_emergency_abort(expected_cursor_pos=expected_pos, shake_threshold_px=280)

            # Cubic ease-out: 1 - (1 - t)^3
            t = step / steps
            ease = 1.0 - math.pow(1.0 - t, 3)

            curr_x = int(round(start_x + (target_x - start_x) * ease))
            curr_y = int(round(start_y + (target_y - start_y) * ease))

            move_mouse(curr_x, curr_y)
            expected_pos = (curr_x, curr_y)
            time.sleep(interval)

        # Ensure precision on final point
        move_mouse(target_x, target_y)
        return True
    finally:
        _IS_AUTOMATED_MOVE_IN_PROGRESS = False


def mouse_down(button: str = "left") -> bool:
    """Press down mouse button ('left', 'right', 'middle')."""
    btn = button.lower()
    flag = MOUSEEVENTF_LEFTDOWN
    if btn == "right":
        flag = MOUSEEVENTF_RIGHTDOWN
    elif btn == "middle":
        flag = MOUSEEVENTF_MIDDLEDOWN
    return _send_mouse_input(flag)


def mouse_up(button: str = "left") -> bool:
    """Release mouse button ('left', 'right', 'middle')."""
    btn = button.lower()
    flag = MOUSEEVENTF_LEFTUP
    if btn == "right":
        flag = MOUSEEVENTF_RIGHTUP
    elif btn == "middle":
        flag = MOUSEEVENTF_MIDDLEUP
    return _send_mouse_input(flag)


def click_mouse(
    x: Optional[int] = None,
    y: Optional[int] = None,
    button: str = "left",
    clicks: int = 1,
    interval_s: float = 0.05,
) -> bool:
    """Click at current or specified desktop coordinates."""
    check_emergency_abort()

    if x is not None and y is not None:
        move_mouse(x, y)
        time.sleep(0.02)

    for i in range(clicks):
        check_emergency_abort()
        mouse_down(button)
        time.sleep(0.02)
        mouse_up(button)
        if i < clicks - 1:
            time.sleep(interval_s)

    return True


def scroll_mouse(clicks: int) -> bool:
    """Scroll vertical mouse wheel (positive = up, negative = down)."""
    check_emergency_abort()
    # 1 wheel detent = 120 units
    return _send_mouse_input(MOUSEEVENTF_WHEEL, data=clicks * 120)


# ---------------------------------------------------------------------------
# Hardware-Level Keyboard Control (Win32 SendInput Unicode)
# ---------------------------------------------------------------------------

def _send_key_input(vk: int = 0, scan: int = 0, flags: int = 0) -> bool:
    """Low-level wrapper for keyboard events in SendInput."""
    if not IS_WINDOWS or not user32:
        return False

    with ensure_input_desktop():
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.u.ki.wVk = vk
        inp.u.ki.wScan = scan
        inp.u.ki.dwFlags = flags
        inp.u.ki.time = 0
        inp.u.ki.dwExtraInfo = 0

        res = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        return res == 1


def _resolve_vk(key: str) -> Optional[int]:
    """Resolve a human-readable key name or single character to a Win32 Virtual-Key code."""
    k_lower = key.lower().strip()
    vk = VIRTUAL_KEY_MAP.get(k_lower)
    if vk:
        return vk
    if len(k_lower) == 1:
        ch_code = ord(k_lower)
        if ord("a") <= ch_code <= ord("z"):
            return ch_code - 32
        if ord("0") <= ch_code <= ord("9"):
            return ch_code
        if IS_WINDOWS and user32:
            scan_res = user32.VkKeyScanW(ch_code)
            if scan_res != -1:
                return scan_res & 0xFF
    return None


def key_down(key: str) -> bool:
    """Press down a virtual key (e.g. 'enter', 'tab', 'ctrl', 'l')."""
    vk = _resolve_vk(key)
    if not vk:
        log.warning("Unknown key for key_down: '%s'", key)
        return False

    flags = 0
    if vk in EXTENDED_KEYS:
        flags |= KEYEVENTF_EXTENDEDKEY

    return _send_key_input(vk=vk, flags=flags)


def key_up(key: str) -> bool:
    """Release a virtual key."""
    vk = _resolve_vk(key)
    if not vk:
        log.warning("Unknown key for key_up: '%s'", key)
        return False

    flags = KEYEVENTF_KEYUP
    if vk in EXTENDED_KEYS:
        flags |= KEYEVENTF_EXTENDEDKEY

    return _send_key_input(vk=vk, flags=flags)


def press_key(key: str, duration_s: float = 0.04) -> bool:
    """Press and release a virtual key."""
    check_emergency_abort()
    vk = _resolve_vk(key)
    is_esc = (vk == VK_ESCAPE)
    success = key_down(key)
    time.sleep(duration_s)
    key_up(key)
    if is_esc and IS_WINDOWS and user32:
        # Swallow/clear transition state resulting from our own injected Escape key
        user32.GetAsyncKeyState(VK_ESCAPE)
    return success


def hotkey(*keys: str, interval_s: float = 0.04) -> bool:
    """Press a key combination in order, then release in reverse order (e.g. 'ctrl', 'c').

    Validates all keys before pressing any to prevent stuck modifiers on invalid key names.
    """
    check_emergency_abort()
    if not keys:
        return False

    # Validate all keys before pressing any modifiers
    for k in keys:
        if _resolve_vk(k) is None:
            log.warning("Unknown key '%s' in hotkey combo %s; skipping execution to avoid stuck modifier keys.", k, keys)
            return False

    pressed: List[str] = []
    has_esc = False
    try:
        for k in keys:
            if _resolve_vk(k) == VK_ESCAPE:
                has_esc = True
            key_down(k)
            pressed.append(k)
            time.sleep(0.02)
        time.sleep(interval_s)
    finally:
        for k in reversed(pressed):
            key_up(k)
            time.sleep(0.01)
        if has_esc and IS_WINDOWS and user32:
            # Swallow/clear transition state resulting from our own injected Escape key
            user32.GetAsyncKeyState(VK_ESCAPE)
    return True


def _send_input_batch(inputs_list: List[INPUT]) -> bool:
    """Dispatch a batch of INPUT structs atomically via a single Win32 SendInput call."""
    if not IS_WINDOWS or not user32 or not inputs_list:
        return False
    count = len(inputs_list)
    input_array = (INPUT * count)(*inputs_list)
    sent = user32.SendInput(count, input_array, ctypes.sizeof(INPUT))
    return sent == count


def send_unicode_char(char: str) -> bool:
    """Send a single character via Win32 Unicode injection.

    Handles UTF-16 surrogate pairs for emojis (e.g. 🐱, 💖).
    """
    check_emergency_abort()
    utf16_bytes = char.encode("utf-16-le")
    # Group into 16-bit word integers
    words = [
        int.from_bytes(utf16_bytes[i:i + 2], byteorder="little")
        for i in range(0, len(utf16_bytes), 2)
    ]

    for w in words:
        # Key down
        _send_key_input(vk=0, scan=w, flags=KEYEVENTF_UNICODE)
        # Key up
        _send_key_input(vk=0, scan=w, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)

    return True


def type_text(
    text: str,
    delay_between_chars_s: float = 0.015,
    abort_check: Optional[Callable[[], bool]] = None,
    chunk_size: int = 25,
    use_shift_enter: bool = False,
    expected_hwnd: Optional[int] = None,
) -> bool:
    """Type out a string using chunked atomic SendInput Unicode injection.

    Batches characters into atomic chunks (default 25 chars) to prevent physical
    user keystrokes from interleaving, while checking for panic aborts and window focus
    changes between chunks. Supports Shift+Enter for multiline text in chat apps.
    """
    if not text:
        return True

    # Break text into chunks of chunk_size characters
    chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

    for chunk in chunks:
        check_emergency_abort()
        if abort_check and abort_check():
            raise EmergencyAbortError("Typing canceled by custom abort check.")

        # Guard: verify target window has not lost foreground focus
        if expected_hwnd is not None and IS_WINDOWS and user32:
            fg = user32.GetForegroundWindow()
            if fg != expected_hwnd:
                log.warning("Foreground window changed from %s to %s during typing; canceling.", expected_hwnd, fg)
                raise EmergencyAbortError("Typing canceled: target window lost foreground focus.")

        # Build atomic INPUT list for this chunk
        inputs_list: List[INPUT] = []
        for ch in chunk:
            if ch == "\n":
                if use_shift_enter:
                    # Shift down
                    inp_s_dn = INPUT()
                    inp_s_dn.type = INPUT_KEYBOARD
                    inp_s_dn.u.ki.wVk = VK_SHIFT
                    inputs_list.append(inp_s_dn)

                    # Enter down
                    inp_e_dn = INPUT()
                    inp_e_dn.type = INPUT_KEYBOARD
                    inp_e_dn.u.ki.wVk = VK_RETURN
                    inputs_list.append(inp_e_dn)

                    # Enter up
                    inp_e_up = INPUT()
                    inp_e_up.type = INPUT_KEYBOARD
                    inp_e_up.u.ki.wVk = VK_RETURN
                    inp_e_up.u.ki.dwFlags = KEYEVENTF_KEYUP
                    inputs_list.append(inp_e_up)

                    # Shift up
                    inp_s_up = INPUT()
                    inp_s_up.type = INPUT_KEYBOARD
                    inp_s_up.u.ki.wVk = VK_SHIFT
                    inp_s_up.u.ki.dwFlags = KEYEVENTF_KEYUP
                    inputs_list.append(inp_s_up)
                else:
                    inp_e_dn = INPUT()
                    inp_e_dn.type = INPUT_KEYBOARD
                    inp_e_dn.u.ki.wVk = VK_RETURN
                    inputs_list.append(inp_e_dn)

                    inp_e_up = INPUT()
                    inp_e_up.type = INPUT_KEYBOARD
                    inp_e_up.u.ki.wVk = VK_RETURN
                    inp_e_up.u.ki.dwFlags = KEYEVENTF_KEYUP
                    inputs_list.append(inp_e_up)
            elif ch == "\t":
                inp_t_dn = INPUT()
                inp_t_dn.type = INPUT_KEYBOARD
                inp_t_dn.u.ki.wVk = VK_TAB
                inputs_list.append(inp_t_dn)

                inp_t_up = INPUT()
                inp_t_up.type = INPUT_KEYBOARD
                inp_t_up.u.ki.wVk = VK_TAB
                inp_t_up.u.ki.dwFlags = KEYEVENTF_KEYUP
                inputs_list.append(inp_t_up)
            else:
                utf16_bytes = ch.encode("utf-16-le")
                words = [
                    int.from_bytes(utf16_bytes[i:i + 2], byteorder="little")
                    for i in range(0, len(utf16_bytes), 2)
                ]
                for w in words:
                    inp_dn = INPUT()
                    inp_dn.type = INPUT_KEYBOARD
                    inp_dn.u.ki.wVk = 0
                    inp_dn.u.ki.wScan = w
                    inp_dn.u.ki.dwFlags = KEYEVENTF_UNICODE
                    inputs_list.append(inp_dn)

                    inp_up = INPUT()
                    inp_up.type = INPUT_KEYBOARD
                    inp_up.u.ki.wVk = 0
                    inp_up.u.ki.wScan = w
                    inp_up.u.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
                    inputs_list.append(inp_up)

        if inputs_list:
            _send_input_batch(inputs_list)

        # Brief delay between chunks to let target app message queue process input
        if len(chunks) > 1:
            time.sleep(max(0.02, delay_between_chars_s * min(len(chunk), 5)))

    return True


# ---------------------------------------------------------------------------
# Diagnostics & Self-Test CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("=" * 60)
    print("Yellow's Pixel Buddies — OS Interop Engine Self-Test")
    print("=" * 60)

    metrics = get_screen_metrics()
    print(f"Primary Screen Resolution: {metrics.primary_width}x{metrics.primary_height}")
    print(
        f"Virtual Desktop Bounds:    left={metrics.virtual_left}, top={metrics.virtual_top}, "
        f"size={metrics.virtual_width}x{metrics.virtual_height}"
    )

    cur_x, cur_y = get_cursor_pos()
    print(f"Current Cursor Position:   ({cur_x}, {cur_y})")

    fg = get_foreground_window()
    if fg:
        print(f"Foreground Window:         '{fg.title}' [{fg.process_name}] (PID: {fg.process_id})")
        print(f"Foreground Bounds:         {fg.bounds} (Center: {fg.center_x}, {fg.center_y})")

    print("\nListing Top Active Windows:")
    wins = list_windows(visible_only=True, exclude_cloaked=True)
    for i, w in enumerate(wins[:10], 1):
        print(f"  {i:2d}. [{w.process_name:18s}] {w.title[:45]} ({w.width}x{w.height})")

    print("\nSelf-test completed successfully.")
