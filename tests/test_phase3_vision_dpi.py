"""test_phase3_vision_dpi.py - Unit tests for Phase 3: Vision Capture, Multi-Monitor & DPI Precision."""

import unittest
from unittest.mock import MagicMock, patch
import io
import ctypes
from PIL import Image

import os_interop
import action_planner
import takeover_overlay

class TestPhase3VisionDPI(unittest.TestCase):

    def test_ensure_process_dpi_aware(self):
        res = os_interop.ensure_process_dpi_aware()
        self.assertIsInstance(res, bool)

    def test_get_monitor_rect_for_window(self):
        if not os_interop.IS_WINDOWS:
            return

        mock_mi = os_interop.MONITORINFO()
        mock_mi.rcMonitor.left = 1920
        mock_mi.rcMonitor.top = 0
        mock_mi.rcMonitor.right = 3840
        mock_mi.rcMonitor.bottom = 1080

        def mock_get_info(hmon, mi_ptr):
            ctypes.cast(mi_ptr, ctypes.POINTER(os_interop.MONITORINFO)).contents.rcMonitor.left = 1920
            ctypes.cast(mi_ptr, ctypes.POINTER(os_interop.MONITORINFO)).contents.rcMonitor.top = 0
            ctypes.cast(mi_ptr, ctypes.POINTER(os_interop.MONITORINFO)).contents.rcMonitor.right = 3840
            ctypes.cast(mi_ptr, ctypes.POINTER(os_interop.MONITORINFO)).contents.rcMonitor.bottom = 1080
            return 1

        with patch.object(os_interop.user32, "IsWindow", return_value=1), \
             patch.object(os_interop.user32, "MonitorFromWindow", return_value=999), \
             patch.object(os_interop.user32, "GetMonitorInfoW", side_effect=mock_get_info):
            rect = os_interop.get_monitor_rect_for_window(12345)
            self.assertEqual(rect, (1920, 0, 3840, 1080))

    def test_capture_screen_region_multi_monitor_bounds(self):
        # Create a mock 1920x1080 PIL image
        dummy_img = Image.new("RGB", (1920, 1080), color=(50, 50, 50))
        target_bounds = (-1920, 0, 0, 1080)

        with patch("action_planner.ImageGrab.grab", return_value=dummy_img) as mock_grab:
            b64, orig_w, orig_h, offset = action_planner.capture_screen_region(
                bounds=target_bounds,
                draw_cursor=False,
                draw_grid=False,
            )
            self.assertEqual(offset, (-1920, 0))
            self.assertEqual(orig_w, 1920)
            self.assertEqual(orig_h, 1080)
            self.assertIsNotNone(b64)
            # Verify all_screens=True was passed to ImageGrab.grab
            mock_grab.assert_called_with(bbox=target_bounds, all_screens=True)

    def test_capture_screen_region_fallback_offset(self):
        # If grab with bbox fails and fallback runs, offset must be (0, 0)
        dummy_img = Image.new("RGB", (1920, 1080), color=(50, 50, 50))

        def side_effect(*args, **kwargs):
            if "bbox" in kwargs:
                raise RuntimeError("Display driver error")
            return dummy_img

        with patch("action_planner.ImageGrab.grab", side_effect=side_effect):
            b64, orig_w, orig_h, offset = action_planner.capture_screen_region(
                bounds=(1920, 0, 3840, 1080),
                draw_cursor=False,
                draw_grid=False,
            )
            self.assertEqual(offset, (0, 0))

    def test_crisp_4k_downscale_order(self):
        # Mock 4K screenshot (3840x2160)
        fake_4k = Image.new("RGB", (3840, 2160), color=(20, 20, 30))

        with patch("action_planner.ImageGrab.grab", return_value=fake_4k), \
             patch("action_planner._draw_normalized_coordinate_grid") as mock_draw_grid:
            # Let mock_draw_grid return the image passed to it
            mock_draw_grid.side_effect = lambda img: img

            b64, orig_w, orig_h, offset = action_planner.capture_screen_region(
                bounds=None,
                max_dimension=1920,
                draw_cursor=False,
                draw_grid=True,
            )

            # 1. Reported orig_w and orig_h must remain native 4K so grounding box projection is correct
            self.assertEqual(orig_w, 3840)
            self.assertEqual(orig_h, 2160)

            # 2. _LAST_RAW_SCREENSHOT must be stored as native 4K
            self.assertEqual(action_planner._LAST_RAW_SCREENSHOT.size, (3840, 2160))

            # 3. Grid MUST have been drawn on the downscaled image (1920x1080), NOT the 4K image!
            self.assertTrue(mock_draw_grid.called)
            drawn_img = mock_draw_grid.call_args[0][0]
            self.assertEqual(drawn_img.size, (1920, 1080))

    def test_takeover_banner_multi_monitor_and_elision(self):
        if not takeover_overlay.HAS_PYQT:
            return

        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import QRect, QPoint

        app = QApplication.instance() or QApplication([])

        banner = takeover_overlay.TakeoverBannerOverlay()
        # Very long subtitle that would overflow 520px banner without elision
        long_sub = "Step 4/12: Click And Type on 'Super Long Target Field Description That Would Overflow The Bounding Box Without Ellipsis Text Elision'..."

        with patch.object(QApplication, "screenAt") as mock_screen_at:
            mock_screen = MagicMock()
            mock_screen.geometry.return_value = QRect(1920, 0, 1920, 1080)
            mock_screen_at.return_value = mock_screen

            banner.show_banner(title="TEST", subtitle=long_sub)
            # Position should be on the second monitor: 1920 + (1920 - 520)/2 = 1920 + 700 = 2620
            self.assertEqual(banner.x(), 1920 + (1920 - banner.width()) // 2)
            self.assertEqual(banner.y(), 24)

        banner.dismiss()

    def test_target_reticle_high_dpi_mapping(self):
        if not takeover_overlay.HAS_PYQT:
            return

        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import QRect

        app = QApplication.instance() or QApplication([])
        reticle = takeover_overlay.TargetReticleOverlay()

        # Mock a 1.5x scaled screen at logical (0, 0, 2560, 1440) -> physical (0, 0, 3840, 2160)
        mock_screen = MagicMock()
        mock_screen.devicePixelRatio.return_value = 1.5
        mock_screen.geometry.return_value = QRect(0, 0, 2560, 1440)

        with patch.object(QApplication, "screens", return_value=[mock_screen]):
            # Flash at physical (1500, 750):
            # In logical coordinates: 1500 / 1.5 = 1000, 750 / 1.5 = 500
            # Reticle size is 80x80, half is 40
            # Expected widget position: (1000 - 40, 500 - 40) = (960, 460)
            reticle.flash_at(1500, 750, duration_ms=100)
            self.assertEqual(reticle.x(), 960)
            self.assertEqual(reticle.y(), 460)

        reticle.dismiss()

if __name__ == "__main__":
    unittest.main()
