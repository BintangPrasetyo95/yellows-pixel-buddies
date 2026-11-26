import sys
import unittest
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import action_planner
import os_interop


class TestTakeoverBrowserIntent(unittest.TestCase):
    """Test suite for browser web navigation, simple open goal discrimination, and AI chatbot profiling."""

    def test_simple_open_goal_disqualifies_web_apps_and_compound_tasks(self):
        """Web apps and compound tasks must NEVER terminate early as simple open goals."""
        disqualified_queries = [
            "just do it, open claude in chrome and do it",
            "open claude in chrome and do it",
            "open claude in chrome",
            "open youtube in chrome",
            "open youtube music in chrome",
            "open WhatsApp Web",
            "open whatsapp web in chrome",
            "open web whatsapp",
            "open telegram web",
            "open discord web",
            "open claude",
            "open chatgpt",
            "tell claude to say hi to me",
            "open terminal and run git status",
            "open chrome then search for cat memes",
            "open chrome to watch videos",
            "open vscode and check git diff",
            "open word to write an essay",
        ]
        for query in disqualified_queries:
            with self.subTest(query=query):
                self.assertFalse(
                    action_planner.DesktopActionExecutor._is_simple_open_goal(query),
                    f"Expected '{query}' to NOT be treated as a simple open goal, but got True!",
                )

    def test_simple_open_goal_accepts_clean_os_applications(self):
        """Clean OS application launch/focus requests should be recognized as simple open goals."""
        valid_queries = [
            "open chrome",
            "open notepad",
            "focus vscode",
            "switch to spotify",
            "open calculator",
            "launch file explorer",
        ]
        for query in valid_queries:
            with self.subTest(query=query):
                self.assertTrue(
                    action_planner.DesktopActionExecutor._is_simple_open_goal(query),
                    f"Expected '{query}' to be recognized as a simple open goal, but got False!",
                )

    def test_requires_text_submission(self):
        """Prompting, asking, telling, sending, or typing should require text submission before completion."""
        self.assertTrue(action_planner.DesktopActionExecutor._requires_text_submission("tell claude to say hi to me"))
        self.assertTrue(action_planner.DesktopActionExecutor._requires_text_submission("ask chatgpt to explain quantum computing"))
        self.assertTrue(action_planner.DesktopActionExecutor._requires_text_submission("reply to Mom on WhatsApp saying on my way"))
        self.assertTrue(action_planner.DesktopActionExecutor._requires_text_submission("prompt claude with hello"))
        self.assertTrue(action_planner.DesktopActionExecutor._requires_text_submission("run terminal git status"))

        # Read-only queries must NOT require text submission
        self.assertFalse(action_planner.DesktopActionExecutor._requires_text_submission("what did Mom's message say"))
        self.assertFalse(action_planner.DesktopActionExecutor._requires_text_submission("read messages from Sarah"))
        self.assertFalse(action_planner.DesktopActionExecutor._requires_text_submission("check what time the meeting is"))

    def test_create_desktop_plan_target_app_inference(self):
        """Web apps mentioned in prompt or intent should resolve to Chrome/Browser container."""
        plan_claude = action_planner.create_desktop_plan(
            intent="tell claude to say hi to me",
            user_request="tell claude to say hi to me",
        )
        self.assertEqual(plan_claude.target_app, "Chrome")

        plan_chatgpt = action_planner.create_desktop_plan(
            intent="open chatgpt and write an essay",
            user_request="open chatgpt and write an essay",
        )
        self.assertEqual(plan_chatgpt.target_app, "Chrome")

        plan_yt = action_planner.create_desktop_plan(
            intent="play lofi on youtube",
            user_request="play lofi on youtube",
        )
        self.assertEqual(plan_yt.target_app, "Chrome")

    def test_app_profiles_web_apps(self):
        """App profiles should configure Claude, ChatGPT, and Chrome correctly."""
        claude_prof = action_planner.get_app_profile("claude")
        self.assertTrue(claude_prof.get("is_chat"))
        self.assertEqual(claude_prof.get("url"), "https://claude.ai")
        self.assertFalse(claude_prof.get("prevent_search_enter"))

        chatgpt_prof = action_planner.get_app_profile("chatgpt")
        self.assertTrue(chatgpt_prof.get("is_chat"))
        self.assertEqual(chatgpt_prof.get("url"), "https://chatgpt.com")

        chrome_prof = action_planner.get_app_profile("chrome")
        self.assertFalse(chrome_prof.get("prevent_search_enter"))

    def test_os_interop_search_aliases(self):
        """OS interop aliases should map claude and chatgpt to windows/browsers."""
        self.assertIn("claude", os_interop.APP_SEARCH_ALIASES)
        self.assertIn("chatgpt", os_interop.APP_SEARCH_ALIASES)
        self.assertIn("chrome.exe", os_interop.APP_SEARCH_ALIASES["claude"].hosts)  # a host, not the identity (REVIEW H5)

    def test_vision_prompt_covers_multi_app_compound_goals(self):
        prompt = action_planner.VISION_AGENT_SYSTEM_PROMPT
        self.assertIn("MULTI-APP / COMPOUND GOALS", prompt)
        self.assertIn("focus_window", prompt)
        self.assertIn("NEVER return \"fail\"", prompt)


if __name__ == "__main__":
    unittest.main()
