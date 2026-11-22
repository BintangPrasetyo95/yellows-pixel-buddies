---
name: smoke-test
description: Run syntax compilation, import validation, and project health smoke tests across the codebase
allowed-tools: ["Bash", "GlobTool", "FileReadTool"]
---

# Smoke Test & Health Check

Execute a fast, non-destructive smoke check across the codebase to ensure nothing is broken after recent edits.

## Smoke Checks

1. **Python Syntax & Bytecode Compilation**:
   Run `py_compile` on all root Python files:
   ```powershell
   python -m py_compile yellows_pixel_buddies.py shop_window.py sound_manager.py os_interop.py voice_service.py action_planner.py takeover_overlay.py
   ```

2. **Core Dependency Verification**:
   Verify key libraries import successfully in this environment:
   ```powershell
   python -c "import PyQt5, requests, pygame, ctypes; print('Core imports OK!')"
   ```

3. **Critical Asset Directory Checks**:
   Confirm required runtime directories and fonts exist:
   - `sprites/`
   - `fonts/determination/determination.ttf`
   - `sounds/`

4. **Report Summary**:
   - Print a clean table of check results [PASS/FAIL].
   - If any file fails compilation, output the traceback and line number for immediate fixing.
