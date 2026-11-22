"""test_phase2_os_interop.py - Unit tests for Phase 2: Input Simulation & OS Interop Robustness."""

import unittest

import pytest
from unittest.mock import MagicMock, patch, call
import ctypes
from ctypes import wintypes
import os_interop
import action_planner

class TestPhase2OSInterop(unittest.TestCase):

    def test_hotkey_key_validation(self):
        # An invalid key in the sequence must cause hotkey() to return False early
        # and NEVER press down any modifier keys
        with patch.object(os_interop, "key_down") as mock_down:
            ok = os_interop.hotkey("ctrl", "completely_nonexistent_key_123")
            self.assertFalse(ok)
            mock_down.assert_not_called()

    def test_find_window_word_boundary(self):
        # Setup mock window list
        w1 = os_interop.WindowInfo(
            hwnd=101,
            title="Password Manager - KeePass",
            process_id=1001,
            process_name="keepass.exe",
            bounds=(0, 0, 100, 100),
            is_minimized=False,
            is_cloaked=False,
        )
        w2 = os_interop.WindowInfo(
            hwnd=102,
            title="Document1 - Microsoft Word",
            process_id=1002,
            process_name="winword.exe",
            bounds=(0, 0, 100, 100),
            is_minimized=False,
            is_cloaked=False,
        )
        w3 = os_interop.WindowInfo(
            hwnd=103,
            title="Google Chrome",
            process_id=1003,
            process_name="chrome.exe",
            bounds=(0, 0, 100, 100),
            is_minimized=False,
            is_cloaked=False,
        )

        with patch.object(os_interop, "list_windows", return_value=[w1, w2, w3]):
            # Searching for "word" must NOT match "Password Manager"
            found_word = os_interop.find_window("word")
            self.assertIsNotNone(found_word)
            self.assertEqual(found_word.hwnd, 102)
            self.assertEqual(found_word.process_name, "winword.exe")

            # Searching for "pass" should not match if word boundary is enforced
            found_pass = os_interop.find_window("pass")
            self.assertIsNone(found_pass)

            # Searching for "Password" should match
            found_pw = os_interop.find_window("Password")
            self.assertIsNotNone(found_pw)
            self.assertEqual(found_pw.hwnd, 101)

    def test_is_window_elevated_access_denied(self):
        if not os_interop.IS_WINDOWS:
            return

        def mock_get_pid(hwnd, pid_ptr):
            ctypes.cast(pid_ptr, ctypes.POINTER(wintypes.DWORD)).contents.value = 5555
            return 1

        with patch.object(os_interop.user32, "IsWindow", return_value=1), \
             patch.object(os_interop.user32, "GetWindowThreadProcessId", side_effect=mock_get_pid), \
             patch.object(os_interop.kernel32, "OpenProcess", return_value=0), \
             patch.object(ctypes, "GetLastError", return_value=5):
            is_elev, reason = os_interop.is_window_elevated(99999)
            self.assertTrue(is_elev)
            self.assertIn("Access denied", reason)

    def test_is_window_elevated_standard_token(self):
        if not os_interop.IS_WINDOWS:
            return

        def mock_get_pid(hwnd, pid_ptr):
            ctypes.cast(pid_ptr, ctypes.POINTER(wintypes.DWORD)).contents.value = 5555
            return 1

        def mock_get_token_info(token, token_class, token_info_ptr, token_info_len, ret_len_ptr):
            # Write TokenIsElevated = 0 to TOKEN_ELEVATION struct
            elev_struct = ctypes.cast(token_info_ptr, ctypes.POINTER(os_interop.TOKEN_ELEVATION)).contents
            elev_struct.TokenIsElevated = 0
            return 1

        with patch.object(os_interop.user32, "IsWindow", return_value=1), \
             patch.object(os_interop.user32, "GetWindowThreadProcessId", side_effect=mock_get_pid), \
             patch.object(os_interop.kernel32, "OpenProcess", return_value=123), \
             patch.object(os_interop.kernel32, "CloseHandle", return_value=1), \
             patch.object(os_interop.advapi32, "OpenProcessToken", return_value=1), \
             patch.object(os_interop.advapi32, "GetTokenInformation", side_effect=mock_get_token_info):
            is_elev, reason = os_interop.is_window_elevated(99999)
            self.assertFalse(is_elev)
            self.assertIn("Standard non-elevated user token", reason)

    def test_is_window_elevated_admin_token(self):
        if not os_interop.IS_WINDOWS:
            return

        def mock_get_pid(hwnd, pid_ptr):
            ctypes.cast(pid_ptr, ctypes.POINTER(wintypes.DWORD)).contents.value = 5555
            return 1

        def mock_get_token_info(token, token_class, token_info_ptr, token_info_len, ret_len_ptr):
            elev_struct = ctypes.cast(token_info_ptr, ctypes.POINTER(os_interop.TOKEN_ELEVATION)).contents
            elev_struct.TokenIsElevated = 1
            return 1

        with patch.object(os_interop.user32, "IsWindow", return_value=1), \
             patch.object(os_interop.user32, "GetWindowThreadProcessId", side_effect=mock_get_pid), \
             patch.object(os_interop.kernel32, "OpenProcess", return_value=123), \
             patch.object(os_interop.kernel32, "CloseHandle", return_value=1), \
             patch.object(os_interop.advapi32, "OpenProcessToken", return_value=1), \
             patch.object(os_interop.advapi32, "GetTokenInformation", side_effect=mock_get_token_info):
            is_elev, reason = os_interop.is_window_elevated(99999)
            self.assertTrue(is_elev)
            self.assertIn("Process has elevated Administrator token", reason)

    def test_type_text_chunking_and_send_input(self):
        long_text = "A" * 65  # 65 chars -> 3 chunks with chunk_size=25 (25, 25, 15)
        with patch.object(os_interop, "_send_input_batch") as mock_batch:
            ok = os_interop.type_text(long_text, chunk_size=25, delay_between_chars_s=0.0)
            self.assertTrue(ok)
            self.assertEqual(mock_batch.call_count, 3)

            c1_inputs = mock_batch.call_args_list[0][0][0]
            c2_inputs = mock_batch.call_args_list[1][0][0]
            c3_inputs = mock_batch.call_args_list[2][0][0]
            self.assertEqual(len(c1_inputs), 25 * 2)
            self.assertEqual(len(c2_inputs), 25 * 2)
            self.assertEqual(len(c3_inputs), 15 * 2)

    def test_type_text_shift_enter_for_chat(self):
        text = "Hello\nWorld"
        with patch.object(os_interop, "_send_input_batch") as mock_batch:
            ok = os_interop.type_text(text, use_shift_enter=True)
            self.assertTrue(ok)
            inputs = mock_batch.call_args_list[0][0][0]
            vk_codes = [inp.u.ki.wVk for inp in inputs if inp.u.ki.wVk != 0]
            self.assertIn(os_interop.VK_SHIFT, vk_codes)
            self.assertIn(os_interop.VK_RETURN, vk_codes)

    def test_type_text_focus_change_aborts(self):
        if not os_interop.IS_WINDOWS:
            return

        # _send_input_batch is mocked so the first chunk is never typed into the real foreground window.
        with patch.object(os_interop.user32, "GetForegroundWindow", side_effect=[111, 222]),              patch.object(os_interop, "_send_input_batch") as mock_batch:
            with self.assertRaises(os_interop.EmergencyAbortError):
                os_interop.type_text("Chunk1_123456789012345678Chunk2_123456789012345678", chunk_size=25, expected_hwnd=111)

    def test_desktop_plan_elevation_refusal(self):
        executor = action_planner.DesktopActionExecutor()
        plan = action_planner.DesktopPlan(
            intent="type command",
            target_app="PowerShell",
            steps=[]
        )

        mock_win = os_interop.WindowInfo(
            hwnd=777,
            title="Administrator: Windows PowerShell",
            process_id=9876,
            process_name="powershell.exe",
            bounds=(0, 0, 100, 100),
            is_minimized=False,
            is_cloaked=False,
        )

        with patch.object(os_interop, "get_foreground_window", return_value=None), \
             patch.object(os_interop, "find_window", return_value=mock_win), \
             patch.object(os_interop, "is_window_elevated", return_value=(True, "Process is elevated (Administrator)")):
            success = executor.execute_plan(plan)
            self.assertFalse(success)
            self.assertTrue(plan.is_finished)
            self.assertEqual(plan.outcome_state, "failed")
            self.assertIn("Administrator / elevated", plan.summary_message)

    @pytest.mark.desktop  # opens the real input desktop handle
    def test_attach_detach_worker_desktop(self):
        import threading
        result = {}

        def worker():
            ok_attach = os_interop.attach_worker_desktop()
            result["attach"] = ok_attach
            os_interop.detach_worker_desktop()
            result["detached"] = getattr(os_interop._THREAD_LOCAL, "desktop_handle", None) is None

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=2.0)

        self.assertTrue(result.get("attach"))
        self.assertTrue(result.get("detached"))

if __name__ == "__main__":
    unittest.main()
