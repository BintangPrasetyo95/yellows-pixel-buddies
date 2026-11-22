---
name: release-precheck
description: Enforce version synchronization between Python, Inno Setup, and build artifacts before release
argument-hint: "[optional new version string e.g. 1.2.3.4]"
allowed-tools: ["GrepTool", "FileReadTool", "Bash"]
---

# Pre-Release & Version Synchronization Gatekeeper

You are the release manager for Yellow's Pixel Buddies. In this project, **inconsistent version strings cause the auto-updater to loop indefinitely or download obsolete binaries**.

## Pre-Release Verification Protocol

Execute the following checks in order:

### 1. Active Branch Verification
- Check current git branch: `git branch --show-current`.
- ⚠️ **RULE**: Do NOT bump versions on feature/bugfix branches. Version bumps must only occur on `main` or designated release branches.

### 2. Version Synchronization Check
- Extract `APP_VERSION` from `yellows_pixel_buddies.py` (around line 128).
- Extract `#define MyAppVersion` from `installer.iss` (around line 5).
- If an argument `$1` was provided:
  - Check whether both files reflect `$1`.
- Verify that both version strings match **EXACTLY**:
  ```powershell
  Select-String -Path "yellows_pixel_buddies.py", "installer.iss" -Pattern "(APP_VERSION|MyAppVersion)"
  ```

### 3. PyInstaller Spec Packaging Check
- Read `Yellows-Pixel-Buddies.spec`.
- Verify all necessary asset directories are bundled:
  - `sprites`
  - `fonts`
  - `sounds`
  - `memory` (default template / structure if applicable)

### 4. Build Readiness Verdict
- If versions match and assets are accounted for:
  - Output **PASS**: Ready to build release via `build_release.bat`.
- If versions mismatch:
  - Output **FAIL (CRITICAL)**: Detail the mismatch and provide exact edits required before running `build_release.bat`.
