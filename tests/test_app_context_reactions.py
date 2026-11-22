import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import re
from yellows_pixel_buddies import (
    identify_active_app_context,
    DIALOGUE_LINES,
    NATIVE_APP_REACTIONS_ENABLED,
    APP_SWITCH_GLOBAL_COOLDOWN_S,
    APP_CATEGORY_COOLDOWN_S,
)

def test_identify_active_app_context():
    test_cases = [
        # (exe, path, title, expected_cat, expected_name_substr)
        ("mspaint.exe", r"C:\Windows\System32\mspaint.exe", "Untitled - Paint", "paint", "Paint"),
        ("Photoshop.exe", r"C:\Program Files\Adobe\Photoshop 2024\Photoshop.exe", "Drawing.psd @ 100%", "photoshop", "Photoshop"),
        ("aseprite.exe", r"C:\Steam\steamapps\common\Aseprite\aseprite.exe", "pink.aseprite - Aseprite v1.3", "pixel_art", "Aseprite"),
        ("blender.exe", r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe", "scene.blend - Blender", "blender_3d", "Blender"),
        ("chrome.exe", r"C:\Program Files\Google\Chrome\chrome.exe", "Deltarune OST - YouTube - Google Chrome", "youtube", "YouTube"),
        ("chrome.exe", r"C:\Program Files\Google\Chrome\chrome.exe", "shroud - Twitch - Google Chrome", "twitch", "Twitch"),
        ("firefox.exe", r"C:\Program Files\Mozilla Firefox\firefox.exe", "r/gaming - Reddit - Mozilla Firefox", "reddit", "Reddit"),
        ("chrome.exe", r"C:\Program Files\Google\Chrome\chrome.exe", "Home / X - Google Chrome", "twitter", "Twitter"),
        ("discord.exe", r"C:\Users\User\AppData\Local\Discord\discord.exe", "Discord", "discord", "Discord"),
        ("code.exe", r"C:\Users\User\AppData\Local\Programs\Microsoft VS Code\code.exe", "yellows_pixel_buddies.py - Visual Studio Code", "vscode", "VS Code"),
        ("taskmgr.exe", r"C:\Windows\System32\taskmgr.exe", "Task Manager", "task_manager", "Task Manager"),
        ("calc.exe", r"C:\Windows\System32\calc.exe", "Calculator", "calculator", "Calculator"),
        ("msedge.exe", r"C:\Program Files (x86)\Microsoft\Edge\msedge.exe", "ChatGPT - Personal - Microsoft​ Edge", "ai_chat", "AI Assistant"),
        ("chrome.exe", r"C:\Program Files\Google\Chrome\chrome.exe", "BintangPrasetyo95/pink-here - GitHub - Google Chrome", "github", "GitHub"),
        ("chrome.exe", r"C:\Program Files\Google\Chrome\chrome.exe", "python - How to detect windows - Stack Overflow - Google Chrome", "stackoverflow", "Stack Overflow"),
        ("windowsterminal.exe", r"C:\Program Files\WindowsApps\wt.exe", "Windows PowerShell", "terminal", "Terminal"),
        ("fl64.exe", r"C:\Program Files\Image-Line\FL Studio 21\FL64.exe", "Project_Final.flp - FL Studio 21", "music_daw", "FL Studio"),
        ("winword.exe", r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE", "Document1 - Word", "office", "Word"),
    ]

    for exe, path, title, exp_cat, exp_name in test_cases:
        cat, disp, detail = identify_active_app_context(exe, path, title)
        print(f"Testing {exe} | '{title}' -> Category: '{cat}', Display: '{disp}'")
        assert cat == exp_cat, f"Expected category '{exp_cat}', got '{cat}' for {exe} / {title}"
        assert exp_name.lower() in disp.lower(), f"Expected '{exp_name}' in '{disp}'"

    print("All identify_active_app_context tests passed!")

def test_dialogue_lines_exist():
    categories = [
        "paint", "photoshop", "pixel_art", "digital_art", "blender_3d",
        "game", "youtube", "twitch", "streaming", "reddit", "twitter",
        "discord", "social", "ai_chat", "github", "stackoverflow",
        "vscode", "coding_ide", "terminal", "task_manager", "calculator",
        "music_daw", "office"
    ]
    for cat in categories:
        key = f"app_{cat}"
        assert key in DIALOGUE_LINES, f"Missing {key} in DIALOGUE_LINES"
        lines = DIALOGUE_LINES[key]
        assert len(lines) >= 2, f"Expected at least 2 lines for {key}, got {len(lines)}"
        for line in lines:
            assert line.startswith("* "), f"Line in {key} must start with '* ': {line}"
            # Verify anim tag format
            m = re.search(r"\[anim:\s*([a-zA-Z0-9_]+)\]", line)
            assert m is not None, f"Line in {key} should contain an [anim: ...] tag: {line}"

    print("All DIALOGUE_LINES app categories verified!")

def test_configuration():
    assert NATIVE_APP_REACTIONS_ENABLED is True
    assert APP_SWITCH_GLOBAL_COOLDOWN_S > 0
    assert APP_CATEGORY_COOLDOWN_S > 0
    print("Configuration checks passed!")

if __name__ == "__main__":
    test_identify_active_app_context()
    test_dialogue_lines_exist()
    test_configuration()
    print("\nALL NATIVE APP REACTION TESTS PASSED SUCCESSFULLY!")
