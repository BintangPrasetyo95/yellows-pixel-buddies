"""Shared pytest setup for Pink Here.

Everything at module level here runs BEFORE any test module is imported, which matters because
``yellows_pixel_buddies`` resolves ``USER_DATA_DIR`` and builds Qt objects at import time:

* ``PINK_DATA_DIR`` points at a throwaway folder, so no test can read or write the developer's
  real ``memory/`` folder or ``.env`` (review finding T2).
* ``QT_QPA_PLATFORM=offscreen`` keeps every widget headless (CI has no usable display).
* ``GEMINI_API_KEY`` is removed so nothing can reach the real Gemini API by accident.

Markers (see pyproject.toml):
  desktop  - touches the real screen, windows, cursor or keyboard. Excluded in CI; run locally
             with ``pytest -m desktop`` only when nothing important has focus.
  slow     - builds the full pet widget or otherwise takes seconds.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GOOGLE_API_KEY", None)

_SESSION_DATA_DIR = Path(tempfile.mkdtemp(prefix="pink_test_data_"))
os.environ["PINK_DATA_DIR"] = str(_SESSION_DATA_DIR)


def pytest_unconfigure(config: pytest.Config) -> None:
    shutil.rmtree(_SESSION_DATA_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def qapp():
    """One shared offscreen QApplication for tests that build widgets."""
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["pink-tests", "-platform", "offscreen"])
    yield app


@pytest.fixture
def mem(tmp_path: Path):
    """A MemoryManager in an empty temp folder with migration disabled (no real memory/.env copied)."""
    from yellows_pixel_buddies import MemoryManager

    return MemoryManager(tmp_path)


@pytest.fixture
def fake_os_interop(monkeypatch: pytest.MonkeyPatch):
    """Replace ``action_planner.os_interop`` with a recorder so executor tests never move the real mouse.

    Returns the fake; inspect ``fake.calls`` for the input that *would* have been sent.
    """
    import action_planner

    from tests.fakes import FakeOsInterop

    fake = FakeOsInterop()
    monkeypatch.setattr(action_planner, "os_interop", fake)
    return fake


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch):
    """Make ``time.sleep`` inside action_planner instant (the executor sleeps between every step)."""
    import action_planner

    monkeypatch.setattr(action_planner.time, "sleep", lambda *_a, **_k: None)


def shutdown_pet(pet) -> None:
    """Stop every QThread the pet started (e.g. MediaWatcher) before the process exits.

    A QThread still running when Python shuts down makes Qt abort the process, which kills pytest before it can
    print its summary. The app itself has the same gap at quit (REVIEW H13, fixed in Phase 2); until then every
    test that builds the full pet must tear it down with this.
    """
    from PyQt5.QtCore import QThread

    for thread in pet.findChildren(QThread):
        if thread.isRunning():
            if hasattr(thread, "stop"):
                thread.stop()
            thread.requestInterruption()
            thread.wait(5000)
    pet.hide()
