"""test_phase4_profiles.py - Unit tests for Phase 4: Profiles, Prompt Hardening & Cleanup."""

import unittest
from unittest.mock import patch, MagicMock
import os_interop
import action_planner

class TestPhase4Profiles(unittest.TestCase):

    def test_app_profiles(self):
        prof_wa = action_planner.get_app_profile("WhatsApp.exe")
        self.assertTrue(prof_wa.get("is_chat"))
        self.assertTrue(prof_wa.get("prevent_search_enter"))
        self.assertTrue(prof_wa.get("multiline_shift_enter"))

        prof_edge = action_planner.get_app_profile("msedge.exe")
        self.assertFalse(prof_edge.get("is_chat"))
        self.assertEqual(prof_edge.get("new_tab_hotkey"), ["ctrl", "t"])

        prof_none = action_planner.get_app_profile("some_random_binary.exe")
        self.assertEqual(prof_none, {})

    def test_start_menu_launch_whitelist(self):
        # Allowed app with a registered executable launches directly: no Win key, no typing (REVIEW M6)
        with patch.object(os_interop, "find_window", return_value=None), \
             patch.object(os_interop.os, "startfile", create=True) as mock_start, \
             patch.object(os_interop, "press_key") as mock_pk, \
             patch.object(os_interop, "type_text") as mock_type:
            os_interop.launch_or_focus("notepad", use_start_menu=True)
            mock_start.assert_called_once_with("notepad.exe")
            mock_pk.assert_not_called()
            mock_type.assert_not_called()

    def test_start_menu_search_types_only_when_search_has_focus(self):
        search = os_interop.WindowInfo(hwnd=5, title="Search", process_id=5, process_name="SearchHost.exe",
                                       bounds=(0, 0, 10, 10), is_minimized=False, is_cloaked=False)
        other = os_interop.WindowInfo(hwnd=6, title="Chat", process_id=6, process_name="whatsapp.exe",
                                      bounds=(0, 0, 10, 10), is_minimized=False, is_cloaked=False)
        # Start search opened: query typed, Enter pressed
        with patch.object(os_interop, "find_window", return_value=None), \
             patch.object(os_interop, "get_foreground_window", return_value=search), \
             patch.object(os_interop.time, "sleep"), \
             patch.object(os_interop, "press_key") as mock_pk, \
             patch.object(os_interop, "type_text") as mock_type:
            os_interop.launch_or_focus("Discord", use_start_menu=True)
            mock_type.assert_called_with("discord", delay_between_chars_s=0.02)
            mock_pk.assert_any_call("enter")
        # Start search did NOT open: nothing typed into the chat window that still has focus
        with patch.object(os_interop, "find_window", return_value=None), \
             patch.object(os_interop, "get_foreground_window", return_value=other), \
             patch.object(os_interop.time, "sleep"), \
             patch.object(os_interop, "press_key") as mock_pk, \
             patch.object(os_interop, "type_text") as mock_type:
            self.assertIsNone(os_interop.launch_or_focus("discord", use_start_menu=True))
            mock_type.assert_not_called()
            self.assertNotIn(unittest.mock.call("enter"), mock_pk.call_args_list)

    def test_allowlist_is_exact(self):
        self.assertFalse(os_interop.is_allowed_launch_query("regedit calc"))
        self.assertFalse(os_interop.is_allowed_launch_query("settings edge"))
        self.assertTrue(os_interop.is_allowed_launch_query("  Spotify App "))

    def test_start_menu_launch_blocks_unvetted_and_injection(self):
        with patch.object(os_interop, "find_window", return_value=None), \
             patch.object(os_interop, "press_key") as mock_pk:
            # Unvetted application
            res1 = os_interop.launch_or_focus("malicious_app_xyz", use_start_menu=True)
            self.assertIsNone(res1)
            mock_pk.assert_not_called()

            # Command injection with semicolon
            res2 = os_interop.launch_or_focus("calc; rm -rf /", use_start_menu=True)
            self.assertIsNone(res2)
            mock_pk.assert_not_called()

            # Pipe / redirect
            res3 = os_interop.launch_or_focus("notepad | echo test", use_start_menu=True)
            self.assertIsNone(res3)
            mock_pk.assert_not_called()

    def test_prompt_example_sanitization(self):
        # Verify placeholders replaced hardcoded strings
        self.assertIn("<message_or_command_to_type>", action_planner.VISION_AGENT_SYSTEM_PROMPT)
        self.assertNotIn("Replied 'yes' to Wulandari", action_planner.VISION_AGENT_SYSTEM_PROMPT)
        self.assertIn("TERMINOLOGY DIRECTIVE", action_planner.VISION_AGENT_SYSTEM_PROMPT)
        self.assertIn("SEARCH & FILTER INPUTS", action_planner.VISION_AGENT_SYSTEM_PROMPT)

if __name__ == "__main__":
    unittest.main()
