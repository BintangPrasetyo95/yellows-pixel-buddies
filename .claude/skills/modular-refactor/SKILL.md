---
name: modular-refactor
description: Safely extract a subsystem from the 16,800+ LOC monolith into a clean, decoupled module
argument-hint: "<new_module_name> <source_class_or_function>"
allowed-tools: ["GrepTool", "GlobTool", "FileReadTool", "FileWriteTool", "FileEditTool", "Bash"]
---

# Modular Refactor: Surgical Monolith Slicing

You are an expert refactoring engineer. `yellows_pixel_buddies.py` is an extreme monolith (~16,800 lines of code). 

### ⚠️ GOLDEN RULES:
1. **NEVER ATTEMPT FULL FILE REWRITES** of `yellows_pixel_buddies.py`.
2. Always make targeted, localized edits with adequate surrounding context.
3. Keep backward compatibility with existing method signatures and global references.

## Refactoring Workflow

When asked to extract `$2` into `$1.py`:

### Step 1: Dependency & Scope Analysis
- Find all occurrences and definitions of `$2` in `yellows_pixel_buddies.py`.
- Trace every dependency: imports, global variables (e.g. scale factors, paths, sounds), Qt signals, and callbacks to the main window.

### Step 2: Create the Standalone Module
- Create `$1.py` with:
  - Clear module docstring.
  - Necessary standard library and PyQt5 imports.
  - The extracted class/functions.
  - Decoupled interfaces (pass dependencies via constructor/init or methods instead of relying on external globals).
  - Explicit `__all__` list.

### Step 3: Surgical Replacement in Main Monolith
- In `yellows_pixel_buddies.py`:
  - Add `from $1 import ...` at the top of the file in the imports section.
  - Surgically remove the original implementation of `$2` or replace it with a thin forwarder/subclass to prevent breaking external callers.

### Step 4: Verification Check
- Run Python syntax and compile validation immediately:
  ```powershell
  python -m py_compile yellows_pixel_buddies.py $1.py
  ```
- If compilation fails, inspect errors, fix them, and re-verify until 100% clean.
