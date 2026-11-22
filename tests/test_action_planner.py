"""test_action_planner.py - Unit tests for action_planner.py."""

import unittest

import pytest
from unittest.mock import MagicMock, patch
import action_planner

class TestActionPlanner(unittest.TestCase):
    def test_parse_grounding_json(self):
        # Markdown json format
        md_text = '```json\n{"box_2d": [100, 200, 300, 400], "label": "send button", "confidence": 0.95}\n```'
        res = action_planner._parse_grounding_json(md_text)
        self.assertIsNotNone(res)
        self.assertEqual(res["box_2d"], [100, 200, 300, 400])
        self.assertEqual(res["label"], "send button")

        # Raw json format
        raw_text = '{"box_2d": [500, 600, 700, 800], "label": "input box", "confidence": 0.88}'
        res2 = action_planner._parse_grounding_json(raw_text)
        self.assertIsNotNone(res2)
        self.assertEqual(res2["box_2d"], [500, 600, 700, 800])

        # Regex fallback format
        fallback_text = 'The coordinates are [150, 250, 350, 450] on screen.'
        res3 = action_planner._parse_grounding_json(fallback_text)
        self.assertIsNotNone(res3)
        self.assertEqual(res3["box_2d"], [150, 250, 350, 450])

    def test_grounded_box_coordinates(self):
        # Test 1920x1080 screen with box [500, 500, 600, 600] at offset (0, 0)
        box = action_planner.GroundedBox(
            ymin=500,
            xmin=500,
            ymax=600,
            xmax=600,
            label="test",
            confidence=0.9,
            pixel_x=960,
            pixel_y=540,
            pixel_width=100,
            pixel_height=50,
        )
        d = box.to_dict()
        self.assertEqual(d["box_2d"], [500, 500, 600, 600])
        self.assertEqual(d["pixel_center"], [960, 540])

    def test_create_desktop_plan_whatsapp(self):
        plan = action_planner.create_desktop_plan("Reply to Mom on WhatsApp: I am on my way")
        self.assertEqual(plan.target_app, "WhatsApp")
        self.assertEqual(plan.outcome_state, "pending")
        self.assertFalse(plan.is_finished)

    def test_create_desktop_plan_search(self):
        plan = action_planner.create_desktop_plan("Search for funny cat videos in Chrome", target_app="Chrome")
        self.assertEqual(plan.target_app, "Chrome")
        self.assertEqual(plan.outcome_state, "pending")
        self.assertFalse(plan.is_finished)

    def test_read_only_intent_guard(self):
        executor = action_planner.DesktopActionExecutor()
        # Read-only queries must NOT require text submission
        self.assertFalse(executor._requires_text_submission("what does Mom's last message say"))
        self.assertFalse(executor._requires_text_submission("read the error in the terminal"))
        self.assertFalse(executor._requires_text_submission("check what is on screen"))
        self.assertFalse(executor._requires_text_submission("what is the weather"))
        self.assertFalse(executor._requires_text_submission("what type of file is this"))

        # Explicit typing/sending actions MUST require text submission
        self.assertTrue(executor._requires_text_submission("reply to Mom saying I am on my way"))
        self.assertTrue(executor._requires_text_submission("send a message to Bob saying hello"))
        self.assertTrue(executor._requires_text_submission("type git status in the terminal"))
        self.assertTrue(executor._requires_text_submission("write an essay about cats"))

    def test_sensitive_action_detection(self):
        executor = action_planner.DesktopActionExecutor()
        # Non-sensitive actions (search boxes, regular navigation)
        step_search = action_planner.ActionStep(
            action_type="click_and_type",
            target="Search or start new chat",
            text="Mom",
            press_enter=True,
        )
        self.assertFalse(executor._is_sensitive_action(step_search))

        step_nav = action_planner.ActionStep(action_type="click", target="Chrome Tab")
        self.assertFalse(executor._is_sensitive_action(step_nav))

        # Sensitive actions (typing with enter in chat message box)
        step_chat_msg = action_planner.ActionStep(
            action_type="click_and_type",
            target="Message input box",
            text="Hello there!",
            press_enter=True,
        )
        self.assertTrue(executor._is_sensitive_action(step_chat_msg))

        # Destructive buttons
        step_send_btn = action_planner.ActionStep(action_type="click", target="Send button")
        self.assertTrue(executor._is_sensitive_action(step_send_btn))

        step_del_btn = action_planner.ActionStep(action_type="click", target="Delete file button")
        self.assertTrue(executor._is_sensitive_action(step_del_btn))

        # Terminal command execution
        step_terminal = action_planner.ActionStep(
            action_type="type_text",
            target="VS Code terminal panel",
            text="git push origin main",
            press_enter=True,
        )
        self.assertTrue(executor._is_sensitive_action(step_terminal, fg_proc="code.exe"))

    @pytest.mark.desktop  # sends a REAL Esc keystroke to the focused window
    def test_esc_self_abort_swallowed(self):
        import os_interop
        os_interop.reset_panic_abort()
        self.assertFalse(os_interop.is_panic_key_pressed())

        # Pressing simulated Esc through os_interop should clear its own transition state
        os_interop.press_key("esc")
        self.assertFalse(os_interop.is_panic_key_pressed())

    @patch("action_planner.requests.post")
    def test_secure_api_key_header_and_fast_fail(self, mock_post):
        # 1. Verify header is used instead of query param
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_post.return_value = mock_resp

        res = action_planner._call_gemini_json(
            system_prompt="sys",
            user_prompt="user",
            screenshot_b64=None,
            api_key="SECRET_KEY_12345",
        )
        self.assertIsNone(res)

        # Inspect the call
        call_args = mock_post.call_args
        self.assertIsNotNone(call_args)
        called_url = call_args[0][0]
        called_headers = call_args[1].get("headers", {})

        # URL must NOT contain the API key
        self.assertNotIn("SECRET_KEY_12345", called_url)
        self.assertNotIn("?key=", called_url)

        # Headers must contain x-goog-api-key
        self.assertEqual(called_headers.get("x-goog-api-key"), "SECRET_KEY_12345")

        # 401 should fail fast (called only once, no fallback iteration)
        self.assertEqual(mock_post.call_count, 1)

    def test_action_tag_parsing_and_stripping(self):
        dialogue = (
            "* Fine, minion! I will reply for you! [anim: smug] "
            "[desktop_action: WhatsApp, reply to Mom saying hello] "
            "Don't get used to this!"
        )
        tags = action_planner.extract_desktop_action_tags(dialogue)
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0]["type"], "desktop_action")
        self.assertEqual(tags[0]["app"], "WhatsApp")
        self.assertEqual(tags[0]["intent"], "reply to Mom saying hello")

        cleaned = action_planner.strip_desktop_action_tags(dialogue)
        self.assertNotIn("desktop_action", cleaned)
        self.assertIn("* Fine, minion!", cleaned)
        self.assertIn("Don't get used to this!", cleaned)

    def test_quick_reply_tag(self):
        dialogue = "* Replying now! [quick_reply: WhatsApp, Bob, see you tomorrow]"
        tags = action_planner.extract_desktop_action_tags(dialogue)
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0]["type"], "quick_reply")
        self.assertEqual(tags[0]["app"], "WhatsApp")
        self.assertEqual(tags[0]["contact"], "Bob")
        self.assertEqual(tags[0]["message"], "see you tomorrow")

    def test_executor_abort(self):
        executor = action_planner.DesktopActionExecutor()
        plan = action_planner.DesktopPlan(
            intent="test",
            target_app="test",
            steps=[
                action_planner.ActionStep(action_type="wait", wait_s=0.5),
                action_planner.ActionStep(action_type="wait", wait_s=0.5),
            ],
        )

        # Trigger abort before execution
        executor.abort()
        success = executor.execute_plan(plan)
        self.assertFalse(success)
        self.assertTrue(plan.is_finished)
        self.assertFalse(plan.success)

if __name__ == "__main__":
    unittest.main()
