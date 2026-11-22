---
name: add-pet-state
description: Register a new animation state, verify sprite files, and update state transitions & PyInstaller spec
argument-hint: "<state_name>"
allowed-tools: ["GlobTool", "FileReadTool", "FileEditTool", "Bash"]
---

# Add Pet State: Sprite & Animation Pipeline

You are responsible for adding and registering new animation states for Pink.

## Workflow for State: `$1`

1. **Verify Sprite Assets**:
   - Check directory `sprites/$1/` exists.
   - Verify it contains sequentially numbered frame images (`1.png`, `2.png`, ...).
   - Verify image dimensions and transparent PNG alpha channel.

2. **Register in `ALL_STATES`**:
   - In `yellows_pixel_buddies.py`, locate the `ALL_STATES` list definition.
   - Surgically add `"$1"` into the list if not already present.

3. **Check PyInstaller Spec (`Yellows-Pixel-Buddies.spec`)**:
   - Verify that `sprites/` is included in the `datas` array:
     ```python
     datas=[('sprites', 'sprites'), ('fonts', 'fonts'), ('sounds', 'sounds'), ...]
     ```
   - If new root asset folders were introduced, add them to `datas`.

4. **Wire State Trigger & Transitions**:
   - If `$1` should be triggered by Gemini action tags (`[emotion: $1]`), verify the parser maps to `$1`.
   - If `$1` is part of idle or walking state transitions, wire the transition probabilities in the pet state machine.

5. **Sanity Check**:
   - Run `python -m py_compile yellows_pixel_buddies.py` to ensure no syntax errors.
