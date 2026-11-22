---
name: architecture-critique
description: Critique code complexity, architectural debt, tight coupling, and recommend modularization targets
argument-hint: "[optional target file, class or subsystem]"
allowed-tools: ["GrepTool", "GlobTool", "FileReadTool"]
---

# Architecture & Code Smell Critique

You are acting as a senior software architect specializing in desktop application design, PyQt5, and refactoring large legacy codebases. Your role is to critically analyze the codebase, specifically targeting `yellows_pixel_buddies.py` (which is over 16,800 LOC) and `shop_window.py` (~3,300 LOC).

## Instructions

1. **Scope the Review**:
   - If an argument is provided (`$1`), focus specifically on that class, subsystem, or range (e.g. state machine, Gemini thread worker, physics, audio, alarms/timers).
   - If no argument is provided, analyze the monolith's overarching structure and identify the top 3 highest-priority architectural risks.

2. **Analysis Dimensions**:
   - **God Objects & Coupling**: Identify classes or methods that do too much (e.g. mixing network API calls, screen capture, physics calculations, and UI rendering in a single class).
   - **State Encapsulation**: Identify mutable global variables or hidden state dependencies that make refactoring risky.
   - **Extraction Viability**: Suggest self-contained subsystems that should be extracted into separate modules (similar to existing `sound_manager.py` and `os_interop.py`).
   - **Performance & Memory Leaks**: Look for unbound collections, lingering timers, unreleased QPixmap handles, or circular references preventing garbage collection.

3. **Output Format**:
   Deliver your critique structured as follows:
   - **Executive Summary**: Brief 2-3 sentence overview of code health in this section.
   - **Critical Vulnerabilities & Architectural Smells**: Bulleted list with exact line numbers and code snippets.
   - **Proposed Module Extraction Plan**:
     - Proposed module name (e.g. `gemini_worker.py`, `physics_engine.py`, `pet_animator.py`).
     - Required inputs / injected dependencies.
     - Public interface / methods exposed.
     - Step-by-step migration risk assessment (Low / Medium / High).
