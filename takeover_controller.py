"""TakeoverController: the single owner of a Pink Takeover session (REVIEW M8, plan 5.1).

Before this, takeover state was spread over flags on the 20k-line pet widget (``_is_taking_over_cursor``,
``_confirm_pending``, the worker, the confirm token, the voice-HUD flag...), and five different places cleaned up,
each a little differently (H4, H9). Now:

* state is one value: IDLE -> RUNNING <-> AWAITING_CONFIRM -> STOPPING -> IDLE;
* ``start`` / ``abort`` / ``check_watchdog`` are the only ways in and out;
* ``_teardown`` is the ONLY place that resets takeover UI, and it runs exactly once per session;
* Pink's physics *listens* (``state_changed``, ``pink_action``) instead of deciding when a takeover ends.

The host is the pet widget. The controller uses only these parts of it: ``_memory``, ``_takeover_mode``,
``_phase``, ``_language``, ``_dialogue_overlay``, ``_voice_overlay``, ``_voice_mode_enabled``,
``_takeover_banner``, ``_target_reticle``, ``_question_token``, ``_decision_box_pos()`` and ``_say()``.
"""
from __future__ import annotations

import enum
import logging
import time
from typing import Any, Callable, Optional

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import QDialog, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

import action_planner
import os_interop
import takeover_gate

log = logging.getLogger("yellows_pixel_buddies.takeover_controller")

# Phases in which Pink cannot host a takeover; worker signals arriving then are ignored (REVIEW H9).
NO_TAKEOVER_PHASES = ("EXIT_OUTRO", "HIDE_OUTRO", "HIDE_PEEK")
STALL_TIMEOUT_S = 120.0   # no progress signal for this long while not waiting on the user -> watchdog abort


