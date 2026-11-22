import sys
import json
import shutil
import datetime
import tempfile
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from yellows_pixel_buddies import MemoryManager
import re

def test_memory_manager_temporary_facts():
    print("=== Testing MemoryManager Temporary Facts ===")
    with tempfile.TemporaryDirectory() as temp_dir:
        data_dir = Path(temp_dir)
        mem = MemoryManager(data_dir)

        # 1. Initial state
        assert mem.temp_facts_path.exists(), "temp_facts.json should exist"
        assert mem.get_active_temporary_facts() == [], "Initial temp facts should be empty"
        assert mem.get_temporary_facts_prompt() == "", "Prompt should be empty"

        # 2. Add temporary fact
        ok = mem.add_temporary_fact("User is recovering from a cold today", source="pink")
        assert ok is True, "Adding temp fact should succeed"
        active = mem.get_active_temporary_facts()
        assert len(active) == 1
        assert active[0]["text"] == "User is recovering from a cold today"
        assert active[0]["source"] == "pink"

        # 3. Deduplication
        ok_dup = mem.add_temporary_fact("user is recovering from a cold today", source="pink")
        assert ok_dup is False, "Duplicate temp fact should be rejected"
        assert len(mem.get_active_temporary_facts()) == 1

        # 4. Add second fact
        ok2 = mem.add_temporary_fact("User is crunching for a 48h game jam", source="chat")
        assert ok2 is True
        active = mem.get_active_temporary_facts()
        assert len(active) == 2

        # 5. Prompt generation
        prompt = mem.get_temporary_facts_prompt(numbered=True)
        assert "1. User is recovering from a cold today" in prompt
        assert "2. User is crunching for a 48h game jam" in prompt
        assert "expires in ~48h" in prompt or "expires in ~47h" in prompt
        print("Generated prompt snippet:\n", prompt)

        # 6. TTL Expiration (48 hours)
        # Create an expired fact by backdating created_at to 50 hours ago
        now = datetime.datetime.now()
        expired_dt = now - datetime.timedelta(hours=50)
        valid_dt = now - datetime.timedelta(hours=20)
        
        raw_items = [
            {
                "id": "tf_expired",
                "created_at": expired_dt.isoformat(),
                "text": "User had a headache two days ago",
                "source": "pink"
            },
            {
                "id": "tf_valid",
                "created_at": valid_dt.isoformat(),
                "text": "User is testing a new keyboard",
                "source": "pink"
            }
        ]
        mem.temp_facts_path.write_text(json.dumps(raw_items, indent=2), encoding="utf-8")

        # Calling get_active_temporary_facts should prune the expired one
        active_pruned = mem.get_active_temporary_facts()
        assert len(active_pruned) == 1, f"Expected 1 active item, got {len(active_pruned)}"
        assert active_pruned[0]["id"] == "tf_valid"
        assert active_pruned[0]["text"] == "User is testing a new keyboard"

        # Check that file on disk was pruned
        disk_items = json.loads(mem.temp_facts_path.read_text(encoding="utf-8"))
        assert len(disk_items) == 1
        assert disk_items[0]["id"] == "tf_valid"

        # 7. Deletion by identifier
        # By index
        del_ok, del_text = mem.delete_temporary_fact(1)
        assert del_ok is True
        assert del_text == "User is testing a new keyboard"
        assert len(mem.get_active_temporary_facts()) == 0

        # By text or ID
        mem.add_temporary_fact("Temporary note A")
        mem.add_temporary_fact("Temporary note B")
        del_ok, _ = mem.delete_temporary_fact("note a")
        assert del_ok is True
        assert len(mem.get_active_temporary_facts()) == 1

        # Clear all
        cleared = mem.clear_all_temporary_facts()
        assert cleared == 1
        assert len(mem.get_active_temporary_facts()) == 0

        # 8. Capacity cap (max 8)
        for i in range(12):
            mem.add_temporary_fact(f"Fact number {i}")
        capped = mem.get_active_temporary_facts()
        assert len(capped) == 8, f"Expected capped to 8 items, got {len(capped)}"
        assert capped[-1]["text"] == "Fact number 11"
        assert capped[0]["text"] == "Fact number 4"

    print("PASS: MemoryManager Temporary Facts tests passed!")

def test_tag_extraction_and_cleaning():
    print("=== Testing Tag Extraction & Cleaning Regex ===")
    sample_text = (
        "* S-serve you right for staying up, minion! Drink water! "
        "[anim: tongue] [add_temp_fact: User has a sore throat today] "
        "[delete_temp_fact: exam]"
    )

    # 1. Extraction regex
    temp_facts_extracted = []
    for m in re.finditer(r"\[(?:add_temp_fact|temp_fact):\s*([^\]]+)\]", sample_text, re.IGNORECASE):
        temp_facts_extracted.append(m.group(1).strip())
    assert temp_facts_extracted == ["User has a sore throat today"]

    del_extracted = []
    for m in re.finditer(r"\[(?:delete_temp_fact|del_temp_fact|rm_temp_fact):\s*([^\]]+)\]", sample_text, re.IGNORECASE):
        del_extracted.append(m.group(1).strip())
    assert del_extracted == ["exam"]

    # 2. Cleaning regex
    cleaned = re.sub(
        r"\[(?:set_user_name|add_fact|add_temp_fact|temp_fact|delete_temp_fact|del_temp_fact|rm_temp_fact|add_reminder|delete_reminder|edit_reminder|add_goal|complete_goal|finish_goal|done_goal|delete_goal|del_goal|rm_goal|update_goal|set_goal_deadline|snooze_goals|set_coaching_mode|set_timer|set_alarm|cancel_timer|cancel_alarm|timer|alarm):\s*[^\]]+\]",
        "",
        sample_text,
        flags=re.IGNORECASE
    ).strip()

    assert "[add_temp_fact:" not in cleaned
    assert "[delete_temp_fact:" not in cleaned
    assert "[anim: tongue]" in cleaned  # Anim tag preserved for anim parser
    assert cleaned.startswith("* S-serve you right")

    print("PASS: Tag extraction & regex cleaning passed!")

if __name__ == "__main__":
    test_memory_manager_temporary_facts()
    test_tag_extraction_and_cleaning()
    print("ALL TESTS PASSED SUCCESSFULLY!")
