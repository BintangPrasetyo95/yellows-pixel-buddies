"""takeover_overlay.py - Retro Deltarune-styled Visual HUD Overlays for Desktop Takeover.

Part of Yellow's Pixel Buddies / Pink desktop companion.
Provides:
- TakeoverBannerOverlay: Floating top-centered HUD banner indicating Pink is in control,
  showing the active step and reminding the user of the Emergency Esc killswitch.
- TargetReticleOverlay: High-precision targeting reticle flashing over elements
  before Pink clicks them.
All overlays are non-blocking, layered, and click-through (WS_EX_TRANSPARENT).
"""

from __future__ import annotations

import logging
import math
import sys
import time
from typing import Optional, Tuple

try:
    from PyQt5.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
    from PyQt5.QtGui import QBrush, QColor, QCursor, QFont, QFontMetrics, QImage, QPainter, QPen, QPixmap, QRegion
    from PyQt5.QtWidgets import QApplication, QWidget
    HAS_PYQT = True
except Exception:
    HAS_PYQT = False

import os_interop

log = logging.getLogger("yellows_pixel_buddies.takeover_overlay")


if HAS_PYQT:
    class TakeoverBannerOverlay(QWidget):
        """Floating top-centered HUD banner indicating autonomous desktop takeover."""

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            flags = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
            if hasattr(Qt, "WindowTransparentForInput"):
                flags |= Qt.WindowTransparentForInput
            super().__init__(None, flags)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

            self._title = "⚔️ PINK IN CONTROL — PRESS ESC TO ABORT"
            self._subtitle = "Preparing desktop action..."
            self._pulse_tick = 0.0
            self._pulse_timer = QTimer(self)
            self._pulse_timer.setInterval(30)
            self._pulse_timer.timeout.connect(self._on_pulse)

            self._scale = 1.0
            self._font_family = "Determination Sans"
            self.resize(520, 68)

        def set_font_family(self, family: str) -> None:
            """Set typography family."""
            self._font_family = family
            self.update()

        def show_banner(self, title: Optional[str] = None, subtitle: str = "") -> None:
            """Display the takeover HUD centered near the top of the active screen."""
            if title:
                self._title = title
            self._subtitle = subtitle
            self._pulse_tick = 0.0
            self._pulse_timer.start()

            # Center at top of active screen containing cursor, with primaryScreen fallback
            screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
            if screen:
                geom = screen.geometry()
                x = geom.x() + (geom.width() - self.width()) // 2
                y = geom.y() + 24
                self.move(x, y)

            self.show()
            self.raise_()
            os_interop.set_window_input_transparent(self, True)
            os_interop.set_window_exclude_from_capture(self, True)
            self.update()

        def update_step(self, step_idx: int, total_steps: int, action_type: str, target: str) -> None:
            """Update status text showing active automation progress."""
            type_clean = action_type.replace("_", " ").title()
            if target:
                self._subtitle = f"Step {step_idx + 1}/{total_steps}: {type_clean} on '{target}'..."
            else:
                self._subtitle = f"Step {step_idx + 1}/{total_steps}: {type_clean}..."
            self.update()

        def dismiss(self) -> None:
            """Hide and deactivate the HUD banner."""
            self._pulse_timer.stop()
            self.hide()

        def _on_pulse(self) -> None:
            self._pulse_tick += 0.08
            self.update()

        def paintEvent(self, event) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)

            w = self.width()
            h = self.height()
            rect = QRectF(2, 2, w - 4, h - 4)

            # Background: Dark translucent Deltarune purple-black
            bg_color = QColor(13, 15, 24, 230)
            painter.setBrush(QBrush(bg_color))

            # Pulsing Neon Pink / Magenta border
            # Alpha oscillates between 180 and 255
            pulse_factor = 0.5 + 0.5 * math.sin(self._pulse_tick)
            border_alpha = int(180 + 75 * pulse_factor)
            border_color = QColor(255, 42, 133, border_alpha)

            pen = QPen(border_color, 2.0)
            painter.setPen(pen)
            painter.drawRoundedRect(rect, 8.0, 8.0)

            # Inner subtle accent line
            inner_rect = QRectF(5, 5, w - 10, h - 10)
            painter.setPen(QPen(QColor(255, 255, 255, 35), 1.0))
            painter.drawRoundedRect(inner_rect, 6.0, 6.0)

            # Title Text
            font_title = QFont(self._font_family, 12, QFont.Bold)
            font_title.setStyleStrategy(QFont.PreferAntialias)
            painter.setFont(font_title)
            painter.setPen(QColor(255, 255, 255, 245))
            title_rect = QRectF(12, 10, w - 24, 24)
            painter.drawText(title_rect, Qt.AlignCenter, self._title)

            # Subtitle Text (Step status with font elision to prevent frame overflow)
            font_sub = QFont(self._font_family, 10, QFont.Normal)
            painter.setFont(font_sub)
            painter.setPen(QColor(255, 180, 215, 225))
            sub_rect = QRectF(12, 34, w - 24, 22)
            fm = painter.fontMetrics()
            elided_sub = fm.elidedText(self._subtitle, Qt.ElideRight, int(sub_rect.width()))
            painter.drawText(sub_rect, Qt.AlignCenter, elided_sub)

            painter.end()


    class TargetReticleOverlay(QWidget):
        """Animated retro targeting reticle flashing over an element prior to automated clicks."""

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            flags = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
            if hasattr(Qt, "WindowTransparentForInput"):
                flags |= Qt.WindowTransparentForInput
            super().__init__(None, flags)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

            self._size = 80
            self.setFixedSize(self._size, self._size)

            # Punch a 28x28 hole in the exact center so clicks at (center_x, center_y) NEVER hit this window
            outer_region = QRegion(0, 0, self._size, self._size)
            hole_half = 14
            mid = self._size // 2
            center_hole = QRegion(mid - hole_half, mid - hole_half, hole_half * 2, hole_half * 2)
            self.setMask(outer_region.subtracted(center_hole))

            self._progress = 0.0  # 0.0 -> 1.0
            self._anim_timer = QTimer(self)
            self._anim_timer.setInterval(20)
            self._anim_timer.timeout.connect(self._on_tick)

        def flash_at(self, center_x: int, center_y: int, duration_ms: int = 260) -> None:
            """Center and animate reticle over physical (center_x, center_y) coordinates."""
            self._progress = 0.0
            half = self._size // 2

            # Map physical desktop coordinates to Qt logical widget coordinates across monitors
            target_screen = None
            for scr in QApplication.screens():
                dpr = scr.devicePixelRatio() if hasattr(scr, "devicePixelRatio") else 1.0
                geom = scr.geometry()
                phys_x = geom.x() * dpr
                phys_y = geom.y() * dpr
                phys_w = geom.width() * dpr
                phys_h = geom.height() * dpr
                if phys_x <= center_x <= phys_x + phys_w and phys_y <= center_y <= phys_y + phys_h:
                    target_screen = scr
                    break

            if target_screen:
                dpr = target_screen.devicePixelRatio() if hasattr(target_screen, "devicePixelRatio") else 1.0
                geom = target_screen.geometry()
                log_x = geom.x() + (center_x - geom.x() * dpr) / dpr
                log_y = geom.y() + (center_y - geom.y() * dpr) / dpr
                self.move(int(round(log_x - half)), int(round(log_y - half)))
            else:
                self.move(center_x - half, center_y - half)

            total_ticks = max(4, duration_ms // 20)
            self._tick_step = 1.0 / total_ticks

            self.show()
            self.raise_()
            os_interop.set_window_input_transparent(self, True)
            os_interop.set_window_exclude_from_capture(self, True)
            self._anim_timer.start()
            self.update()

        def dismiss(self) -> None:
            """Hide reticle."""
            self._anim_timer.stop()
            self.hide()

        def _on_tick(self) -> None:
            self._progress += getattr(self, "_tick_step", 0.05)
            if self._progress >= 1.0:
                self.dismiss()
            else:
                self.update()

        def paintEvent(self, event) -> None:
            if not self.isVisible() or self._progress >= 1.0:
                return

            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)

            mid = self._size / 2.0
            # Brackets converge inward: radius shrinks from 34px to 18px (leaving the center 28x28 hole clear)
            ease = 1.0 - math.pow(1.0 - min(1.0, self._progress), 3)
            radius = 34.0 - (16.0 * ease)

            # Opacity fades near end of animation
            alpha = int(255 * (1.0 - max(0.0, (self._progress - 0.6) / 0.4)))
            bracket_color = QColor(255, 42, 133, alpha)
            pen = QPen(bracket_color, 2.5)
            painter.setPen(pen)

            arm = 8.0
            # Top-Left Bracket ┌
            painter.drawLine(int(mid - radius), int(mid - radius), int(mid - radius + arm), int(mid - radius))
            painter.drawLine(int(mid - radius), int(mid - radius), int(mid - radius), int(mid - radius + arm))

            # Top-Right Bracket ┐
            painter.drawLine(int(mid + radius), int(mid - radius), int(mid + radius - arm), int(mid - radius))
            painter.drawLine(int(mid + radius), int(mid - radius), int(mid + radius), int(mid - radius + arm))

            # Bottom-Left Bracket └
            painter.drawLine(int(mid - radius), int(mid + radius), int(mid - radius + arm), int(mid + radius))
            painter.drawLine(int(mid - radius), int(mid + radius), int(mid - radius), int(mid + radius - arm))

            # Bottom-Right Bracket ┘
            painter.drawLine(int(mid + radius), int(mid + radius), int(mid + radius - arm), int(mid + radius))
            painter.drawLine(int(mid + radius), int(mid + radius), int(mid + radius), int(mid + radius - arm))

            painter.end()


    class VoiceModeOverlay(QWidget):
        """Floating retro Deltarune-styled HUD for Voice Push-to-Talk Desktop Takeover mode."""

        sig_voice_submitted = pyqtSignal(str)
        sig_dismissed = pyqtSignal()

        def __init__(self, voice_manager: Optional[object] = None, parent: Optional[QWidget] = None) -> None:
            flags = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            super().__init__(None, flags)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setFocusPolicy(Qt.StrongFocus)

            self._font_family = "Determination Sans"
            self._voice_manager = voice_manager
            self._language = "en"
            self._state = "idle"  # "idle", "listening", "transcribing", "dispatched", "error"
            self._title = "🎙️ VOICE MODE [SPACE]"
            self._subtitle = "[ HOLD SPACE TO SPEAK ]  •  [ESC to exit]"
            self._audio_level = 0.0
            self._pulse_tick = 0.0
            self._drag_pos: Optional[QPoint] = None

            self._pulse_timer = QTimer(self)
            self._pulse_timer.setInterval(33)  # ~30 fps
            self._pulse_timer.timeout.connect(self._on_pulse)

            self._reset_timer = QTimer(self)
            self._reset_timer.setSingleShot(True)
            self._reset_timer.timeout.connect(self._reset_to_idle)

            self.resize(500, 74)
            self._dialogue_ref: Optional[object] = None
            self._connect_voice_manager()

        def set_font_family(self, family: str) -> None:
            self._font_family = family
            self.update()

        def set_language(self, lang: str) -> None:
            """Update language for Voice Mode HUD titles and status messages ('en' or 'id')."""
            self._language = lang if lang in ("en", "id") else "en"
            if self._state == "idle":
                self._reset_to_idle()

        def _get_localized_text(self, key: str) -> Tuple[str, str]:
            is_id = getattr(self, "_language", "en") == "id"
            if is_id:
                texts = {
                    "idle": ("🎙️ MODE SUARA [SPASI]", "[ TAHAN SPASI UNTUK BICARA ]  •  [ESC untuk keluar]"),
                    "listening": ("💓 MENDENGARKAN... (DOKI-METER AKTIF)", "[ Lepas SPASI untuk kirim perintah ]"),
                    "transcribing": ("⚡ MENERJEMAHKAN SUARA...", "[ Menerjemahkan suara untuk Pink... ]"),
                    "dispatched": ("⚔️ PERINTAH DIKIRIM KE PINK!", ""),
                    "no_speech": ("🎙️ TIDAK ADA SUARA TERDETEKSI", "[ Tahan SPASI dan bicara dengan jelas ]"),
                    "error": ("⚠️ SUARA ERROR", ""),
                }
            else:
                texts = {
                    "idle": ("🎙️ VOICE MODE [SPACE]", "[ HOLD SPACE TO SPEAK ]  •  [ESC to exit]"),
                    "listening": ("💓 LISTENING... (DOKI-METER ACTIVE)", "[ Release SPACE to send command ]"),
                    "transcribing": ("⚡ TRANSCRIBING AUDIO...", "[ Translating voice command for Pink... ]"),
                    "dispatched": ("⚔️ COMMAND DISPATCHED TO PINK!", ""),
                    "no_speech": ("🎙️ NO SPEECH DETECTED", "[ Hold SPACE firmly and speak clearly ]"),
                    "error": ("⚠️ VOICE ERROR", ""),
                }
            return texts.get(key, ("", ""))

        def set_dialogue_ref(self, dlg: object) -> None:
            """Link reference to dialogue overlay to forward decision keystrokes."""
            self._dialogue_ref = dlg

        def set_voice_manager(self, vm: object) -> None:
            self._voice_manager = vm
            self._connect_voice_manager()

        def _connect_voice_manager(self) -> None:
            if self._voice_manager is None:
                return
            try:
                self._voice_manager.sig_audio_level.connect(self._on_audio_level)
                self._voice_manager.sig_transcription_started.connect(self._on_transcription_started)
                self._voice_manager.sig_transcription_finished.connect(self._on_transcription_finished)
                self._voice_manager.sig_transcription_error.connect(self._on_transcription_error)
            except Exception as exc:
                log.warning("Could not connect voice manager signals: %s", exc)

        def show_overlay(self) -> None:
            """Display the Voice Mode HUD centered near the top of the active screen."""
            self._state = "idle"
            self._title, self._subtitle = self._get_localized_text("idle")
            self._pulse_tick = 0.0
            self._pulse_timer.start()

            screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
            if screen:
                geom = screen.geometry()
                x = geom.x() + (geom.width() - self.width()) // 2
                y = geom.y() + 40
                self.move(x, y)

            self.show()
            self.raise_()
            self.activateWindow()
            self.setFocus()
            self.update()

        def dismiss(self) -> None:
            """Hide and deactivate Voice Mode HUD."""
            self._pulse_timer.stop()
            self._reset_timer.stop()
            if self._voice_manager and getattr(self._voice_manager, "is_recording", lambda: False)():
                try:
                    self._voice_manager.stop_recording()
                except Exception:
                    pass
            self.hide()
            self.sig_dismissed.emit()

        def _on_pulse(self) -> None:
            self._pulse_tick += 0.08
            self.update()

        def _on_audio_level(self, level: float) -> None:
            self._audio_level = max(0.0, min(1.0, level))
            if self._state == "listening":
                self.update()

        def _on_transcription_started(self) -> None:
            self._state = "transcribing"
            self._title, self._subtitle = self._get_localized_text("transcribing")
            self.update()

        def _on_transcription_finished(self, text: str) -> None:
            clean_text = text.strip()
            if not clean_text:
                self._state = "idle"
                self._title, self._subtitle = self._get_localized_text("no_speech")
                self.update()
                self._reset_timer.start(2500)
                return

            self._state = "dispatched"
            t, _ = self._get_localized_text("dispatched")
            self._title = t
            disp_text = clean_text[:50] + "..." if len(clean_text) > 50 else clean_text
            self._subtitle = f"\"{disp_text}\""
            self.update()
            self.sig_voice_submitted.emit(clean_text)
            self._reset_timer.start(3500)

        def _on_transcription_error(self, err_msg: str) -> None:
            self._state = "error"
            t, _ = self._get_localized_text("error")
            self._title = t
            self._subtitle = f"[{err_msg[:45]}]"
            self.update()
            self._reset_timer.start(3000)

        def _reset_to_idle(self) -> None:
            if not self.isVisible():
                return
            self._state = "idle"
            self._title, self._subtitle = self._get_localized_text("idle")
            self._audio_level = 0.0
            self.update()

        def keyPressEvent(self, event) -> None:
            # If Pink's dialogue overlay is actively presenting choices, forward decision keys directly
            if self._dialogue_ref and getattr(self._dialogue_ref, "has_active_choices", lambda: False)():
                if event.key() in (
                    Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Tab,
                    Qt.Key_Return, Qt.Key_Enter, Qt.Key_Z,
                    Qt.Key_Y, Qt.Key_N, Qt.Key_Escape,
                    Qt.Key_1, Qt.Key_2, Qt.Key_3, Qt.Key_4
                ):
                    try:
                        self._dialogue_ref.keyPressEvent(event)
                        event.accept()
                        return
                    except Exception as exc:
                        log.debug("Error forwarding key to dialogue overlay: %s", exc)

            if event.key() == Qt.Key_Escape:
                event.accept()
                self.dismiss()
                return

            if event.key() == Qt.Key_Space:
                if event.isAutoRepeat():
                    event.accept()
                    return
                if self._state in ("idle", "error"):
                    self._state = "listening"
                    self._title, self._subtitle = self._get_localized_text("listening")
                    self.update()
                    if self._voice_manager:
                        self._voice_manager.start_recording()
                event.accept()
                return

            super().keyPressEvent(event)

        def keyReleaseEvent(self, event) -> None:
            if event.key() == Qt.Key_Space:
                if event.isAutoRepeat():
                    event.accept()
                    return
                if self._state == "listening":
                    self._state = "transcribing"
                    self._title, self._subtitle = self._get_localized_text("transcribing")
                    self.update()
                    if self._voice_manager:
                        self._voice_manager.stop_recording()
                event.accept()
                return

            super().keyReleaseEvent(event)

        def mousePressEvent(self, event) -> None:
            if event.button() == Qt.LeftButton:
                # Check top-right close [X] button (width - 32, 8, 24, 24)
                if event.pos().x() >= self.width() - 36 and event.pos().y() <= 32:
                    event.accept()
                    self.dismiss()
                    return
                self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
                self.setFocus()
                event.accept()
            else:
                super().mousePressEvent(event)

        def mouseMoveEvent(self, event) -> None:
            if getattr(self, "_drag_pos", None) and event.buttons() == Qt.LeftButton:
                self.move(event.globalPos() - self._drag_pos)
                event.accept()
            else:
                super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event) -> None:
            self._drag_pos = None
            super().mouseReleaseEvent(event)

        def _draw_soul_heart(self, painter: QPainter, x: int, y: int, scale: int = 3) -> None:
            grid = [
                " 11   11 ",
                "1111 1111",
                "111111111",
                "111111111",
                " 1111111 ",
                "  11111  ",
                "   111   ",
                "    1    ",
            ]
            if self._state == "listening":
                # Pulse dynamically with live microphone audio level + timer tick
                pulse = (math.sin(self._pulse_tick * 3.0) + 1.0) / 2.0
                level_boost = min(1.0, self._audio_level * 1.5)
                r = int(255 * (1.0 - level_boost * 0.4))
                g = int(30 + level_boost * 220)
                b = int(100 + pulse * 140)
                color = QColor(r, g, b)
            elif self._state == "transcribing":
                color = QColor(0, 255, 255)  # Cyan
            elif self._state == "dispatched":
                color = QColor(0, 255, 128)  # Retro Green
            elif self._state == "error":
                color = QColor(255, 140, 0)  # Orange
            else:
                color = QColor(255, 0, 64)   # Iconic Undertale Red

            painter.save()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            for row_idx, row in enumerate(grid):
                for col_idx, ch in enumerate(row):
                    if ch == "1":
                        painter.drawRect(x + col_idx * scale, y + row_idx * scale, scale, scale)
            painter.restore()

        def paintEvent(self, event) -> None:
            if not self.isVisible():
                return

            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            w = self.width()
            h = self.height()

            # Translucent dark body
            bg_color = QColor(10, 10, 18, 235)
            painter.setBrush(QBrush(bg_color))

            # Outer border: cyan when recording, white otherwise
            border_color = QColor(0, 255, 255) if self._state == "listening" else QColor(255, 255, 255)
            painter.setPen(QPen(border_color, 2.0))
            painter.drawRoundedRect(1, 1, w - 2, h - 2, 6, 6)

            # Inner subtle accent border
            painter.setPen(QPen(QColor(50, 50, 75, 180), 1.0))
            painter.drawRoundedRect(4, 4, w - 8, h - 8, 4, 4)

            # Draw Soul Heart on left
            heart_y = (h - 24) // 2
            self._draw_soul_heart(painter, 18, heart_y, scale=3)

            # If recording, draw live audio waveform bounce bars
            if self._state == "listening":
                painter.save()
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(0, 255, 255, 220)))
                bar_count = 5
                base_x = 54
                center_y = h // 2
                for i in range(bar_count):
                    # Combine audio RMS level with sine jitter
                    offset = math.sin(self._pulse_tick * 4.0 + i * 1.2) * 0.3
                    bar_h = max(4, int((self._audio_level + offset) * 22))
                    painter.drawRect(base_x + i * 5, center_y - bar_h // 2, 3, bar_h)
                painter.restore()

            # Text block
            text_x = 88 if self._state == "listening" else 58
            font = QFont(self._font_family)
            font.setPixelSize(15)
            font.setBold(True)
            painter.setFont(font)
            title_color = QColor(255, 255, 255) if self._state != "listening" else QColor(0, 255, 255)
            painter.setPen(title_color)
            painter.drawText(text_x, 28, self._title)

            font.setPixelSize(12)
            font.setBold(False)
            painter.setFont(font)
            sub_color = QColor(200, 200, 220) if self._state != "error" else QColor(255, 180, 100)
            painter.setPen(sub_color)
            painter.drawText(text_x, 50, self._subtitle)

            # Close button [X]
            painter.setFont(QFont(self._font_family, 12, QFont.Bold))
            painter.setPen(QPen(QColor(160, 160, 180), 1.5))
            painter.drawText(w - 26, 24, "✕")

            painter.end()
else:
    class TakeoverBannerOverlay:
        pass

    class TargetReticleOverlay:
        pass

    class VoiceModeOverlay:
        pass
