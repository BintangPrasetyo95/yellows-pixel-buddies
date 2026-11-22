"""test_os_interop.py - Verification and unit tests for os_interop.py."""

import unittest

import pytest
import os_interop

class TestOSInterop(unittest.TestCase):
    @pytest.mark.desktop  # reads the real screen / window list
    def test_screen_metrics(self):
        metrics = os_interop.get_screen_metrics()
        self.assertGreater(metrics.primary_width, 0)
        self.assertGreater(metrics.primary_height, 0)
        self.assertGreaterEqual(metrics.virtual_width, metrics.primary_width)
        self.assertGreaterEqual(metrics.virtual_height, metrics.primary_height)

    @pytest.mark.desktop  # reads the real screen / window list
    def test_coords_to_normalized_virtual(self):
        metrics = os_interop.get_screen_metrics()
        # Top-left of virtual desktop
        nx, ny = os_interop.coords_to_normalized_virtual(metrics.virtual_left, metrics.virtual_top)
        self.assertEqual(nx, 0)
        self.assertEqual(ny, 0)

        # Center
        cx = metrics.virtual_left + metrics.virtual_width // 2
        cy = metrics.virtual_top + metrics.virtual_height // 2
        nx_c, ny_c = os_interop.coords_to_normalized_virtual(cx, cy)
        self.assertTrue(30000 <= nx_c <= 35000)
        self.assertTrue(30000 <= ny_c <= 35000)

        # Bottom-right
        br_x = metrics.virtual_left + metrics.virtual_width
        br_y = metrics.virtual_top + metrics.virtual_height
        nx_br, ny_br = os_interop.coords_to_normalized_virtual(br_x, br_y)
        self.assertLessEqual(nx_br, 65535)
        self.assertLessEqual(ny_br, 65535)

    @pytest.mark.desktop  # reads the real screen / window list
    def test_window_enumeration_and_finding(self):
        windows = os_interop.list_windows(visible_only=True)
        self.assertIsInstance(windows, list)
        self.assertGreater(len(windows), 0, "Should have at least one visible window.")

        first_win = windows[0]
        self.assertGreater(first_win.hwnd, 0)
        self.assertIsInstance(first_win.title, str)
        self.assertIsInstance(first_win.process_name, str)
        self.assertIsInstance(first_win.bounds, tuple)
        self.assertEqual(len(first_win.bounds), 4)

        # Test finding this existing window
        found = os_interop.find_window(first_win.title[:10])
        self.assertIsNotNone(found, f"Should find window by partial title: '{first_win.title[:10]}'")

    def test_virtual_key_mappings(self):
        for key in ["enter", "return", "tab", "space", "backspace", "esc", "ctrl", "alt", "shift", "win"]:
            self.assertIn(key, os_interop.VIRTUAL_KEY_MAP)
            vk = os_interop.VIRTUAL_KEY_MAP[key]
            self.assertIsInstance(vk, int)
            self.assertGreater(vk, 0)

    def test_emergency_abort_exception(self):
        with self.assertRaises(os_interop.EmergencyAbortError):
            # Test mouse shake check with a huge delta
            os_interop.check_emergency_abort(expected_cursor_pos=(-99999, -99999), shake_threshold_px=50)

    @pytest.mark.desktop  # reads the real screen / window list
    def test_cursor_pos(self):
        x, y = os_interop.get_cursor_pos()
        self.assertIsInstance(x, int)
        self.assertIsInstance(y, int)

if __name__ == "__main__":
    unittest.main()
