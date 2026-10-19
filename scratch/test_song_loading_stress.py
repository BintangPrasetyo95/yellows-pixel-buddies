import sys
import time
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt5.QtWidgets import QApplication

# Ensure QApplication exists in headless/offscreen mode
app = QApplication.instance()
if not app:
    app = QApplication(["test", "-platform", "offscreen"])

from yellows_pixel_buddies import (
    YellowsPixelBuddies,
    SpriteBank,
    SPRITES_DIR,
    SONG_SKIP_RAPID_THRESHOLD_S,
    SONG_SKIP_STRESS_THRESHOLD,
    STRESSED_SKIP_LINES,
    DialogueStep,
)


def test_song_loading_and_stress_mechanics():
    print("Initializing test pet instance...")
    bank = SpriteBank(SPRITES_DIR, 1.0)
    pet = YellowsPixelBuddies(bank)
    pet._dialogue_enabled = True
    pet._ai_song_comment_enabled = True
    # Mock memory API key so AI commentary is considered available
    pet._memory.get_api_key = lambda: "mock_api_key"

    recorded_says = []
    gemini_triggers = []

    def mock_say(line, force=False, extra_queue=None, dialogue_category=None, **kwargs):
        recorded_says.append({
            "line": line,
            "force": force,
            "extra_queue": list(extra_queue) if extra_queue else [],
            "category": dialogue_category,
        })

    def mock_trigger(title, artist, skip_count=0):
        gemini_triggers.append({
            "title": title,
            "artist": artist,
            "skip_count": skip_count,
        })

    pet._say = mock_say
    pet._trigger_ai_song_comment = mock_trigger

    # 1. First song starts (normal play, no previous track)
    print("\n[Test 1] First song starts...")
    pet._last_song_start_time = -9999.0
    pet._on_song_started("Song A", "Artist A")

    assert pet._song_skip_count == 0, f"Expected skip count 0, got {pet._song_skip_count}"
    assert len(recorded_says) == 1
    say1 = recorded_says[-1]
    assert "* Now playing: Song A by Artist A" in say1["line"]
    assert len(say1["extra_queue"]) == 1
    assert isinstance(say1["extra_queue"][0], DialogueStep)
    assert say1["extra_queue"][0].text == "* ..."
    assert say1["extra_queue"][0].anim == "idle"
    assert len(gemini_triggers) == 1
    assert gemini_triggers[-1]["skip_count"] == 0
    print("-> Test 1 Passed: Normal song has '* ...' loading step and skip_count=0.")

    # 2. Rapid skip 1 (< 8.0s)
    print("\n[Test 2] Rapid skip 1 (2.0s later)...")
    pet._last_song_start_time = time.perf_counter() - 2.0
    pet._on_song_started("Song B", "Artist B")

    assert pet._song_skip_count == 1, f"Expected skip count 1, got {pet._song_skip_count}"
    assert len(recorded_says) == 2
    say2 = recorded_says[-1]
    assert "* Now playing: Song B by Artist B" in say2["line"]
    assert len(say2["extra_queue"]) == 1
    assert say2["extra_queue"][0].text == "* ...?"
    assert say2["extra_queue"][0].anim == "idle"
    assert len(gemini_triggers) == 2
    assert gemini_triggers[-1]["skip_count"] == 1
    print("-> Test 2 Passed: Skip 1 has '* ...?' loading step and skip_count=1.")

    # 3. Rapid skip 2 (< 8.0s)
    print("\n[Test 3] Rapid skip 2 (1.5s later)...")
    pet._last_song_start_time = time.perf_counter() - 1.5
    pet._on_song_started("Song C", "Artist C")

    assert pet._song_skip_count == 2, f"Expected skip count 2, got {pet._song_skip_count}"
    assert len(recorded_says) == 3
    say3 = recorded_says[-1]
    assert "* Now playing: Song C by Artist C" in say3["line"]
    assert len(say3["extra_queue"]) == 1
    assert "* ...?! (Wait, make up your mind!)" in say3["extra_queue"][0].text
    assert say3["extra_queue"][0].anim == "behind"
    assert len(gemini_triggers) == 3
    assert gemini_triggers[-1]["skip_count"] == 2
    print("-> Test 3 Passed: Skip 2 has '* ...?! (Wait, make up your mind!)' loading step with 'behind' sprite.")

    # 4. Rapid skip 3 (>= SONG_SKIP_STRESS_THRESHOLD = 3) -> STRESSED CONFUSION!
    print("\n[Test 4] Rapid skip 3 (1.0s later) -> Stressed confusion threshold...")
    pet._last_song_start_time = time.perf_counter() - 1.0
    pet._on_song_started("Song D", "Artist D")

    assert pet._song_skip_count == 3, f"Expected skip count 3, got {pet._song_skip_count}"
    assert len(recorded_says) == 4
    say4 = recorded_says[-1]
    assert "* Now playing: Song D by Artist D" in say4["line"]
    assert say4["category"] == "stressed_skip"
    assert len(say4["extra_queue"]) == 1
    stressed_step = say4["extra_queue"][0]
    # Verify stressed step came from STRESSED_SKIP_LINES
    valid_texts = [text for text, _ in STRESSED_SKIP_LINES]
    assert stressed_step.text in valid_texts, f"Unexpected stressed text: {stressed_step.text}"
    assert stressed_step.anim in ("shocked", "angry")
    # Gemini should NOT be triggered on stressed skip
    assert len(gemini_triggers) == 3, "Gemini should NOT be called when skip count >= 3!"
    assert pet._ai_comment_target_song == "", "_ai_comment_target_song should be cleared!"
    print(f"-> Test 4 Passed: Stressed skip triggered '{stressed_step.text}' ({stressed_step.anim}) without calling Gemini.")

    # 5. Continuous playback (> 8.0s) -> Calms down, resets skip count
    print("\n[Test 5] Playback continues for 15s, then next song plays...")
    pet._last_song_start_time = time.perf_counter() - 15.0
    pet._on_song_started("Song E", "Artist E")

    assert pet._song_skip_count == 0, f"Expected reset to 0, got {pet._song_skip_count}"
    assert len(recorded_says) == 5
    say5 = recorded_says[-1]
    assert "* Now playing: Song E by Artist E" in say5["line"]
    assert say5["extra_queue"][0].text == "* ..."
    assert say5["extra_queue"][0].anim == "idle"
    assert len(gemini_triggers) == 4
    assert gemini_triggers[-1]["skip_count"] == 0
    print("-> Test 5 Passed: Playback over threshold resets skip count and restores normal loading.")

    # 6. Test Stale Comment Discarding
    print("\n[Test 6] Stale comment discarding test...")
    pet._ai_comment_target_song = "Song Current"
    # Call _on_gemini_song_comment with target_song = "Song Old"
    turns_before = len(pet._memory.history)
    pet._on_gemini_song_comment(
        user_label="[Music played: 'Song Old']",
        spoken_text="* This song old was cool! [anim: peace_sign]",
        anim="peace_sign",
        target_song="Song Old",
    )
    # Stale comment should be discarded and not recorded in history
    assert len(pet._memory.history) == turns_before, "Stale commentary should be discarded!"
    print("-> Test 6 Passed: Stale comment for mismatched target song was successfully discarded.")

    # 7. Test clean_song_title
    print("\n[Test 7] Song title cleaning test...")
    from yellows_pixel_buddies import clean_song_title
    assert clean_song_title("Megalovania (Official Audio)") == "Megalovania"
    assert clean_song_title("Bad Apple!! [MV]") == "Bad Apple!!"
    assert clean_song_title("Never Gonna Give You Up (Official Music Video)") == "Never Gonna Give You Up"
    assert clean_song_title("Simple Song") == "Simple Song"
    print("-> Test 7 Passed: Metadata video tags cleaned from song titles successfully.")

    # 8. Test _cancel_previous_song_loading
    print("\n[Test 8] Immediate skip cancellation test...")
    pet._ai_comment_target_song = "Song To Cancel"
    pet._pending_song_announcement = ("line", [], "Song To Cancel", "Artist")
    pet._cancel_previous_song_loading()
    assert pet._ai_comment_target_song == "", "_ai_comment_target_song must be cleared by _cancel_previous_song_loading!"
    assert pet._pending_song_announcement is None, "_pending_song_announcement must be cleared by _cancel_previous_song_loading!"
    print("-> Test 8 Passed: _cancel_previous_song_loading immediately clears active target song and pending announcements.")

    # 9. Test _on_gemini_song_error dismisses loading bubble
    print("\n[Test 9] Error dismissal test...")
    pet._ai_comment_target_song = "Error Track"
    pet._dialogue_overlay._active = True
    pet._dialogue_overlay._full_text = "* ..."
    pet._on_gemini_song_error("Network timeout", target_song="Error Track")
    assert pet._ai_comment_target_song == "", "Target song must be cleared on error!"
    assert not pet._dialogue_overlay._active, "Dialogue overlay should be dismissed on loading error!"
    print("-> Test 9 Passed: Song loading bubble dismissed cleanly upon Gemini error.")

    # Clean up media watcher thread to avoid QThread destroyed warning
    if hasattr(pet, "_media_watcher") and pet._media_watcher is not None:
        pet._media_watcher.stop()
        pet._media_watcher.wait(2000)

    print("\nALL SONG LOADING & SKIP STRESS TESTS PASSED!")


if __name__ == "__main__":
    test_song_loading_and_stress_mechanics()