class TakeoverState(enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    AWAITING_CONFIRM = "awaiting_confirm"
    STOPPING = "stopping"


def _play_sound(name: str) -> None:
    try:
        import sound_manager
        sound_manager.play_sound(name)
    except Exception:
        pass


class TakeoverController(QObject):
    state_changed = pyqtSignal(object)                    # TakeoverState
    step_changed = pyqtSignal(int, int, str, str)         # (index, max_steps, action_type, target)
    pink_action = pyqtSignal(str, int, int)               # (anim, x, y): Pink's body follows the cursor
    confirm_requested = pyqtSignal(int, str, str, str, str, str)
    finished = pyqtSignal(bool, str)                      # (success, summary) of a plan that ran to its end

    def __init__(self, host: Any, worker_factory: Optional[Callable[..., Any]] = None, parent: Optional[QObject] = None,
                 abort_reaction: str = "laughing", stall_timeout_s: float = STALL_TIMEOUT_S):
        super().__init__(parent)
        self.host = host
        self.abort_reaction = abort_reaction       # Pink's reaction when the user ends a takeover early
        self.stall_timeout_s = stall_timeout_s
        self._max_steps = 0
        self._worker_factory = worker_factory or action_planner.DesktopActionWorkerThread
        self._state = TakeoverState.IDLE
        self.worker: Any = None
        self.latch: Optional[os_interop.PanicLatch] = None
        self.confirm_token = 0
        self.last_progress = 0.0
        self.last_reaction: Optional[str] = None     # what Pink should do as she lets go (read by the physics)
        self.voice_hud_hidden = False                # Voice HUD hidden for this session (REVIEW M5)
        self.text_viewer: Optional[QDialog] = None   # "Show all" view of a long confirmation payload (REVIEW M1)
        self.teardown_count = 0                      # sessions torn down (tests: exactly one per session)
        self._session_open = False

    # ------------------------------------------------------------------ state
    @property
    def state(self) -> TakeoverState:
        return self._state

    @property
    def is_active(self) -> bool:
        """A takeover owns the mouse/keyboard right now (RUNNING or AWAITING_CONFIRM)."""
        return self._state in (TakeoverState.RUNNING, TakeoverState.AWAITING_CONFIRM)

    @property
    def awaiting_confirm(self) -> bool:
        return self._state is TakeoverState.AWAITING_CONFIRM

    def _set_state(self, new: TakeoverState) -> None:
        if new is not self._state:
            log.debug("Takeover state %s -> %s", self._state.value, new.value)
            self._state = new
            self.state_changed.emit(new)

    def _touch(self) -> None:
        self.last_progress = time.perf_counter()

    # ------------------------------------------------------------------ start
    def start(self, action_data: dict, user_request: str = "") -> bool:
        """Start a closed-loop vision takeover. Returns True only if one actually started (REVIEW L3)."""
        h = self.host
        if h._takeover_mode == takeover_gate.TAKEOVER_MODE_OFF:
            log.info("Desktop takeover refused: Desktop Cursor Control is turned off.")
            return False
        if self._state is not TakeoverState.IDLE or (self.worker is not None and self.worker.isRunning()):
            log.warning("Another desktop action plan is already running.")
            return False
        if h._phase.name in NO_TAKEOVER_PHASES:
            log.warning("Desktop takeover refused during %s.", h._phase.name)
            return False

        api_key = h._memory.get_api_key() if getattr(h, "_memory", None) else ""
        intent = (action_data.get("intent") or action_data.get("target") or action_data.get("text")
                  or action_data.get("app") or user_request or "")
        if not intent and not user_request:
            return False

        plan = action_planner.create_desktop_plan(
            intent=intent,
            api_key=api_key,
            target_app=action_data.get("app") or "",
            user_request=user_request or intent,
            context_notes=self._recent_context(),
        )
        self.latch = os_interop.reset_panic_abort()            # a fresh latch for this session (plan 5.4)
        worker = self._worker_factory(plan, api_key=api_key, parent=h, latch=self.latch)
        self._open_session(worker, plan.max_steps)

        if getattr(h, "_takeover_banner", None) is not None:
            target_display = plan.target_app.upper() if plan.target_app else "DESKTOP"
            h._takeover_banner.show_banner(
                title=f"⚔️ PINK IN CONTROL — {target_display} (ESC OR SHAKE MOUSE TO ABORT)",
                subtitle=f"Inspecting screen for: {(user_request or intent)[:55]}...",
            )
        worker.start()
        return True

    def _recent_context(self) -> str:
        """Recent chat turns, so references like 'say the same thing I said to Arqan' work."""
        mem = getattr(self.host, "_memory", None)
        try:
            turns = list(mem.history)[-5:] if mem is not None else []
            return "\n".join(
                f"- User: {t.get('user', '')[:140]} | Pink: {t.get('pink', '')[:140]}"
                for t in turns if isinstance(t, dict) and t.get("user")
            )
        except Exception:
            return ""

    def _open_session(self, worker: Any, max_steps: int) -> None:
        """Adopt ``worker`` as this session's worker and take over the UI."""
        h = self.host
        self.worker = worker
        self._max_steps = max_steps
        self.confirm_token = 0
        self.last_reaction = None
        self._session_open = True
        self._touch()

        # Exclude Pink and her speech bubble from screenshots so she never blocks Gemini's vision
        os_interop.set_window_exclude_from_capture(h, True)
        if getattr(h, "_dialogue_overlay", None) is not None:
            os_interop.set_window_exclude_from_capture(h._dialogue_overlay, True)
        vo = getattr(h, "_voice_overlay", None)
        if vo is not None:
            os_interop.set_window_exclude_from_capture(vo, True)
        # The Voice HUD sits over browser tab strips: hide it (voice mode stays on) so clicks can't land on it.
        # It comes back for confirmations (voice yes/no) and when the takeover ends (REVIEW M5).
        self.voice_hud_hidden = bool(vo is not None and vo.isVisible())
        if self.voice_hud_hidden:
            vo.hide()
        h._question_token += 1   # no question may pop up mid-takeover (REVIEW M2)

        if hasattr(worker, "sig_step_started"):
            worker.sig_step_started.connect(self._on_step_started)
            worker.sig_pink_action.connect(self._on_pink_action)
            worker.sig_confirm_action.connect(self.show_confirmation)
            worker.sig_confirm_expired.connect(self._on_confirm_expired)
            worker.sig_plan_finished.connect(self._on_plan_finished)
        self._set_state(TakeoverState.RUNNING)   # Pink's physics latches onto the cursor on this signal

    # ------------------------------------------------------------------ worker signals
    def _signals_live(self) -> bool:
        return self.is_active and self.host._phase.name not in NO_TAKEOVER_PHASES

    def _on_step_started(self, idx: int, a_type: str, target: str) -> None:
        if not self.is_active:
            return
        self._touch()
        log.info("Desktop Action Step %d/%d: %s on '%s'", idx + 1, self._max_steps, a_type, target)
        if getattr(self.host, "_takeover_banner", None) is not None:
            self.host._takeover_banner.update_step(idx, self._max_steps, a_type, target)
        self.step_changed.emit(idx, self._max_steps, a_type, target)

    def _on_pink_action(self, anim: str, cx: int, cy: int) -> None:
        if not self._signals_live():
            return
        self._touch()
        if anim in ("move_to", "jump_to") and cx > 0 and cy > 0 and getattr(self.host, "_target_reticle", None) is not None:
            self.host._target_reticle.flash_at(cx, cy, duration_ms=420)
        self.pink_action.emit(anim, cx, cy)

    def _on_plan_finished(self, success: bool, msg: str) -> None:
        if not self.is_active:
            return
        log.info("Desktop Action Plan Finished: success=%s, msg='%s'", success, msg)
        self._teardown("peace_sign" if success else "angry")
        h = self.host
        if success:
            _play_sound("coin")
            clean = (msg or "Task finished").strip()
            if getattr(h, "_language", "en") == "id":
                h._say(f"* Beres semua, babu! ({clean[:65]}) [anim: peace_sign]", force=True, auto_dismiss=True)
            else:
                h._say(f"* All done, minion! ({clean[:65]}) [anim: peace_sign]", force=True, auto_dismiss=True)
        else:
            clean = (msg or "Something interrupted me").strip()
            h._say(f"* Hmph! {clean[:75]} [anim: angry]", force=True, auto_dismiss=True)
        self.finished.emit(success, msg)

    # ------------------------------------------------------------------ confirmation (REVIEW C2, M1, M2, M5, H2)
    def show_confirmation(self, token: int, a_type: str, target: str, text: str, win_title: str, proc_name: str) -> None:
        """Ask the user to approve one sensitive step (worker signal sig_confirm_action).

        Shows the FULL text that will be typed (newlines as ⏎, plus its length) with a "Show all" view for long
        payloads, defaults to Cancel, ignores input until it has typed out, and answers with the request's token
        so a late click can never approve a different step.
        """
        h = self.host
        if not self.is_active:
            if self.worker is not None:
                self.worker.deliver_confirmation(token, False)
            return
        self.confirm_token = token
        self._touch()
        self._set_state(TakeoverState.AWAITING_CONFIRM)
        self.confirm_requested.emit(token, a_type, target, text, win_title, proc_name)
        log.info("Desktop Takeover confirmation #%d requested for '%s' on '%s' (text=%r, window='%s' [%s])",
                 token, a_type, target, text, win_title, proc_name)

        is_id = getattr(h, "_language", "en") == "id"
        long_text = bool(text) and len(text) > 280
        if text:
            shown = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ⏎ ")
            if len(shown) > 280:
                more = len(shown) - 280
                shown = shown[:280] + (f" …(+{more} karakter lagi!)" if is_id else f" …(+{more} more chars!)")
            unit = "karakter" if is_id else "chars"
            detail = f"\"{shown}\" ({len(text)} {unit})"
        else:
            detail = target or a_type
        app_display = proc_name or win_title or ("jendela ini" if is_id else "this window")
        action_clean = a_type.replace("_", " ")

        if is_id:
            question_text = f"* Babu! Aku bakal {action_clean}:\n* {detail}\n* di {app_display}. Lanjutkan?"
            choices = [("Lanjut", "* Siap laksanakan, babu! [anim: peace_sign]", "peace_sign"),
                       ("Batal", "* Hmph! Dibatalkan! [anim: angry]", "angry")]
            banner_title = "⚠️ BUTUH KONFIRMASI — [Y: Lanjut]  [ENTER/ESC/N: Batal]"
            banner_sub = f"Konfirmasi {action_clean} di {app_display} (atau klik opsi di bawah)..."
        else:
            question_text = f"* Minion! I'm about to {action_clean}:\n* {detail}\n* in {app_display}. Proceed?"
            choices = [("Proceed", "* Right away, minion! [anim: peace_sign]", "peace_sign"),
                       ("Cancel", "* Hmph! Canceled! [anim: angry]", "angry")]
            banner_title = "⚠️ CONFIRMATION REQUIRED — [Y: Proceed]  [ENTER/ESC/N: Cancel]"
            banner_sub = f"Confirm {a_type} in {app_display} (or click option below)..."
        show_all_label = "Lihat semua" if is_id else "Show all"
        if long_text:
            choices.append((show_all_label, "", None))

        if getattr(h, "_takeover_banner", None) is not None:
            h._takeover_banner.show_banner(title=banner_title, subtitle=banner_sub, is_confirmation=True)

        def _on_chosen(choice_label: str, _reaction_text: str, _reaction_anim: str) -> None:
            if self.confirm_token != token:
                return  # superseded or expired prompt
            if choice_label == show_all_label:
                self._show_text_viewer(text, app_display, is_id)
                self.show_confirmation(token, a_type, target, text, win_title, proc_name)   # ask again
                return
            # Close the bubble before the worker resumes, so it doesn't keep focus or sit over the target (REVIEW H2).
            h._dialogue_overlay.dismiss(clear_queue=True)
            self.confirm(token, choice_label in ("Proceed", "Lanjut"))

        def _on_cancel() -> None:
            # The prompt was closed without an answer: that's a NO, said now instead of after the timeout (REVIEW M2).
            if self.confirm_token == token:
                log.info("Takeover confirmation #%d closed without an answer: denying.", token)
                self.confirm(token, False)

        fixed_x, fixed_y = h._decision_box_pos()
        h._dialogue_overlay.ask(
            question_text, choices, fixed_x, fixed_y, on_chosen=_on_chosen, track_ignore=False, fixed=True,
            fixed_pos=(fixed_x, fixed_y), default_idx=1, arm_delay_s=0.6, on_cancel=_on_cancel,
        )
        vo = getattr(h, "_voice_overlay", None)
        if self.voice_hud_hidden and getattr(h, "_voice_mode_enabled", False) and vo is not None:
            vo.show_overlay()   # only while the decision is pending, so the user can say yes/no (REVIEW M5)

    def confirm(self, token: int, approved: bool) -> None:
        """Deliver the user's answer for confirmation ``token`` and resume the plan."""
        if token != self.confirm_token:
            return
        self._end_confirmation()
        if self.worker is not None:
            self.worker.deliver_confirmation(token, approved)

    def _end_confirmation(self) -> None:
        self.confirm_token = 0
        self._close_text_viewer()
        self._hide_voice_hud()
        if getattr(self.host, "_takeover_banner", None) is not None:
            self.host._takeover_banner.restore_base_title()
        self._touch()
        if self._state is TakeoverState.AWAITING_CONFIRM:
            self._set_state(TakeoverState.RUNNING)

    def _on_confirm_expired(self, token: int) -> None:
        """The worker stopped waiting for confirmation ``token``: drop the stale prompt (REVIEW M1)."""
        if token != self.confirm_token:
            return
        log.info("Takeover confirmation #%d expired without an answer.", token)
        self._end_confirmation()
        if self.host._dialogue_overlay.has_pending_fixed_decision():
            self.host._dialogue_overlay.dismiss(clear_queue=True)

    def _show_text_viewer(self, text: str, app_display: str, is_id: bool) -> None:
        """Read-only, scrollable view of the full text Pink is asking to type (REVIEW M1)."""
        self._close_text_viewer()
        dlg = QDialog(None, Qt.Window | Qt.WindowStaysOnTopHint)
        dlg.setWindowTitle(f"Teks lengkap untuk {app_display}" if is_id else f"Full text Pink will type into {app_display}")
        lay = QVBoxLayout(dlg)
        box = QPlainTextEdit(dlg)
        box.setReadOnly(True)
        box.setPlainText(text)
        lay.addWidget(QLabel((f"{len(text)} karakter. Tutup ini, lalu pilih Lanjut atau Batal." if is_id
                              else f"{len(text)} characters. Close this, then choose Proceed or Cancel."), dlg))
        lay.addWidget(box)
        close_btn = QPushButton("Tutup" if is_id else "Close", dlg)
        close_btn.clicked.connect(dlg.close)
        lay.addWidget(close_btn)
        dlg.resize(560, 360)
        dlg.show()
        self.text_viewer = dlg

    def _close_text_viewer(self) -> None:
        dlg, self.text_viewer = self.text_viewer, None
        if dlg is not None:
            try:
                dlg.close()
                dlg.deleteLater()
            except RuntimeError:
                pass

    def _hide_voice_hud(self) -> None:
        vo = getattr(self.host, "_voice_overlay", None)
        if self.voice_hud_hidden and vo is not None and vo.isVisible():
            vo.hide()

    # ------------------------------------------------------------------ ending
    def abort(self, reason: str = "Aborted by user", announce: bool = True) -> None:
        """End the session NOW from the UI thread: stop the worker, then tear down once.

        Every early ending (Esc/shake, watchdog, exit, hide, quit, reset, mode switched off) comes through here
        (REVIEW H4, H9). Safe to call any number of times.
        """
        worker = self.worker
        if not self.is_active and not (worker is not None and worker.isRunning()):
            return
        log.warning("Immediate UI-thread abort of desktop cursor takeover: %s", reason)
        if self.latch is not None:
            self.latch.trigger()
        os_interop.trigger_panic_abort()
        if worker is not None:
            for name in ("sig_step_started", "sig_pink_action", "sig_plan_finished", "sig_confirm_action", "sig_confirm_expired"):
                sig = getattr(worker, name, None)
                if sig is not None:
                    try:
                        sig.disconnect()
                    except Exception:
                        pass
            worker.abort()
        self._teardown(self.abort_reaction if announce else None)
        if announce:
            self.host._say("* W-wah?! Okay, okay! I let go of your mouse, minion! [anim: shocked]",
                           force=True, auto_dismiss=True)

    def check_watchdog(self, now: float) -> bool:
        """Called from Pink's hang tick. Aborts (and returns True) if the worker is gone or has stalled (REVIEW H4)."""
        if not self.is_active:
            return False
        worker = self.worker
        alive = worker is not None and worker.isRunning()
        stalled = (now - self.last_progress) > self.stall_timeout_s and not self.awaiting_confirm
        if alive and not stalled:
            return False
        log.warning("Takeover watchdog: %s. Aborting it.", "stalled" if alive else "worker gone")
        self.abort("Takeover watchdog", announce=alive)
        return True

    def _teardown(self, reaction: Optional[str]) -> None:
        """The ONLY place that resets takeover UI. Idempotent: a session is torn down exactly once."""
        if not self._session_open:
            return
        self._session_open = False
        self.teardown_count += 1
        h = self.host
        self._set_state(TakeoverState.STOPPING)
        if self.confirm_token and h._dialogue_overlay.has_pending_fixed_decision():
            h._dialogue_overlay.dismiss(clear_queue=True)
        self.confirm_token = 0
        self._close_text_viewer()
        if self.voice_hud_hidden:
            self.voice_hud_hidden = False
            vo = getattr(h, "_voice_overlay", None)
            if vo is not None and getattr(h, "_voice_mode_enabled", False):
                vo.show_overlay()
        os_interop.set_window_exclude_from_capture(h, False)
        if getattr(h, "_dialogue_overlay", None) is not None:
            os_interop.set_window_exclude_from_capture(h._dialogue_overlay, False)
        if getattr(h, "_voice_overlay", None) is not None:
            os_interop.set_window_exclude_from_capture(h._voice_overlay, False)
        if getattr(h, "_takeover_banner", None) is not None:
            h._takeover_banner.dismiss()
        if getattr(h, "_target_reticle", None) is not None:
            h._target_reticle.dismiss()
        self.last_reaction = reaction
        self._set_state(TakeoverState.IDLE)   # Pink's physics lets go of the cursor on this signal
