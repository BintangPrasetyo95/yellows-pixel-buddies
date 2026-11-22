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
        # Whitelisted app passes whitelist check
        with patch.object(os_interop, "find_window", return_value=None), \
             patch.object(os_interop, "press_key") as mock_pk, \
             patch.object(os_interop, "type_text") as mock_type:
            os_interop.launch_or_focus("notepad", use_start_menu=True)
            # Should have called press_key("win") and typed "notepad"
            mock_pk.assert_any_call("win")
            mock_type.assert_called_with("notepad", delay_between_chars_s=0.02)

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
