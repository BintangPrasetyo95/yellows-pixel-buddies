"""Windows: make torch's DLL folder loadable BEFORE torch / PyQt5 / sounddevice are imported (plan 8.4).

This used to be copied in yellows_pixel_buddies.py and voice_service.py. Importing torch after PyQt5 or sounddevice
can fail with WinError 1114 (DLL initialisation), which is why the app still preloads torch early on purpose.
"""
from __future__ import annotations

import os
import site
import sys
from pathlib import Path

_DLL_HANDLES: list = []
_done = False


def torch_lib_dirs() -> list[Path]:
    paths: list[str] = []
    try:
        paths.extend(site.getsitepackages())
    except Exception:
        pass
    try:
        user_site = site.getusersitepackages()
        if user_site:
            paths.append(user_site)
    except Exception:
        pass
    return [p / "torch" / "lib" for p in map(Path, paths) if (p / "torch" / "lib").exists()]


def register_torch_dll_dirs() -> list:
    """Add every torch/lib folder to PATH and the DLL search path. Idempotent; returns the DLL handles."""
    global _done
    if _done or sys.platform != "win32":
        return _DLL_HANDLES
    _done = True
    for t_lib in torch_lib_dirs():
        try:
            os.environ["PATH"] = str(t_lib) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                _DLL_HANDLES.append(os.add_dll_directory(str(t_lib)))
        except Exception:
            pass
    return _DLL_HANDLES
