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
    from PyQt5.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer
    from PyQt5.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap
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
            super().__init__(
                None,
                Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus,
            )
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
            """Display the takeover HUD centered near the top of the primary screen."""
            if title:
                self._title = title
            self._subtitle = subtitle
            self._pulse_tick = 0.0
            self._pulse_timer.start()

            # Center at top of active screen with 24px margin
            screen = QApplication.primaryScreen()
            if screen:
                geom = screen.geometry()
                x = geom.x() + (geom.width() - self.width()) // 2
                y = geom.y() + 24
                self.move(x, y)

            self.show()
            self.raise_()
            os_interop.set_window_input_transparent(self, True)
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

            # Subtitle Text (Step status)
            font_sub = QFont(self._font_family, 10, QFont.Normal)
            painter.setFont(font_sub)
            painter.setPen(QColor(255, 180, 215, 225))
            sub_rect = QRectF(12, 34, w - 24, 22)
            painter.drawText(sub_rect, Qt.AlignCenter, self._subtitle)

            painter.end()


    class TargetReticleOverlay(QWidget):
        """Animated retro targeting reticle flashing over an element prior to automated clicks."""

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(
                None,
                Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus,
            )
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

            self._size = 80
            self.setFixedSize(self._size, self._size)

            self._progress = 0.0  # 0.0 -> 1.0
            self._anim_timer = QTimer(self)
            self._anim_timer.setInterval(20)
            self._anim_timer.timeout.connect(self._on_tick)

        def flash_at(self, center_x: int, center_y: int, duration_ms: int = 350) -> None:
            """Center and animate reticle over (center_x, center_y)."""
            self._progress = 0.0
            half = self._size // 2
            self.move(center_x - half, center_y - half)

            total_ticks = max(5, duration_ms // 20)
            self._tick_step = 1.0 / total_ticks

            self.show()
            self.raise_()
            os_interop.set_window_input_transparent(self, True)
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
            # Brackets converge inward: radius shrinks from 34px to 18px
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

            # Center Soul Crosshair +
            center_color = QColor(255, 230, 240, alpha)
            painter.setPen(QPen(center_color, 2.0))
            c_arm = 4.0
            painter.drawLine(int(mid - c_arm), int(mid), int(mid + c_arm), int(mid))
            painter.drawLine(int(mid), int(mid - c_arm), int(mid), int(mid + c_arm))

            painter.end()
else:
    class TakeoverBannerOverlay:
        pass

    class TargetReticleOverlay:
        pass
