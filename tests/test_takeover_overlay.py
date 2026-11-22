"""test_takeover_overlay.py - Unit tests for takeover_overlay.py."""

import unittest
import sys
from PyQt5.QtWidgets import QApplication

# Ensure single shared QApplication instance for tests
app = QApplication.instance() or QApplication(sys.argv)

import takeover_overlay

class TestTakeoverOverlay(unittest.TestCase):
    def test_banner_instantiation(self):
        banner = takeover_overlay.TakeoverBannerOverlay()
        self.assertIsNotNone(banner)
        self.assertEqual(banner.width(), 520)
        self.assertEqual(banner.height(), 68)

    def test_banner_update_step(self):
        banner = takeover_overlay.TakeoverBannerOverlay()
        banner.update_step(0, 3, "focus_window", "WhatsApp")
        self.assertIn("Step 1/3", banner._subtitle)
        self.assertIn("WhatsApp", banner._subtitle)

    def test_reticle_instantiation(self):
        reticle = takeover_overlay.TargetReticleOverlay()
        self.assertIsNotNone(reticle)
        self.assertEqual(reticle.width(), 80)
        self.assertEqual(reticle.height(), 80)

    def test_reticle_flash_and_dismiss(self):
        reticle = takeover_overlay.TargetReticleOverlay()
        reticle.flash_at(500, 400, duration_ms=100)
        self.assertEqual(reticle.x(), 500 - 40)
        self.assertEqual(reticle.y(), 400 - 40)
        reticle.dismiss()
        self.assertFalse(reticle.isVisible())

if __name__ == "__main__":
    unittest.main()
