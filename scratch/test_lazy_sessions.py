import sys
import shutil
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from yellows_pixel_buddies import MemoryManager


def test_lazy_sessions_and_pruning():
    temp_dir = ROOT / "scratch" / "temp_memory_test"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    print("\n[Test 1] Initializing MemoryManager without chat turns...")
    mem = MemoryManager(temp_dir)

    # File should NOT exist on disk yet (lazy initialization)
    assert not mem.session_file.exists(), f"Session file {mem.session_file} should not exist before any messages are sent!"
    print("-> Test 1 Passed: No session file created on startup.")

    print("\n[Test 2] Recording first turn triggers lazy creation...")
    mem.record_turn("Hello Pink!", "* Hmph! What do you want, dork?", "idle")
    assert mem.session_file.exists(), "Session file should now exist on disk after recording a turn!"
    assert len(mem.history) == 1
    print("-> Test 2 Passed: Session file created lazily upon first turn.")

    print("\n[Test 3] clear_current_session does not create an empty file...")
    mem.clear_current_session()
    assert not mem.session_file.exists(), "New session file should not exist on disk immediately after clear_current_session!"
    print("-> Test 3 Passed: clear_current_session resets in-memory history without creating empty file.")

    print("\n[Test 4] Prune empty session files...")
    # Create a couple dummy empty session files (<= 120 bytes)
    empty1 = mem.sessions_dir / "session_20261020_000001.json"
    empty1.write_text('{\n  "session_id": "dummy1",\n  "started_at": "...",\n  "messages": []\n}', encoding="utf-8")
    empty2 = mem.sessions_dir / "session_20261020_000002.json"
    empty2.write_text('{\n  "session_id": "dummy2",\n  "started_at": "...",\n  "messages": []\n}', encoding="utf-8")
    assert empty1.exists() and empty2.exists()

    pruned = mem.prune_empty_sessions()
    assert pruned == 2, f"Expected 2 pruned files, got {pruned}"
    assert not empty1.exists() and not empty2.exists(), "Dummy empty files should have been removed!"
    print("-> Test 4 Passed: prune_empty_sessions cleanly removed all 0-message files.")

    # Cleanup temp directory
    shutil.rmtree(temp_dir, ignore_errors=True)
    print("\nALL LAZY SESSION TESTS PASSED!")


if __name__ == "__main__":
    test_lazy_sessions_and_pruning()
