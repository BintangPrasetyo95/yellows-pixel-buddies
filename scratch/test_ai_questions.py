import sys
import time
import json
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt5.QtWidgets import QApplication

app = QApplication.instance()
if not app:
    app = QApplication(["test", "-platform", "offscreen"])

from yellows_pixel_buddies import (
    YellowsPixelBuddies,
    SpriteBank,
    SPRITES_DIR,
    GeminiQuestionWorkerThread,
    QuestionItem,
    QUESTION_ITEMS,
    Phase,
)


def test_ai_question_mechanics():
    print("Initializing test pet instance for AI questions...")
    bank = SpriteBank(SPRITES_DIR, 1.0)
    pet = YellowsPixelBuddies(bank)
    pet._dialogue_enabled = True
    pet._memory.get_api_key = lambda: "mock_key"

    # =========================================================================
    # Test 1: JSON Parsing in GeminiQuestionWorkerThread
    # =========================================================================
    print("\n[Test 1] Testing GeminiQuestionWorkerThread._parse_question_json...")
    thread = GeminiQuestionWorkerThread(
        api_key="dummy",
        user_prompt="test",
        system_instruction="test",
        source_type="screen",
    )

    # 1a. Clean standard JSON
    sample_json = json.dumps({
        "question": "* Why do you have 50 tabs open?!",
        "choices": [
            {"label": "I need them!", "reaction": "* LIES! You're hoarding them!", "anim": "angry"},
            {"label": "Closing now", "reaction": "* Good! Prevent the meltdown!", "anim": "peace_sign"}
        ]
    })
    q1 = thread._parse_question_json(sample_json)
    assert q1.question == "* Why do you have 50 tabs open?!"
    assert len(q1.choices) == 2
    assert q1.choices[0] == ("I need them!", "* LIES! You're hoarding them!", "angry")
    assert q1.choices[1] == ("Closing now", "* Good! Prevent the meltdown!", "peace_sign")
    assert q1.category == "screen"

    # 1b. Markdown code fence wrapped JSON + missing "* " prefix
    wrapped_json = f"Here is the question:\n```json\n" + json.dumps({
        "question": "What are you coding?",
        "choices": [
            {"label": "A game", "reaction": "Can I play it?!", "anim": "singing"},
            {"label": "A tool", "reaction": "Sounds boring, mew!", "anim": "tongue"}
        ]
    }) + "\n```\nHope you like it!"
    q2 = thread._parse_question_json(wrapped_json)
    assert q2.question == "* What are you coding?"
    assert q2.choices[0] == ("A game", "* Can I play it?!", "singing")
    assert q2.choices[1] == ("A tool", "* Sounds boring, mew!", "tongue")

    # 1c. Invalid animation fallback
    json_weird_anim = json.dumps({
        "question": "* Question?",
        "choices": [
            {"label": "A", "reaction": "* React A", "anim": "laser_eye_blast"},
            {"label": "B", "reaction": "* React B", "anim": "peace_sign"}
        ]
    })
    q3 = thread._parse_question_json(json_weird_anim)
    assert q3.choices[0][2] == "idle"  # fallback to idle

    print("-> Test 1 Passed: JSON parsing handles markdown fences, prefixing, and anim fallback cleanly.")

    # =========================================================================
    # Test 2: Source Selection & Memory Highlights
    # =========================================================================
    print("\n[Test 2] Testing source selection and memory highlights...")
    # By default, mock facts exist so memory highlights should be True
    assert pet._has_memory_highlights() is True

    # Test source selection when screen & memory are enabled
    pet._screen_enabled = True
    sources = set(pet._pick_question_source() for _ in range(50))
    assert "screen" in sources
    assert "memory" in sources
    assert "personality" in sources
    print("-> Test 2 Passed: Dynamic source selection rolls between screen, memory, and personality.")

    # =========================================================================
    # Test 3: Best Memory Highlight Selection
    # =========================================================================
    print("\n[Test 3] Testing _get_best_memory_highlight priority...")
    # 3a. Current song priority
    pet._current_song = ("Megalovania", "Toby Fox")
    h1 = pet._get_best_memory_highlight()
    assert "Megalovania" in h1
    assert "Toby Fox" in h1

    # 3b. When no song, reminders / facts take over
    pet._current_song = None
    pet._memory.get_active_reminders = lambda: [{"text": "Water the plants"}]
    h2 = pet._get_best_memory_highlight()
    assert "Water the plants" in h2
    print("-> Test 3 Passed: Memory highlights prioritize active song and reminders properly.")

    # =========================================================================
    # Test 4: Question Prompt Building
    # =========================================================================
    print("\n[Test 4] Testing _build_question_prompt for all 3 sources...")
    sys_inst, prompt_screen = pet._build_question_prompt("screen")
    assert "CRITICAL OUTPUT FORMAT REQUIREMENTS" in sys_inst
    assert "Screen Observation" in prompt_screen

    _, prompt_memory = pet._build_question_prompt("memory")
    assert "Memory & Context" in prompt_memory

    _, prompt_persona = pet._build_question_prompt("personality")
    assert "Doll/Ghost Persona" in prompt_persona
    print("-> Test 4 Passed: System and user prompts built cleanly for all sources.")

    # =========================================================================
    # Test 5: AI Question Trigger and Ready Flow
    # =========================================================================
    print("\n[Test 5] Testing _trigger_ai_question and _on_ai_question_ready...")
    pet._last_dialogue = None
    test_q_item = QuestionItem(
        question="* Are you actually working or just clicking around?",
        choices=[
            ("Working hard!", "* Hmph! If you say so, minion!", "peace_sign"),
            ("Procrastinating", "* Bwahaha! Caught you red-handed!", "laughing")
        ],
        category="screen"
    )

    # Deliver question ready event
    pet._on_ai_question_ready(test_q_item, "screen")
    assert pet._dialogue_overlay.is_active() is True
    assert pet._dialogue_overlay._full_text == test_q_item.question
    assert len(pet._dialogue_overlay._choices) == 2
    # Verify recorded in ambient memory
    assert len(pet._memory.recent_ambient_dialogues) > 0
    ambient = pet._memory.recent_ambient_dialogues[-1]
    assert test_q_item.question in ambient["text"]
    assert ambient["category"] == "question_screen"
    print("-> Test 5 Passed: Question and choices presented in overlay and recorded in ambient context.")

    # =========================================================================
    # Test 6: Answering AI Question
    # =========================================================================
    print("\n[Test 6] Testing question answer callback and history recording...")
    history_len_before = len(pet._memory.history)
    # Simulate clicking choice 0
    pet._on_question_answered("Working hard!", "* Hmph! If you say so, minion!", "peace_sign")

    # History should have new turn recording user choice and pink reply
    assert len(pet._memory.history) == history_len_before + 1
    last_turn = pet._memory.history[-1]
    assert "Working hard!" in last_turn["user"]
    assert "* Hmph! If you say so, minion!" in last_turn["pink"]
    assert last_turn["anim"] == "peace_sign"
    print("-> Test 6 Passed: Answering question records to persistent conversation history with animation.")

    # =========================================================================
    # Test 7: Error Fallback to Static Questions
    # =========================================================================
    print("\n[Test 7] Testing _on_ai_question_error fallback...")
    pet._dialogue_overlay._active = True
    pet._dialogue_overlay._full_text = "* ...?"
    pet._on_ai_question_error("Simulated timeout error")
    assert pet._dialogue_overlay.is_active() is True
    assert pet._dialogue_overlay._full_text != "* ...?"
    assert len(pet._dialogue_overlay._choices) >= 2
    print("-> Test 7 Passed: Error fallback seamlessly presented static question from QUESTION_ITEMS.")

    # =========================================================================
    # Test 8: Chat Command /question
    # =========================================================================
    print("\n[Test 8] Testing /question chat command...")
    triggered = []
    pet._trigger_ai_question = lambda forced_source=None: triggered.append(forced_source) or True
    pet._on_chat_submitted("/question screen")
    assert len(triggered) == 1
    assert triggered[-1] == "screen"

    pet._on_chat_submitted("/ask memory")
    assert len(triggered) == 2
    assert triggered[-1] == "memory"

    pet._on_chat_submitted("ask me a question")
    assert len(triggered) == 3
    assert triggered[-1] is None
    print("-> Test 8 Passed: /question and /ask chat commands successfully dispatch AI questions.")

    # Clean up media watcher thread to avoid QThread destroyed warning
    if hasattr(pet, "_media_watcher") and pet._media_watcher is not None:
        pet._media_watcher.stop()
        pet._media_watcher.wait(2000)

    print("\nALL AI QUESTION OVERHAUL TESTS PASSED!")


if __name__ == "__main__":
    test_ai_question_mechanics()
