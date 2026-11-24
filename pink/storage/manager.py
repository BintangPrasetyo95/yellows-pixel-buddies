"""Pink's memory: facts, temporary facts, curiosities, reminders, goals, alarms/timers, wallet, settings, token usage
and chat sessions (plan 8.7, moved out of yellows_pixel_buddies.py).

All JSON goes through ``JsonStore`` (atomic, locked, corrupt files never overwritten - REVIEW C6); sessions are
append-only JSON Lines (``pink.storage.sessions``). No Qt, no torch, no main-script import: the main file passes its
two settings in with ``configure()``.
"""
from __future__ import annotations

import datetime
import functools
import inspect
import json
import logging
import os
import re
import shutil
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

import privacy
from pink.ai import protocol
from pink.storage import sessions
from pink.storage.json_store import JsonStore, StoreCorrupt
from pink.text.intents import evaluate_goal_value, parse_clock_time, parse_target_date

log = logging.getLogger("yellows_pixel_buddies")

MAX_HISTORY_TURNS_IN_MEMORY = 200   # MemoryManager.history is trimmed to this (REVIEW M21)
MAX_FACTS = 50                      # permanent facts go into EVERY prompt: keep them bounded (REVIEW C5)
MAX_FACT_CHARS = 200

# Set by the app from its configuration section (yellows_pixel_buddies.py) via configure().
GEMINI_MODEL = "gemini-3.5-flash-lite"
ALARMS_ENABLED = False


def configure(gemini_model: str | None = None, alarms_enabled: bool | None = None) -> None:
    global GEMINI_MODEL, ALARMS_ENABLED
    if gemini_model is not None:
        GEMINI_MODEL = gemini_model
    if alarms_enabled is not None:
        ALARMS_ENABLED = bool(alarms_enabled)


def new_item_id(prefix: str) -> str:
    """Collision-free item ID. IDs used to be built from the current second, so items added together shared one
    and edits/deletes hit the wrong item (REVIEW H14)."""
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def fix_duplicate_ids(items: list, prefix: str) -> bool:
    """Give every item after the first with an already-seen (or missing) ID a fresh one. True if anything changed."""
    seen: set[str] = set()
    changed = False
    for item in items:
        if not isinstance(item, dict):
            continue
        iid = str(item.get("id") or "")
        if not iid or iid in seen:
            item["id"] = new_item_id(prefix)
            changed = True
        seen.add(str(item["id"]))
    return changed


class MemoryManager:
    """Manages local session chat logs, long-term facts, and config/API key storage."""

    def __init__(self, data_dir: Path, legacy_dir: Path | None = None) -> None:
        self.data_dir = data_dir
        self.base_dir = data_dir  # Backwards compatibility
        # Old exe-adjacent folder to migrate memory/.env from. None (the default) disables migration,
        # so tests and secondary instances never copy the developer's real memory or API key.
        self._legacy_dir = legacy_dir
        # Read ambiguous numeric dates (05/12/2026) day-first; the pet sets this from its language (REVIEW L8).
        self.day_first_dates: bool = False
        self.memory_dir = data_dir / "memory"
        self.sessions_dir = self.memory_dir / "sessions"
        self.config_path = self.memory_dir / "config.json"
        self.env_path = data_dir / ".env"
        self.facts_path = self.memory_dir / "facts.json"
        self.temp_facts_path = self.memory_dir / "temp_facts.json"
        self.reminders_path = self.memory_dir / "reminders.json"
        self.alarms_path = self.memory_dir / "alarms.json"
        self.goals_path = self.memory_dir / "goals.json"
        self.wallet_path = self.memory_dir / "wallet.json"
        self.token_usage_path = self.memory_dir / "token_usage.json"
        self.curiosity_path = self.memory_dir / "curiosity.json"
        # ONE way to read/write memory files: atomic writes, corrupt files quarantined, never overwritten (REVIEW C6)
        self.on_store_corrupt = None     # callback(path, backup) - the pet tells the user (in character)
        self.store = JsonStore(on_corrupt=self._store_corrupt)

        # Migrate existing memory from local exe folder if switching to AppData
        self._migrate_existing_data()

        # Token usage tracking (session and persistent)
        self.session_prompt_tokens = 0
        self.session_candidates_tokens = 0
        self.session_total_tokens = 0
        self.session_queries = 0
        self.last_prompt_tokens = 0
        self.last_candidates_tokens = 0
        self.last_total_tokens = 0
        self.last_model = GEMINI_MODEL
        self.last_token_timestamp = ""
        self._load_token_stats()

        self._ensure_dirs()
        self._scrub_saved_secrets_once()
        self._generate_new_session_file()
        self.history: list[dict[str, any]] = []
        # Temporary in-memory only storage for immediate ambient dialogue reactions (never saved to disk)
        self.recent_ambient_dialogues: deque[dict[str, any]] = deque(maxlen=4)
        # Temporary in-memory only storage for physical actions, body state & physics events (never saved to disk)
        self.recent_physical_actions: deque[dict[str, any]] = deque(maxlen=12)

    def _store_corrupt(self, path: Path, backup: Path | None) -> None:
        cb = self.on_store_corrupt
        if cb is not None:
            cb(path, backup)

    def _load_json(self, path: Path) -> Any:
        """Parse a memory file. Missing -> FileNotFoundError (as before); corrupt -> quarantined + StoreCorrupt."""
        if not Path(path).exists():
            raise FileNotFoundError(path)
        return self.store.read(path, strict=True)

    def _save_json(self, path: Path, data: Any) -> bool:
        """Atomic write through the store. A file that was corrupt this session is never overwritten."""
        if isinstance(data, str):
            data = json.loads(data)
        if not self.store.write(path, data):
            raise StoreCorrupt(Path(path))
        return True

    def _scrub_saved_secrets_once(self) -> None:
        """Older versions could save the Gemini key inside session files (network error text). Redact it once."""
        marker = self.memory_dir / ".secrets_redacted_v1"
        if marker.exists() or not self.sessions_dir.is_dir():
            return
        fixed = 0
        for f in sessions.session_files(self.sessions_dir):
            try:
                text = f.read_text(encoding="utf-8")
                if not privacy.contains_secret(text):
                    continue
                tmp = f.with_suffix(".json.tmp")
                tmp.write_text(privacy.redact_secrets(text), encoding="utf-8")
                os.replace(tmp, f)
                fixed += 1
            except OSError as err:
                log.debug("Could not scrub %s: %s", f.name, err)
        try:
            marker.write_text("1", encoding="utf-8")
        except OSError as err:
            log.debug("_scrub_saved_secrets_once: ignored %s: %s", type(err).__name__, err)
        if fixed:
            log.info("Redacted a leaked API key from %d old session file(s) (REVIEW M9).", fixed)

    def _migrate_existing_data(self) -> None:
        """If transitioning from local exe directory to AppData, seamlessly copy existing memory."""
        legacy_dir = self._legacy_dir
        if legacy_dir is None:
            return
        try:
            if self.data_dir.resolve() == legacy_dir.resolve():
                return
            local_mem = legacy_dir / "memory"
            if local_mem.is_dir():
                self.memory_dir.mkdir(parents=True, exist_ok=True)
                for f in local_mem.glob("*.*[a-zA-Z0-9]"):
                    target_f = self.memory_dir / f.name
                    if not target_f.exists() and f.is_file():
                        try:
                            shutil.copy2(str(f), str(target_f))
                            log.info("Migrated memory file %s to %s", f.name, target_f)
                        except Exception as e:
                            log.warning("Could not migrate %s: %s", f.name, e)
            local_env = legacy_dir / ".env"
            if local_env.is_file() and not self.env_path.exists():
                shutil.copy2(str(local_env), str(self.env_path))
        except Exception as err:
            log.warning("Memory migration check skipped: %s", err)

    def _append_history(self, turn: dict) -> None:
        """Keep the in-memory history bounded; the session file still has everything (REVIEW M21)."""
        self.history.append(turn)
        if len(self.history) > MAX_HISTORY_TURNS_IN_MEMORY:
            del self.history[:-MAX_HISTORY_TURNS_IN_MEMORY]

    def _generate_new_session_file(self) -> None:
        """Generate a unique session file path for a fresh session."""
        now = datetime.datetime.now()
        base_id = now.strftime("%Y%m%d_%H%M%S")
        # Append-only JSON Lines (REVIEW M21); old session_*.json files stay readable.
        candidate = self.sessions_dir / f"session_{base_id}.jsonl"
        counter = 1
        while candidate.exists() or candidate.with_suffix(".json").exists():
            candidate = self.sessions_dir / f"session_{base_id}_{counter}.jsonl"
            counter += 1
        self._session_id = candidate.stem.replace("session_", "")
        self._session_started_at = now.isoformat()
        self.session_file = candidate

    def _ensure_dirs(self) -> None:
        try:
            self.memory_dir.mkdir(parents=True, exist_ok=True)
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            if JsonStore.remove_stale_temp_files(self.memory_dir):
                log.info("Removed temp files left by an interrupted write in %s", self.memory_dir)
            self.prune_empty_sessions()
            if not self.facts_path.exists():
                default_facts = {
                    "user_name": "Minion",
                    "notes": [],
                }
                self._save_json(self.facts_path, default_facts)
            if not self.temp_facts_path.exists():
                self._save_json(self.temp_facts_path, [])
            else:
                self.get_active_temporary_facts()
            if not self.reminders_path.exists():
                self._save_json(self.reminders_path, [])
            if not self.alarms_path.exists():
                self._save_json(self.alarms_path, [])
            if not self.curiosity_path.exists():
                self._save_json(self.curiosity_path, [])
            if not self.goals_path.exists():
                self._save_json(self.goals_path, [])
        except Exception as err:
            log.warning("Could not initialize memory directories/facts: %s", err)

    def prune_empty_sessions(self) -> int:
        """Prune any historical 0-message empty session files from memory/sessions/.
        Returns count of pruned files."""
        if not self.sessions_dir.exists():
            return 0
        pruned_count = 0
        try:
            for f in sessions.session_files(self.sessions_dir):
                try:
                    size = f.stat().st_size
                    if size == 0:
                        f.unlink(missing_ok=True)
                        pruned_count += 1
                        continue
                    if size <= 160 and not sessions.has_messages(f):   # an empty header-only / "messages": [] file
                        f.unlink(missing_ok=True)
                        pruned_count += 1
                except Exception as err:
                    log.debug("prune_empty_sessions: ignored %s: %s", type(err).__name__, err)
        except Exception as err:
            log.warning("Could not prune empty sessions: %s", err)
        if pruned_count > 0:
            log.info("Pruned %d empty session files from %s", pruned_count, self.sessions_dir)
        return pruned_count

    def _session_header(self) -> dict:
        return {"session_id": self._session_id, "started_at": self._session_started_at}

    def _append_session_message(self, turn: dict) -> None:
        """One appended line per turn instead of rewriting the whole session file (REVIEW M21)."""
        with self.store.lock:
            sessions.append_message(self.session_file, turn, header=self._session_header())

    def _ensure_session_file(self) -> None:
        """Kept for callers: the session file is created lazily by the first appended message."""
        return None

    def get_api_key(self) -> str:
        """Retrieve Gemini API key from environment, .env file, or memory/config.json."""
        env_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if env_key:
            return env_key

        if self.env_path.exists():
            try:
                for line in self.env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("GEMINI_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
            except Exception as err:
                log.debug("get_api_key: ignored %s: %s", type(err).__name__, err)

        # Fallback check in local exe dir .env if running from installed/portable location
        if self._legacy_dir is not None and self._legacy_dir.resolve() != self.data_dir.resolve():
            local_env = self._legacy_dir / ".env"
            if local_env.exists():
                try:
                    for line in local_env.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line.startswith("GEMINI_API_KEY="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val:
                                return val
                except Exception as err:
                    log.debug("get_api_key: ignored %s: %s", type(err).__name__, err)

        if self.config_path.exists():
            try:
                cfg = self._load_json(self.config_path)
                val = cfg.get("gemini_api_key", "").strip()
                if val:
                    return val
            except Exception as err:
                log.debug("get_api_key: ignored %s: %s", type(err).__name__, err)

        # Fallback check in local exe dir memory/config.json
        if self._legacy_dir is not None and self._legacy_dir.resolve() != self.data_dir.resolve():
            local_cfg = self._legacy_dir / "memory" / "config.json"
            if local_cfg.exists():
                try:
                    cfg = json.loads(local_cfg.read_text(encoding="utf-8"))
                    val = cfg.get("gemini_api_key", "").strip()
                    if val:
                        return val
                except Exception as err:
                    log.debug("get_api_key: ignored %s: %s", type(err).__name__, err)

        return ""

    def save_api_key(self, api_key: str) -> None:
        """Save API key to both .env and memory/config.json."""
        api_key = api_key.strip()
        os.environ["GEMINI_API_KEY"] = api_key

        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            env_lines = []
            found = False
            if self.env_path.exists():
                for line in self.env_path.read_text(encoding="utf-8").splitlines():
                    if line.strip().startswith("GEMINI_API_KEY="):
                        env_lines.append(f'GEMINI_API_KEY="{api_key}"')
                        found = True
                    else:
                        env_lines.append(line)
            if not found:
                env_lines.append(f'GEMINI_API_KEY="{api_key}"')
            self.env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        except Exception as err:
            log.debug("Could not update .env: %s", err)

        cfg = {}
        if self.config_path.exists():
            try:
                cfg = self._load_json(self.config_path)
            except Exception as err:
                log.debug("save_api_key: ignored %s: %s", type(err).__name__, err)
        cfg["gemini_api_key"] = api_key
        try:
            self.memory_dir.mkdir(parents=True, exist_ok=True)
            self._save_json(self.config_path, cfg)
        except Exception as err:
            log.warning("Could not update config.json: %s", err)

    def get_user_name(self) -> str:
        """Return the current user preferred name from facts.json or 'Minion' fallback."""
        if self.facts_path.exists():
            try:
                facts = self._load_json(self.facts_path)
                name = facts.get("user_name", "").strip()
                if name:
                    return name
            except Exception as err:
                log.debug("get_user_name: ignored %s: %s", type(err).__name__, err)
        return "Minion"

    def set_user_name(self, name: str) -> bool:
        """Set user preferred name/nickname in facts.json."""
        clean_name = name.strip()
        if not clean_name:
            return False
        data = {"user_name": "Minion", "notes": []}
        if self.facts_path.exists():
            try:
                data = self._load_json(self.facts_path)
            except Exception as err:
                log.debug("set_user_name: ignored %s: %s", type(err).__name__, err)
        if data.get("user_name") == clean_name:
            return False
        data["user_name"] = clean_name
        if "notes" not in data or not isinstance(data["notes"], list):
            data["notes"] = []
        try:
            self.memory_dir.mkdir(parents=True, exist_ok=True)
            self._save_json(self.facts_path, data)
            log.info("Updated user preferred name in %s to: %s", self.facts_path, clean_name)
            return True
        except Exception as err:
            log.warning("Could not save user_name to facts: %s", err)
            return False

    def get_long_term_facts(self) -> str:
        """Read facts.json to inject into system prompt with clear priority between primary name and notes."""
        if not self.facts_path.exists() and self._legacy_dir is not None:
            local_facts = self._legacy_dir / "memory" / "facts.json"
            if local_facts.is_file():
                try:
                    self.facts_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(local_facts), str(self.facts_path))
                except Exception as err:
                    log.debug("get_long_term_facts: ignored %s: %s", type(err).__name__, err)
        if self.facts_path.exists():
            try:
                facts = self._load_json(self.facts_path)
                lines = []
                user_name = facts.get("user_name", "").strip()
                notes = facts.get("notes") or facts.get("facts") or []

                if user_name and user_name.lower() != "minion":
                    lines.append(f"- PRIMARY USER NAME / NICKNAME: \"{user_name}\"")
                    lines.append(
                        f"  * ADDRESS RULE: When speaking to the user, address them MAINLY by \"{user_name}\" (roughly 75-80% of the time). "
                        f"Weave it naturally into your dramatic, tsundere banter (e.g., \"* {user_name}, you minion!\", \"* Listen here, {user_name}!\")."
                    )
                else:
                    lines.append("- Primary User Reference: \"minion\" (User has not set a custom primary nickname).")

                if isinstance(notes, list) and notes:
                    lines.append("- FACT NOTES & SECONDARY NICKNAMES / ALIASES:")
                    lines.append(
                        "  * ADDRESS RULE: If any alternative nicknames, titles, or pet names appear in the notes below, "
                        "you may call the user by those secondary nicknames SOMETIMES for playful teasing or variety (roughly 20-25% of the time). "
                        f"However, \"{user_name or 'Minion'}\" remains your primary name for them!"
                    )
                    for n in notes:
                        lines.append(f"  * {n}")
                return "\n".join(lines)
            except Exception as err:
                log.debug("get_long_term_facts: ignored %s: %s", type(err).__name__, err)
        return ""

    def add_fact(self, fact_text: str, source: str = "chat") -> bool:
        """Permanently store a new fact about the user or companion in facts.json.

        Capped at MAX_FACTS notes of MAX_FACT_CHARS each (facts go into every prompt); facts that came from a turn
        with a screenshot/image are recorded under "note_sources" so they can be reviewed (REVIEW C5).
        """
        fact_text = fact_text.strip()[:MAX_FACT_CHARS].rstrip()
        if not fact_text:
            return False
        data = {}
        if self.facts_path.exists():
            try:
                data = self._load_json(self.facts_path)
            except Exception as err:
                log.debug("add_fact: ignored %s: %s", type(err).__name__, err)
        notes = data.setdefault("notes", [])
        if not isinstance(notes, list):
            notes = []
            data["notes"] = notes
        if any(n.strip().lower() == fact_text.lower() for n in notes):
            return False
        if len(notes) >= MAX_FACTS:
            log.warning("Not saving fact: the limit of %d permanent facts is reached.", MAX_FACTS)
            return False
        notes.append(fact_text)
        if source != "chat":
            data.setdefault("note_sources", {})[fact_text] = source
        try:
            self._save_json(self.facts_path, data)
            log.info("Saved new permanent fact: %s", fact_text)
            return True
        except Exception as err:
            log.warning("Could not save fact: %s", err)
            return False

    def get_active_temporary_facts(self, max_age_hours: float = 48.0) -> list[dict]:
        """Read temporary facts from temp_facts.json, auto-prune anything older than 48 hours (2 days), and return active ones."""
        if not self.temp_facts_path.exists() or self.temp_facts_path.stat().st_size == 0:
            return []
        try:
            raw = self._load_json(self.temp_facts_path)
            if not isinstance(raw, list):
                return []
        except Exception as err:
            log.warning("Could not read temp_facts.json: %s", err)
            return []

        now = datetime.datetime.now()
        active: list[dict] = []
        changed = False

        for item in raw:
            if not isinstance(item, dict):
                continue
            created_str = item.get("created_at")
            if not created_str:
                active.append(item)
                continue
            try:
                dt = datetime.datetime.fromisoformat(created_str)
                age_hours = (now - dt).total_seconds() / 3600.0
                if age_hours <= max_age_hours:
                    active.append(item)
                else:
                    changed = True  # Prune expired temporary fact (> 48 hours)
            except Exception:
                active.append(item)

        if fix_duplicate_ids(active, "tf"):
            changed = True
        if changed or len(active) != len(raw):
            try:
                self._save_json(self.temp_facts_path, active)
            except Exception as err:
                log.warning("Could not prune temp_facts.json: %s", err)

        return active

    def get_temporary_facts_prompt(self, numbered: bool = True) -> str:
        """Format active 2-day temporary facts with age/expiry hints for prompt injection and user viewing."""
        active = self.get_active_temporary_facts()
        if not active:
            return ""
        now = datetime.datetime.now()
        lines = []
        for idx, item in enumerate(active, 1):
            text = item.get("text", "").strip()
            created_str = item.get("created_at", "")
            time_label = ""
            if created_str:
                try:
                    dt = datetime.datetime.fromisoformat(created_str)
                    age_hours = (now - dt).total_seconds() / 3600.0
                    remaining_hours = max(1, int(round(48.0 - age_hours)))
                    if dt.date() == now.date():
                        day_str = f"Today {dt.strftime('%I:%M %p')}"
                    elif (now.date() - dt.date()).days == 1:
                        day_str = f"Yesterday {dt.strftime('%I:%M %p')}"
                    else:
                        day_str = dt.strftime("%b %d, %I:%M %p")
                    time_label = f" (Added {day_str} | expires in ~{remaining_hours}h)"
                except Exception as err:
                    log.debug("get_temporary_facts_prompt: ignored %s: %s", type(err).__name__, err)
            prefix = f"{idx}. " if numbered else "- "
            lines.append(f"{prefix}{text}{time_label}")
        return "\n".join(lines)

    def add_temporary_fact(self, fact_text: str, source: str = "pink", ttl_hours: float = 48.0) -> bool:
        """Store a temporary situational fact about the user or situation that automatically prunes after 48h (2 days)."""
        clean_text = fact_text.strip()
        if not clean_text:
            return False
        active = self.get_active_temporary_facts(max_age_hours=ttl_hours)
        # Deduplication check
        if any(item.get("text", "").strip().lower() == clean_text.lower() for item in active):
            return False

        # Soft cap to prevent prompt pollution: retain up to 8 active temporary facts
        if len(active) >= 8:
            active.pop(0)

        now_dt = datetime.datetime.now()
        item = {
            "id": new_item_id("tf"),
            "created_at": now_dt.isoformat(),
            "text": clean_text,
            "source": source,
        }
        active.append(item)
        try:
            self.memory_dir.mkdir(parents=True, exist_ok=True)
            self._save_json(self.temp_facts_path, active)
            log.info("Saved new temporary fact (2 days): %s (source: %s)", clean_text, source)
            return True
        except Exception as err:
            log.warning("Could not save temporary fact: %s", err)
            return False

    def _find_temp_fact_index(self, active: list[dict], identifier: str | int) -> int | None:
        """Helper to find the 0-based index in active temporary facts by 1-based index, ID, or text match."""
        if not active or identifier is None:
            return None

        if isinstance(identifier, int):
            idx = identifier - 1
            return idx if 0 <= idx < len(active) else None

        clean = str(identifier).strip()
        if not clean:
            return None

        target_str = clean[1:] if clean.startswith("#") else clean
        if target_str.isdigit():
            idx = int(target_str) - 1
            if 0 <= idx < len(active):
                return idx

        clean_lower = clean.lower()

        # 1. Exact match on id
        for idx, item in enumerate(active):
            if item.get("id", "").lower() == clean_lower:
                return idx

        # 2. Exact match on text
        for idx, item in enumerate(active):
            if item.get("text", "").strip().lower() == clean_lower:
                return idx

        # 3. Substring match on text
        for idx, item in enumerate(active):
            if clean_lower in item.get("text", "").strip().lower():
                return idx

        return None

    def delete_temporary_fact(self, identifier: str | int) -> tuple[bool, str]:
        """Delete an active temporary fact by 1-based index, ID, or text match.
        Returns (success, deleted_text)."""
        active = self.get_active_temporary_facts()
        idx = self._find_temp_fact_index(active, identifier)
        if idx is None:
            return False, ""
        deleted_item = active.pop(idx)
        deleted_text = deleted_item.get("text", "")
        try:
            self._save_json(self.temp_facts_path, active)
            log.info("Deleted temporary fact: %s", deleted_text)
            return True, deleted_text
        except Exception as err:
            log.warning("Could not delete temporary fact: %s", err)
            return False, ""

    def clear_all_temporary_facts(self) -> int:
        """Clear all active temporary facts. Returns count of deleted items."""
        active = self.get_active_temporary_facts()
        count = len(active)
        try:
            self._save_json(self.temp_facts_path, [])
            log.info("Cleared all temporary facts (%d items)", count)
            return count
        except Exception as err:
            log.warning("Could not clear temporary facts: %s", err)
            return 0

    def get_active_curiosity_threads(self, max_age_days: float = 7.0) -> list[dict]:
        """Read curiosity threads from curiosity.json, auto-prune stale threads (> 7 days), and return active ones."""
        if not hasattr(self, "curiosity_path") or not self.curiosity_path.exists() or self.curiosity_path.stat().st_size == 0:
            return []
        try:
            raw = self._load_json(self.curiosity_path)
            if not isinstance(raw, list):
                return []
        except Exception as err:
            log.warning("Could not read curiosity.json: %s", err)
            return []

        now_dt = datetime.datetime.now()
        active = []
        changed = False
        for item in raw:
            if not isinstance(item, dict):
                continue
            created_str = item.get("created_at")
            if not created_str:
                continue
            try:
                created_dt = datetime.datetime.fromisoformat(created_str)
                age_days = (now_dt - created_dt).total_seconds() / 86400.0
                if age_days <= max_age_days and not item.get("resolved", False):
                    active.append(item)
                else:
                    changed = True
            except Exception:
                continue

        if fix_duplicate_ids(active, "cur"):
            changed = True
        if changed:
            try:
                self._save_json(self.curiosity_path, active)
            except Exception as err:
                log.warning("Could not prune curiosity.json: %s", err)
        return active

    def add_curiosity_thread(self, topic: str, context: str = "", source: str = "observation") -> bool:
        """Store a topic/thread Pink is curious about (max 8 active). Deduplicates by topic."""
        clean_topic = topic.strip()
        if not clean_topic:
            return False
        active = self.get_active_curiosity_threads()
        if any(item.get("topic", "").strip().lower() == clean_topic.lower() for item in active):
            return False

        if len(active) >= 8:
            active.pop(0)

        now_dt = datetime.datetime.now()
        item = {
            "id": new_item_id("cur"),
            "created_at": now_dt.isoformat(),
            "topic": clean_topic,
            "context": context.strip() if context else "",
            "source": source,
            "asked_count": 0,
            "last_asked_time": 0.0,
            "resolved": False,
        }
        active.append(item)
        try:
            self._save_json(self.curiosity_path, active)
            log.info("Recorded curiosity thread: %s (source: %s)", clean_topic, source)
            return True
        except Exception as err:
            log.warning("Could not save curiosity thread: %s", err)
            return False

    def record_curiosity_asked(self, thread_id: str) -> None:
        """Increment asked count for a curiosity thread."""
        active = self.get_active_curiosity_threads()
        changed = False
        for item in active:
            if item.get("id") == thread_id or thread_id in item.get("topic", "").lower():
                item["asked_count"] = item.get("asked_count", 0) + 1
                item["last_asked_time"] = time.time()
                changed = True
                break
        if changed:
            try:
                self._save_json(self.curiosity_path, active)
            except Exception as err:
                log.warning("Could not update curiosity asked state: %s", err)

    def resolve_curiosity_thread(self, identifier: str) -> tuple[bool, str]:
        """Resolve/remove an active curiosity thread by index, id, or topic substring."""
        active = self.get_active_curiosity_threads()
        clean = identifier.strip().lower()
        target_idx = None
        if clean.isdigit():
            val = int(clean) - 1
            if 0 <= val < len(active):
                target_idx = val
        if target_idx is None:
            for idx, item in enumerate(active):
                if item.get("id", "").lower() == clean or clean in item.get("topic", "").lower():
                    target_idx = idx
                    break
        if target_idx is None:
            return False, ""
        resolved_item = active.pop(target_idx)
        resolved_topic = resolved_item.get("topic", "")
        try:
            self._save_json(self.curiosity_path, active)
            log.info("Resolved curiosity thread: %s", resolved_topic)
            return True, resolved_topic
        except Exception as err:
            log.warning("Could not resolve curiosity thread: %s", err)
            return False, ""

    def clear_all_curiosity_threads(self) -> int:
        """Clear all curiosity threads."""
        active = self.get_active_curiosity_threads()
        count = len(active)
        try:
            self._save_json(self.curiosity_path, [])
            return count
        except Exception as err:
            log.warning("Could not clear curiosity threads: %s", err)
            return 0

    def get_curiosity_prompt(self, numbered: bool = True) -> str:
        """Format active curiosity threads for Gemini prompt injection."""
        active = self.get_active_curiosity_threads()
        if not active:
            return ""
        lines = []
        for i, item in enumerate(active[:5], 1):
            top = item.get("topic", "")
            ctx = item.get("context", "")
            extra = f" ({ctx})" if ctx else ""
            prefix = f"{i}. " if numbered else "- "
            lines.append(f"{prefix}{top}{extra}")
        return "\n".join(lines)

    def get_active_reminders(self, max_age_days: int = 30) -> list[dict]:
        """Read reminders from reminders.json, auto-prune anything older than 30 days, and return active ones."""
        if not self.reminders_path.exists() or self.reminders_path.stat().st_size == 0:
            return []
        try:
            raw = self._load_json(self.reminders_path)
            if not isinstance(raw, list):
                return []
        except Exception as err:
            log.warning("Could not read reminders.json: %s", err)
            return []

        now = datetime.datetime.now()
        active = []
        changed = False

        for item in raw:
            if not isinstance(item, dict):
                continue
            created_str = item.get("created_at")
            if not created_str:
                active.append(item)
                continue
            try:
                dt = datetime.datetime.fromisoformat(created_str)
                age_days = (now - dt).total_seconds() / 86400.0
                if age_days <= max_age_days:
                    active.append(item)
                else:
                    changed = True  # Prune expired reminder (> 30 days)
            except Exception:
                active.append(item)

        if fix_duplicate_ids(active, "rem"):
            changed = True
        if changed or len(active) != len(raw):
            try:
                self._save_json(self.reminders_path, active)
            except Exception as err:
                log.warning("Could not prune reminders.json: %s", err)

        return active

    def get_reminders_prompt(self, numbered: bool = True) -> str:
        """Format active reminders into a concise numbered list for prompt injection and user viewing."""
        active = self.get_active_reminders()
        if not active:
            return ""
        lines = []
        for idx, r in enumerate(active, 1):
            text = r.get("text", "").strip()
            created_str = r.get("created_at", "")
            date_label = ""
            if created_str:
                try:
                    dt = datetime.datetime.fromisoformat(created_str)
                    date_label = f" (Added {dt.strftime('%b %d, %Y')})"
                except Exception as err:
                    log.debug("get_reminders_prompt: ignored %s: %s", type(err).__name__, err)
            prefix = f"{idx}. " if numbered else "- "
            lines.append(f"{prefix}{text}{date_label}")
        return "\n".join(lines)

    def add_reminder(self, reminder_text: str) -> bool:
        """Add a temporary reminder (auto-deletes after 30 days)."""
        reminder_text = reminder_text.strip()
        if not reminder_text:
            return False
        active = self.get_active_reminders()
        if any(r.get("text", "").strip().lower() == reminder_text.lower() for r in active):
            return False
        now_dt = datetime.datetime.now()
        item = {
            "id": new_item_id("rem"),
            "created_at": now_dt.isoformat(),
            "text": reminder_text,
        }
        active.append(item)
        try:
            self._save_json(self.reminders_path, active)
            log.info("Saved new reminder: %s", reminder_text)
            return True
        except Exception as err:
            log.warning("Could not save reminder: %s", err)
            return False

    def _find_reminder_index(self, active: list[dict], identifier: str | int) -> int | None:
        """Helper to find the 0-based index in active reminders by 1-based index, ID, or text match."""
        if not active or identifier is None:
            return None

        if isinstance(identifier, int):
            idx = identifier - 1
            return idx if 0 <= idx < len(active) else None

        clean = str(identifier).strip()
        if not clean:
            return None

        target_str = clean[1:] if clean.startswith("#") else clean
        if target_str.isdigit():
            idx = int(target_str) - 1
            if 0 <= idx < len(active):
                return idx

        clean_lower = clean.lower()

        # 1. Exact match on id
        for idx, r in enumerate(active):
            if r.get("id", "").lower() == clean_lower:
                return idx

        # 2. Exact match on text
        for idx, r in enumerate(active):
            if r.get("text", "").strip().lower() == clean_lower:
                return idx

        # 3. Substring match on text
        for idx, r in enumerate(active):
            if clean_lower in r.get("text", "").strip().lower():
                return idx

        return None

    def delete_reminder(self, identifier: str | int) -> tuple[bool, str]:
        """Delete an active reminder by 1-based index, ID, or text match.
        Returns (success, deleted_text)."""
        active = self.get_active_reminders()
        idx = self._find_reminder_index(active, identifier)
        if idx is None:
            return False, ""
        deleted = active.pop(idx)
        deleted_text = deleted.get("text", "").strip()
        try:
            self._save_json(self.reminders_path, active)
            log.info("Deleted reminder [%s]: %s", deleted.get("id"), deleted_text)
            return True, deleted_text
        except Exception as err:
            log.warning("Could not delete reminder: %s", err)
            return False, ""

    def edit_reminder(self, identifier: str | int, new_text: str) -> tuple[bool, str]:
        """Edit an active reminder by 1-based index, ID, or text match.
        Returns (success, old_text)."""
        clean_new = new_text.strip()
        if not clean_new:
            return False, ""
        active = self.get_active_reminders()
        idx = self._find_reminder_index(active, identifier)
        if idx is None:
            return False, ""
        old_text = active[idx].get("text", "").strip()
        active[idx]["text"] = clean_new
        active[idx]["updated_at"] = datetime.datetime.now().isoformat()
        try:
            self._save_json(self.reminders_path, active)
            log.info("Edited reminder [%s]: '%s' -> '%s'", active[idx].get("id"), old_text, clean_new)
            return True, old_text
        except Exception as err:
            log.warning("Could not edit reminder: %s", err)
            return False, ""

    def clear_all_reminders(self) -> int:
        """Clear all active reminders. Returns count of removed reminders."""
        active = self.get_active_reminders()
        count = len(active)
        try:
            self._save_json(self.reminders_path, [])
            log.info("Cleared all %d reminders.", count)
            return count
        except Exception as err:
            log.warning("Could not clear reminders: %s", err)
            return 0

    def _atomic_write_json(self, path: Path, data: Any) -> bool:
        """Atomically write JSON data (kept for callers; delegates to the store)."""
        try:
            return self._save_json(path, data)
        except (StoreCorrupt, OSError) as err:
            log.warning("Could not write %s: %s", Path(path).name, err)
            return False

    def _normalize_goal_entry(self, raw: dict | str, legacy_mtime_iso: str | None = None) -> dict:
        """Normalize a goal entry to the rich schema with backward compatibility."""
        now_iso = datetime.datetime.now().isoformat(timespec="seconds")
        if isinstance(raw, str):
            text = raw.strip()
            raw = {"text": text}
        elif not isinstance(raw, dict):
            raw = {"text": str(raw)}

        text = raw.get("text", "").strip()
        goal_id = raw.get("id")
        if not goal_id or not isinstance(goal_id, str):
            goal_id = f"goal_{uuid.uuid4().hex[:8]}"

        created_at = raw.get("created_at")
        if not created_at:
            created_at = legacy_mtime_iso  # May be None for legacy goals without timestamps

        target_date = parse_target_date(raw.get("target_date"), day_first=self.day_first_dates) if raw.get("target_date") else None

        notes = []
        for n in raw.get("progress_notes", []):
            if isinstance(n, dict) and "note" in n:
                notes.append({"timestamp": n.get("timestamp") or now_iso, "note": str(n["note"])[:120]})
            elif isinstance(n, str) and n.strip():
                notes.append({"timestamp": now_iso, "note": n.strip()[:120]})

        stats = raw.get("stats", {})
        if not isinstance(stats, dict):
            stats = {}

        return {
            "id": goal_id,
            "text": text,
            "created_at": created_at,
            "target_date": target_date,
            "last_checked_at": raw.get("last_checked_at"),
            "last_asked_at": raw.get("last_asked_at"),
            "ignored_count": max(0, int(raw.get("ignored_count", 0))),
            "progress_notes": notes[-10:],
            "completed": bool(raw.get("completed", False)),
            "stats": {
                "mentions_count": max(0, int(stats.get("mentions_count", 0))),
                "engagements_count": max(0, int(stats.get("engagements_count", 0))),
            },
        }

    def _load_raw_goals(self) -> list[dict]:
        """Read and normalize all goal entries from goals.json."""
        if not self.goals_path.exists() or self.goals_path.stat().st_size == 0:
            return []
        try:
            mtime_iso = datetime.datetime.fromtimestamp(self.goals_path.stat().st_mtime).isoformat(timespec="seconds")
            raw = self._load_json(self.goals_path)
            if not isinstance(raw, list):
                return []
            normalized = []
            needs_save = False
            for item in raw:
                norm = self._normalize_goal_entry(item, legacy_mtime_iso=mtime_iso)
                if norm != item:
                    needs_save = True
                normalized.append(norm)
            if needs_save:
                self.save_goals(normalized)
            return normalized
        except Exception as err:
            log.warning("Could not read goals.json: %s", err)
            return []

    def save_goals(self, goals: list[dict]) -> bool:
        """Atomically save goals list to goals.json."""
        return self._atomic_write_json(self.goals_path, goals)

    def get_active_goals(self) -> list[dict]:
        """Read active personal milestones and goals from goals.json."""
        return [g for g in self._load_raw_goals() if not g.get("completed", False)]

    def get_goals_prompt(self, numbered: bool = True) -> str:
        """Format active goals into a rich prompt block with temporal context and recent progress notes."""
        active = self.get_active_goals()
        if not active:
            return ""
        today = datetime.date.today()
        now = datetime.datetime.now()
        lines = []

        for idx, g in enumerate(active, 1):
            text = g.get("text", "").strip()
            gid = g.get("id", f"goal_{idx}")
            val = evaluate_goal_value(text)
            prefix = f"{idx}. " if numbered else "- "
            
            lines.append(f'{prefix}[ID: {gid}] "{text}" (Bounty: +P$ {val:02d} upon completion)')

            meta_parts = []
            created_ts = g.get("created_at")
            if created_ts:
                try:
                    c_dt = datetime.datetime.fromisoformat(created_ts)
                    days_ago = (now - c_dt).days
                    if days_ago == 0:
                        meta_parts.append("Set: Today")
                    elif days_ago == 1:
                        meta_parts.append("Set: Yesterday")
                    elif days_ago > 1:
                        meta_parts.append(f"Set: {days_ago} days ago")
                except Exception as err:
                    log.debug("get_goals_prompt: ignored %s: %s", type(err).__name__, err)

            target_d = g.get("target_date")
            if target_d:
                try:
                    d_obj = datetime.date.fromisoformat(target_d)
                    days_left = (d_obj - today).days
                    if days_left > 0:
                        meta_parts.append(f"Deadline: {target_d} ({days_left}d left)")
                    elif days_left == 0:
                        meta_parts.append(f"Deadline: TODAY ({target_d})")
                    else:
                        meta_parts.append(f"Deadline: OVERDUE ({abs(days_left)}d overdue)")
                except Exception:
                    meta_parts.append(f"Deadline: {target_d}")

            checked_ts = g.get("last_checked_at")
            if checked_ts:
                try:
                    chk_dt = datetime.datetime.fromisoformat(checked_ts)
                    chk_days = (now - chk_dt).days
                    if chk_days == 0:
                        meta_parts.append("Last Check-in: Today")
                    elif chk_days == 1:
                        meta_parts.append("Last Check-in: Yesterday")
                    else:
                        meta_parts.append(f"Last Check-in: {chk_days}d ago")
                except Exception as err:
                    log.debug("get_goals_prompt: ignored %s: %s", type(err).__name__, err)
            else:
                meta_parts.append("Last Check-in: Not yet")

            if meta_parts:
                lines.append(f"   - {' | '.join(meta_parts)}")

            # Inject at most the last 2 progress notes capped at 80 chars each
            notes = g.get("progress_notes", [])
            if notes:
                lines.append("   - Recent Progress:")
                for n_entry in notes[-2:]:
                    ts = n_entry.get("timestamp", "")
                    n_txt = n_entry.get("note", "").strip()
                    try:
                        dt_n = datetime.datetime.fromisoformat(ts)
                        d_str = dt_n.strftime("%b %d")
                    except Exception:
                        d_str = "Recent"
                    lines.append(f"     * [{d_str}] {n_txt[:80]}")

        return "\n".join(lines)

    def add_goal(self, goal_text: str, target_date: str | None = None) -> bool:
        """Add a new personal milestone/goal."""
        goal_text = goal_text.strip()
        if not goal_text:
            return False
        goals = self._load_raw_goals()
        if any(g.get("text", "").strip().lower() == goal_text.lower() and not g.get("completed") for g in goals):
            return False
        
        parsed_target = parse_target_date(target_date, day_first=self.day_first_dates) if target_date else None
        now_iso = datetime.datetime.now().isoformat(timespec="seconds")
        new_g = {
            "id": f"goal_{uuid.uuid4().hex[:8]}",
            "text": goal_text,
            "created_at": now_iso,
            "target_date": parsed_target,
            "last_checked_at": None,
            "last_asked_at": None,
            "ignored_count": 0,
            "progress_notes": [],
            "completed": False,
            "stats": {"mentions_count": 0, "engagements_count": 0}
        }
        goals.append(new_g)
        ok = self.save_goals(goals)
        if ok:
            log.info("Saved new goal [%s]: %s (target_date=%s)", new_g["id"], goal_text, parsed_target)
        return ok

    def _find_goal_index(self, active: list[dict], identifier: str | int) -> int | None:
        """Helper to find 0-based index in active goals by 1-based index, ID, or text match."""
        if not active or identifier is None:
            return None
        if isinstance(identifier, int):
            idx = identifier - 1
            return idx if 0 <= idx < len(active) else None

        clean = str(identifier).strip()
        if not clean:
            return None
        target_str = clean[1:] if clean.startswith("#") else clean
        if target_str.isdigit():
            idx = int(target_str) - 1
            if 0 <= idx < len(active):
                return idx

        clean_lower = clean.lower()
        # 1. Exact match on id
        for idx, g in enumerate(active):
            if g.get("id", "").lower() == clean_lower:
                return idx
        # 2. Exact match on text
        for idx, g in enumerate(active):
            if g.get("text", "").strip().lower() == clean_lower:
                return idx
        # 3. Unambiguous substring match on text
        matches = [idx for idx, g in enumerate(active) if clean_lower in g.get("text", "").strip().lower()]
        if len(matches) == 1:
            return matches[0]
        return None

    def delete_goal(self, identifier: str | int) -> tuple[bool, str]:
        """Delete an active goal by 1-based index, ID, or text match. Returns (success, deleted_text)."""
        goals = self._load_raw_goals()
        active = [g for g in goals if not g.get("completed")]
        idx = self._find_goal_index(active, identifier)
        if idx is None:
            return False, ""
        target_id = active[idx].get("id")
        deleted_text = active[idx].get("text", "").strip()
        goals = [g for g in goals if g.get("id") != target_id]
        try:
            self.save_goals(goals)
            log.info("Deleted goal [%s]: %s", target_id, deleted_text)
            return True, deleted_text
        except Exception as err:
            log.warning("Could not delete goal: %s", err)
            return False, ""

    def complete_goal(self, identifier: str | int) -> tuple[bool, str, int]:
        """Complete an active goal, archive it, and award Pink Dollars.
        Returns (success, goal_text, awarded_dollars)."""
        goals = self._load_raw_goals()
        active = [g for g in goals if not g.get("completed")]
        idx = self._find_goal_index(active, identifier)
        if idx is None:
            return False, "", 0
        target_g = active[idx]
        target_id = target_g.get("id")
        goal_text = target_g.get("text", "").strip()
        val = evaluate_goal_value(goal_text)
        
        # Mark completed rather than destroying records
        for g in goals:
            if g.get("id") == target_id:
                g["completed"] = True
                g["completed_at"] = datetime.datetime.now().isoformat(timespec="seconds")
                break
        
        try:
            self.save_goals(goals)
            new_bal = self.award_pink_dollars(val)
            log.info("Completed goal [%s] '%s'! Awarded P$ %d (new balance: P$ %d)", target_id, goal_text, val, new_bal)
            return True, goal_text, val
        except Exception as err:
            log.warning("Could not complete goal: %s", err)
            return False, "", 0

    def update_goal_progress(self, identifier: str | int, note: str) -> tuple[bool, str, dict | None]:
        """Log a micro-milestone progress note on an active goal."""
        goals = self._load_raw_goals()
        active = [g for g in goals if not g.get("completed")]
        idx = self._find_goal_index(active, identifier)
        if idx is None:
            return False, "", None
        
        target_g = active[idx]
        now_iso = datetime.datetime.now().isoformat(timespec="seconds")
        clean_note = note.strip()[:120]
        target_g.setdefault("progress_notes", []).append({"timestamp": now_iso, "note": clean_note})
        target_g["progress_notes"] = target_g["progress_notes"][-10:]
        target_g["last_checked_at"] = now_iso
        target_g["ignored_count"] = 0
        stats = target_g.setdefault("stats", {"mentions_count": 0, "engagements_count": 0})
        stats["engagements_count"] = int(stats.get("engagements_count", 0)) + 1
        
        self.save_goals(goals)
        log.info("[GoalEngine] Updated goal [%s] progress: %s", target_g.get("id"), clean_note)
        return True, target_g["text"], target_g

    def set_goal_deadline(self, identifier: str | int, target_date_str: str | None) -> tuple[bool, str, str | None]:
        """Set or clear a target completion deadline for a goal."""
        goals = self._load_raw_goals()
        active = [g for g in goals if not g.get("completed")]
        idx = self._find_goal_index(active, identifier)
        if idx is None:
            return False, "", None
        
        target_g = active[idx]
        parsed = parse_target_date(target_date_str, day_first=self.day_first_dates) if target_date_str else None
        target_g["target_date"] = parsed
        self.save_goals(goals)
        log.info("[GoalEngine] Set goal [%s] deadline to %s", target_g.get("id"), parsed)
        return True, target_g["text"], parsed

    def record_goal_asked(self, goal_id: str) -> None:
        """Record that Pink initiated an ask about goal_id.
        If the prior ask was never engaged with, increments ignored_count mechanically.
        """
        goals = self._load_raw_goals()
        now_iso = datetime.datetime.now().isoformat(timespec="seconds")
        changed = False
        for g in goals:
            if g.get("id") == goal_id:
                prev_asked = g.get("last_asked_at")
                prev_checked = g.get("last_checked_at")
                if prev_asked:
                    if not prev_checked or prev_checked < prev_asked:
                        g["ignored_count"] = int(g.get("ignored_count", 0)) + 1
                        log.info("[GoalEngine] User ignored prior ask for goal [%s]. Ignored count now: %d", goal_id, g["ignored_count"])
                g["last_asked_at"] = now_iso
                stats = g.setdefault("stats", {"mentions_count": 0, "engagements_count": 0})
                stats["mentions_count"] = int(stats.get("mentions_count", 0)) + 1
                changed = True
                break
        if changed:
            self.save_goals(goals)

    def record_goal_engagement(self, goal_id: str | None = None) -> bool:
        """Record that the user engaged with a goal. Resets ignored_count to 0."""
        goals = self._load_raw_goals()
        now_iso = datetime.datetime.now().isoformat(timespec="seconds")
        matched = False
        for g in goals:
            if goal_id is None or g.get("id") == goal_id:
                g["last_checked_at"] = now_iso
                g["ignored_count"] = 0
                stats = g.setdefault("stats", {"mentions_count": 0, "engagements_count": 0})
                stats["engagements_count"] = int(stats.get("engagements_count", 0)) + 1
                matched = True
                if goal_id is not None:
                    break
        if matched:
            self.save_goals(goals)
            log.info("[GoalEngine] Recorded user engagement for goal [%s]. Ignored count reset.", goal_id)
        return matched

    def get_stale_goal_candidate(self) -> dict | None:
        """Find the most urgent stale goal that needs check-in, or None if all fresh or snoozed."""
        if self.is_goal_coaching_snoozed():
            return None
        active = self.get_active_goals()
        if not active:
            return None
        
        now = datetime.datetime.now()
        today = now.date()
        stale_candidates = []

        for g in active:
            target_d = g.get("target_date")
            threshold_hours = 48.0
            urgency_weight = 1.0

            if target_d:
                try:
                    d_obj = datetime.date.fromisoformat(target_d)
                    days_until = (d_obj - today).days
                    if days_until < 0:
                        threshold_hours = 12.0
                        urgency_weight = 4.0
                    elif days_until <= 3:
                        threshold_hours = 12.0
                        urgency_weight = 3.0
                    elif days_until <= 7:
                        threshold_hours = 24.0
                        urgency_weight = 2.0
                    else:
                        threshold_hours = 48.0
                        urgency_weight = 1.2
                except Exception as err:
                    log.debug("get_stale_goal_candidate: ignored %s: %s", type(err).__name__, err)
            
            ign = int(g.get("ignored_count", 0))
            if ign > 0:
                threshold_hours += min(48.0, 12.0 * ign)
            
            ref_ts = g.get("last_checked_at") or g.get("created_at")
            if ref_ts:
                try:
                    ref_dt = datetime.datetime.fromisoformat(ref_ts)
                    elapsed_hours = (now - ref_dt).total_seconds() / 3600.0
                except Exception:
                    elapsed_hours = 999.0
            else:
                elapsed_hours = 999.0

            last_asked = g.get("last_asked_at")
            if last_asked:
                try:
                    last_asked_dt = datetime.datetime.fromisoformat(last_asked)
                    asked_elapsed = (now - last_asked_dt).total_seconds() / 3600.0
                    min_ask_gap = 6.0 if ign == 0 else min(48.0, 12.0 * ign)
                    if asked_elapsed < min_ask_gap:
                        continue
                except Exception as err:
                    log.debug("get_stale_goal_candidate: ignored %s: %s", type(err).__name__, err)

            if elapsed_hours >= threshold_hours:
                stale_candidates.append((urgency_weight * (elapsed_hours / threshold_hours), g))

        if not stale_candidates:
            return None

        stale_candidates.sort(key=lambda x: x[0], reverse=True)
        return stale_candidates[0][1]

    def get_goal_coaching_config(self) -> dict:
        """Get goal coaching configuration (mode, snooze_until, ritual dates)."""
        defaults = {
            "mode": "royal",
            "snooze_until": None,
            "last_morning_date": None,
            "last_evening_date": None
        }
        if self.config_path.exists():
            try:
                data = self._load_json(self.config_path)
                cfg = data.get("goal_coaching", {})
                if isinstance(cfg, dict):
                    defaults.update(cfg)
            except Exception as e:
                log.warning("Could not load goal_coaching from %s: %s", self.config_path, e)
        return defaults

    def set_goal_coaching_config(self, updates: dict) -> bool:
        """Update goal coaching configuration in config.json."""
        data = {}
        if self.config_path.exists():
            try:
                data = self._load_json(self.config_path)
            except Exception as err:
                log.debug("set_goal_coaching_config: ignored %s: %s", type(err).__name__, err)
        curr = data.get("goal_coaching", {})
        if not isinstance(curr, dict):
            curr = {}
        curr.update(updates)
        data["goal_coaching"] = curr
        return self._atomic_write_json(self.config_path, data)

    def is_goal_coaching_snoozed(self) -> bool:
        """Check if goal coaching is currently snoozed."""
        cfg = self.get_goal_coaching_config()
        if cfg.get("mode") == "snooze":
            snooze_until = cfg.get("snooze_until")
            if snooze_until:
                try:
                    dt = datetime.datetime.fromisoformat(snooze_until)
                    if datetime.datetime.now() < dt:
                        return True
                except Exception as err:
                    log.debug("is_goal_coaching_snoozed: ignored %s: %s", type(err).__name__, err)
            else:
                return True
        elif cfg.get("snooze_until"):
            try:
                dt = datetime.datetime.fromisoformat(cfg["snooze_until"])
                if datetime.datetime.now() < dt:
                    return True
            except Exception as err:
                log.debug("is_goal_coaching_snoozed: ignored %s: %s", type(err).__name__, err)
        return False

    def snooze_goals(self, hours: float = 24.0) -> datetime.datetime:
        """Snooze all goal-related check-ins and coaching for N hours."""
        until_dt = datetime.datetime.now() + datetime.timedelta(hours=hours)
        self.set_goal_coaching_config({
            "snooze_until": until_dt.isoformat(timespec="seconds")
        })
        log.info("[GoalEngine] Goal coaching snoozed for %.1f hours (until %s)", hours, until_dt)
        return until_dt

    def get_hardware_coaching_config(self) -> dict:
        """Read hardware monitoring / coaching configuration from config.json."""
        cfg = {}
        if self.config_path.exists():
            try:
                cfg = self._load_json(self.config_path)
            except Exception as err:
                log.debug("get_hardware_coaching_config: ignored %s: %s", type(err).__name__, err)
        return cfg.get("hardware_coaching", {
            "snooze_until": None,
        })

    def set_hardware_coaching_config(self, updates: dict) -> None:
        """Update hardware monitoring configuration in config.json."""
        cfg = {}
        if self.config_path.exists():
            try:
                cfg = self._load_json(self.config_path)
            except Exception as err:
                log.debug("set_hardware_coaching_config: ignored %s: %s", type(err).__name__, err)
        hw_cfg = cfg.setdefault("hardware_coaching", {})
        hw_cfg.update(updates)
        self._atomic_write_json(self.config_path, cfg)

    def is_hardware_coaching_snoozed(self) -> bool:
        """Check whether hardware chatter and alerts are currently snoozed."""
        cfg = self.get_hardware_coaching_config()
        snooze_until = cfg.get("snooze_until")
        if not snooze_until:
            return False
        try:
            until_dt = datetime.datetime.fromisoformat(snooze_until)
            return datetime.datetime.now() < until_dt
        except Exception:
            return False

    def snooze_hardware(self, hours: float = 24.0) -> datetime.datetime:
        """Snooze hardware chatter and alerts for N hours."""
        until_dt = datetime.datetime.now() + datetime.timedelta(hours=hours)
        self.set_hardware_coaching_config({
            "snooze_until": until_dt.isoformat(timespec="seconds")
        })
        log.info("[HardwareMonitor] Hardware chatter snoozed for %.1f hours (until %s)", hours, until_dt)
        return until_dt

    def award_pink_dollars(self, amount: int) -> int:
        """Award Pink Dollars through the store (read-modify-write under its lock) and return the new balance."""
        result = {"bal": self.get_wallet_balance()}

        def _m(data: dict) -> None:
            data["pink_dollars"] = max(0, int(data.get("pink_dollars", 15)) + amount)
            data["updated_at"] = time.time()
            result["bal"] = data["pink_dollars"]
        try:
            self.store.update(self.wallet_path, {}, _m)
            log.info("Awarded P$ %d. New balance: P$ %d", amount, result["bal"])
        except (StoreCorrupt, OSError) as err:
            log.warning("Could not update wallet.json: %s", err)
        return result["bal"]

    def get_wallet_balance(self) -> int:
        """Get current Pink Dollars balance from wallet.json."""
        wallet_p = self.wallet_path
        if wallet_p.exists():
            try:
                data = self._load_json(wallet_p)
                return int(data.get("pink_dollars", 15))
            except Exception as err:
                log.debug("get_wallet_balance: ignored %s: %s", type(err).__name__, err)
        return 15

    def get_long_term_facts_count(self) -> int:
        """Return the number of permanent fact notes stored in facts.json."""
        if not self.facts_path.exists():
            return 0
        try:
            facts = self._load_json(self.facts_path)
            notes = facts.get("notes") or facts.get("facts") or []
            return len(notes) if isinstance(notes, list) else 0
        except Exception:
            return 0

    def get_active_alarms(self, max_age_hours: int = 24) -> list[dict]:
        """Read timers and alarms from alarms.json. Auto-prune completed/dismissed items older than max_age_hours."""
        if not self.alarms_path.exists() or self.alarms_path.stat().st_size == 0:
            return []
        try:
            raw = self._load_json(self.alarms_path)
            if not isinstance(raw, list):
                return []
        except Exception as err:
            log.warning("Could not read alarms.json: %s", err)
            return []

        now = time.time()
        active = []
        changed = False

        for item in raw:
            if not isinstance(item, dict):
                continue
            state = item.get("state", "active")
            if state in ("completed", "dismissed"):
                finished_at = item.get("finished_at") or item.get("target_timestamp", 0)
                if isinstance(finished_at, (int, float)):
                    if now - finished_at > max_age_hours * 3600:
                        changed = True
                        continue
            active.append(item)

        if fix_duplicate_ids(active, "alarm"):
            changed = True
        if changed:
            try:
                self._save_json(self.alarms_path, active)
            except Exception as err:
                log.warning("Could not prune alarms.json: %s", err)

        return active

    def save_alarms(self, items: list[dict]) -> bool:
        """Write timers and alarms to alarms.json."""
        try:
            self._save_json(self.alarms_path, items)
            return True
        except Exception as err:
            log.warning("Could not save alarms.json: %s", err)
            return False

    def add_timer(self, duration_seconds: int, label: str = "Focus Timer") -> dict:
        """Create and persist a new countdown timer."""
        active = self.get_active_alarms()
        now_dt = datetime.datetime.now()
        now_ts = time.time()
        label = label.strip() or "Focus Timer"
        item = {
            "id": new_item_id("timer"),
            "type": "timer",
            "label": label,
            "created_at": now_dt.isoformat(),
            "duration_seconds": duration_seconds,
            "target_timestamp": now_ts + duration_seconds,
            "clock_time": "",
            "repeat": "once",
            "snooze_count": 0,
            "state": "active",
        }
        active.append(item)
        self.save_alarms(active)
        log.info("Added countdown timer '%s' for %ds (target: %f)", label, duration_seconds, item["target_timestamp"])
        return item

    def mark_alarm_ringing(self, item_id: str) -> None:
        """Mark an active alarm or timer as currently ringing in persistence so it does not re-trigger."""
        active = self.get_active_alarms()
        for a in active:
            if a.get("id") == item_id:
                a["state"] = "ringing"
                break
        self.save_alarms(active)

    def add_alarm(self, clock_str: str, label: str = "Alarm", repeat: str = "once") -> dict | None:
        """Create and persist a new clock alarm."""
        parsed = parse_clock_time(clock_str)
        if not parsed:
            return None
        hour, minute = parsed
        now_dt = datetime.datetime.now()
        target_dt = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target_dt <= now_dt:
            target_dt += datetime.timedelta(days=1)
        target_ts = target_dt.timestamp()

        clock_formatted = target_dt.strftime("%I:%M %p")
        label = label.strip() or "Alarm"

        active = self.get_active_alarms()
        now_id = datetime.datetime.now()
        item = {
            "id": new_item_id("alarm"),
            "type": "alarm",
            "label": label,
            "created_at": now_id.isoformat(),
            "duration_seconds": 0,
            "target_timestamp": target_ts,
            "clock_time": clock_formatted,
            "repeat": repeat,
            "snooze_count": 0,
            "state": "active",
        }
        active.append(item)
        self.save_alarms(active)
        log.info("Added clock alarm '%s' at %s (target: %s)", label, clock_formatted, target_dt)
        return item

    def cancel_alarm_or_timer(self, identifier: str | int) -> tuple[bool, str]:
        """Cancel an active timer or alarm by 1-based index, ID, or label substring."""
        active = self.get_active_alarms()
        idx = self._find_alarm_index(active, identifier)
        if idx is None:
            return False, ""
        item = active.pop(idx)
        self.save_alarms(active)
        return True, item.get("label", "")

    def dismiss_alarm(self, item_id: str) -> bool:
        """Mark a ringing or active alarm as completed/dismissed."""
        active = self.get_active_alarms()
        for item in active:
            if item.get("id") == item_id:
                if item.get("repeat") == "daily":
                    target_dt = datetime.datetime.fromtimestamp(item.get("target_timestamp", time.time()))
                    target_dt += datetime.timedelta(days=1)
                    item["target_timestamp"] = target_dt.timestamp()
                    item["state"] = "active"
                    item["snooze_count"] = 0
                else:
                    item["state"] = "completed"
                    item["finished_at"] = time.time()
                self.save_alarms(active)
                return True
        return False

    def snooze_alarm_or_timer(self, identifier: str | int, minutes: int = 5) -> tuple[bool, str]:
        """Snooze an active or ringing alarm/timer by `minutes`."""
        active = self.get_active_alarms()
        idx = self._find_alarm_index(active, identifier)
        if idx is None:
            return False, ""
        item = active[idx]
        item["target_timestamp"] = time.time() + (minutes * 60)
        item["state"] = "active"
        item["snooze_count"] = item.get("snooze_count", 0) + 1
        self.save_alarms(active)
        return True, item.get("label", "")

    def _find_alarm_index(self, active: list[dict], identifier: str | int) -> int | None:
        """Find index in active alarms list by 1-based index, ID, or label."""
        if not active or identifier is None:
            return None
        active_candidates = [a for a in active if a.get("state") in ("active", "ringing")]
        if isinstance(identifier, int):
            idx = identifier - 1
            if 0 <= idx < len(active_candidates):
                target_item = active_candidates[idx]
                return active.index(target_item)
            return None

        clean = str(identifier).strip()
        if not clean:
            return None
        target_str = clean[1:] if clean.startswith("#") else clean
        if target_str.isdigit():
            idx = int(target_str) - 1
            if 0 <= idx < len(active_candidates):
                target_item = active_candidates[idx]
                return active.index(target_item)

        clean_lower = clean.lower()
        for idx, item in enumerate(active):
            if item.get("id", "").lower() == clean_lower:
                return idx
        for idx, item in enumerate(active):
            if item.get("label", "").lower() == clean_lower:
                return idx
        for idx, item in enumerate(active):
            if clean_lower in item.get("label", "").lower():
                return idx
        return None

    def load_settings(self) -> dict:
        """Load persistent pet settings toggles from config.json."""
        if self.config_path.exists():
            try:
                data = self._load_json(self.config_path)
                return data.get("settings", {})
            except Exception as e:
                log.warning("Could not load settings from %s: %s", self.config_path, e)
        return {}

    def save_settings(self, settings: dict) -> bool:
        """Save persistent pet settings toggles into config.json."""
        data = {}
        if self.config_path.exists():
            try:
                data = self._load_json(self.config_path)
            except Exception as err:
                log.debug("save_settings: ignored %s: %s", type(err).__name__, err)
        data["settings"] = settings
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self._save_json(self.config_path, data)
            return True
        except Exception as e:
            log.warning("Could not save settings to %s: %s", self.config_path, e)
            return False

    def clear_all_alarms(self) -> int:
        """Cancel and remove all active and pending alarms and timers."""
        active = self.get_active_alarms()
        count = len([a for a in active if a.get("state") in ("active", "ringing")])
        self.save_alarms([])
        return count

    def get_alarms_prompt(self, numbered: bool = True) -> str:
        """Format active timers and alarms for Gemini prompt context and chat display."""
        if not ALARMS_ENABLED:
            return ""   # REVIEW H15
        active = self.get_active_alarms()
        active_items = [a for a in active if a.get("state") in ("active", "ringing")]
        if not active_items:
            return ""

        now = time.time()
        lines = []
        for idx, item in enumerate(active_items, 1):
            itype = item.get("type", "timer")
            label = item.get("label", "Timer")
            prefix = f"{idx}. " if numbered else "- "
            target_ts = item.get("target_timestamp", now)
            rem_s = max(0, int(target_ts - now))

            if itype == "timer":
                rem_m, rem_sec = divmod(rem_s, 60)
                rem_h, rem_m = divmod(rem_m, 60)
                if rem_h > 0:
                    time_desc = f"{rem_h}h {rem_m}m {rem_sec}s remaining"
                else:
                    time_desc = f"{rem_m}m {rem_sec}s remaining"
                lines.append(f"{prefix}[TIMER] \"{label}\" ({time_desc})")
            else:
                clock_str = item.get("clock_time", "")
                rem_m, rem_sec = divmod(rem_s, 60)
                rem_h, rem_m = divmod(rem_m, 60)
                if rem_h > 0:
                    time_desc = f"in {rem_h}h {rem_m}m"
                else:
                    time_desc = f"in {rem_m}m"
                lines.append(f"{prefix}[ALARM] \"{label}\" (Scheduled for {clock_str}, {time_desc})")

        return "\n".join(lines)

    def record_turn(self, user_text: str, pink_response: str, anim: str, had_screen: bool = False, seen: str = "") -> None:
        """Record turn in history and persist to session file."""
        display_user = user_text
        if had_screen and seen and user_text.startswith("[Pink peeks"):
            display_user = f"[Pink peeks at your screen — Saw: {seen}]"

        # Clean any raw [anim: ...] or [mode: ...] tags from recorded Pink response
        clean_pink = re.sub(r"\[anim:\s*[^\\\]]+\]", "", pink_response)
        clean_pink = re.sub(r"\[mode:\s*[^\\\]]+\]", "", clean_pink).strip()

        turn = {
            "timestamp": datetime.datetime.now().isoformat(),
            "status": "ok",
            "user": display_user,
            "pink": clean_pink,
            "anim": anim,
            "had_screen": had_screen,
        }
        if getattr(self, "last_total_tokens", 0) > 0:
            turn["tokens"] = {
                "prompt": self.last_prompt_tokens,
                "candidates": self.last_candidates_tokens,
                "total": self.last_total_tokens,
                "model": getattr(self, "last_model", GEMINI_MODEL),
            }
        if seen:
            turn["seen"] = seen
        self._append_history(turn)

        try:
            self._append_session_message(turn)
        except Exception as err:
            log.warning("Could not record turn to session file: %s", err)

    def record_error(
        self,
        user_text: str,
        error_msg: str,
        spoken_text: str | None = None,
        anim: str = "burnt",
        had_screen: bool = False,
    ) -> None:
        """Record an error turn in history and persist to session file with error formatting."""
        error_msg = privacy.redact_secrets(error_msg)          # REVIEW M9
        spoken_text = privacy.redact_secrets(spoken_text) if spoken_text else spoken_text
        pink_entry = spoken_text if spoken_text else f"[Error: {error_msg}]"
        turn = {
            "timestamp": datetime.datetime.now().isoformat(),
            "status": "error",
            "user": user_text,
            "pink": f"[ERROR] {pink_entry}",
            "error": error_msg,
            "anim": anim,
            "had_screen": had_screen,
        }
        self._append_history(turn)

        try:
            self._append_session_message(turn)
        except Exception as err:
            log.warning("Could not record error turn to session file: %s", err)

    def clear_current_session(self) -> None:
        """Reset current in-memory history and start a fresh session file."""
        self.history.clear()
        self.recent_ambient_dialogues.clear()
        self.recent_physical_actions.clear()
        # If previous session file on disk was empty (0 messages), prune it
        if hasattr(self, "session_file") and self.session_file.exists():
            try:
                if not sessions.has_messages(self.session_file):
                    self.session_file.unlink(missing_ok=True)
            except Exception as err:
                log.debug("clear_current_session: ignored %s: %s", type(err).__name__, err)
        self._generate_new_session_file()

    def record_ambient_dialogue(
        self,
        text: str | object,
        category: str = "dialogue",
        extra_lines: list[object] | None = None,
        user_choice: str | None = None,
        context: str | None = None,
    ) -> None:
        """Record an ambient or fixed dialogue line in temporary in-memory RAM storage only (zero disk writes)."""
        if not text:
            return
        if hasattr(text, "text"):
            clean_text = str(text.text).strip()
        else:
            clean_text = str(text).strip()

        clean_text = re.sub(r"\[anim:\s*[^\\\]]+\]", "", clean_text)
        clean_text = re.sub(r"\[mode:\s*[^\\\]]+\]", "", clean_text).strip()

        if extra_lines:
            clean_extras = []
            for e in extra_lines:
                if hasattr(e, "text"):
                    t = str(e.text).strip()
                elif isinstance(e, dict):
                    t = str(e.get("text", "")).strip()
                elif isinstance(e, (tuple, list)):
                    t = str(e[0]).strip() if e else ""
                elif isinstance(e, str):
                    t = e.strip()
                else:
                    t = str(e).strip()
                # Omit transient loading UI indicators from ambient dialogue context
                if t and t not in ("* ...", "* ...?", "* ..?", "* ...?! (Wait, make up your mind!)"):
                    clean_extras.append(t)
            if clean_extras:
                clean_text = clean_text + " -> " + " -> ".join(clean_extras)

        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "text": clean_text,
            "category": category,
            "user_choice": user_choice,
            "context": context,
        }
        # In-memory only (RAM) so session files on disk never blow up in size!
        self.recent_ambient_dialogues.append(entry)

    def get_recent_ambient_context(self, max_items: int = 3, max_age_s: int = 120) -> str:
        """Format very recent ambient dialogue lines (temporary RAM only, max 2 minutes old)."""
        if not self.recent_ambient_dialogues:
            return ""

        now = datetime.datetime.now()
        lines = []
        valid_entries = []
        for entry in self.recent_ambient_dialogues:
            if "timestamp" in entry:
                try:
                    dt = datetime.datetime.fromisoformat(entry["timestamp"])
                    diff_s = int((now - dt).total_seconds())
                    if diff_s <= max_age_s:
                        valid_entries.append((entry, max(0, diff_s)))
                except Exception:
                    valid_entries.append((entry, 0))

        if not valid_entries:
            return ""

        recent = valid_entries[-max_items:]

        category_descriptions = {
            "idle": "Ambient idle speech while resting",
            "question": "Interactive question asked to user",
            "question_answered": "User answered Pink's interactive question",
            "burnt_switch": "Flashbang reaction when switching to bright light app",
            "window_switch_shock": "Startled reaction when switching to maximized app",
            "song_detection": "Detected song playing in media player",
            "toby_fox_familiar": "Heard familiar music composed by Toby Fox",
            "stressed_skip": "Dizzy and annoyed from rapid song skips",
            "startup_summon": "Spawned / summoned onto the taskbar",
            "shocked": "Startled by a click",
            "tongue": "Stuck tongue out (:P)",
            "angry": "Angry reaction",
            "land": "Landed after falling or dropping",
            "throw": "Throwing cat bomb attack",
            "drag": "Picked up by cursor",
            "singing": "Singing happily",
            "peace_sign": "Flashing a peace sign",
            "embarrassed": "Feeling embarrassed",
            "wistful": "Wistful thinking",
            "kneeling": "Taking a break kneeling down",
            "behind": "Looking suspiciously behind her back",
            "screen_comment": "Spontaneous comment after peeking at user's desktop screen",
        }

        for entry, diff_s in recent:
            if diff_s < 10:
                ts_str = "just now"
            elif diff_s < 60:
                ts_str = f"{diff_s}s ago"
            else:
                mins = diff_s // 60
                ts_str = f"{mins}m ago"

            cat = entry.get("category", "dialogue")
            cat_desc = category_descriptions.get(cat, cat)
            spoken = entry.get("text", "")
            choice = entry.get("user_choice")
            ctx = entry.get("context")

            item_desc = f"- [{ts_str}] ({cat_desc}): \"{spoken}\""
            if choice:
                item_desc += f" (User clicked option: \"{choice}\")"
            elif ctx:
                item_desc += f" [Context: {ctx}]"
            lines.append(item_desc)

        return "\n".join(lines)

    def record_physical_action(
        self,
        action: str,
        description: str,
        category: str = "action",
        details: str = "",
    ) -> None:
        """Record an observable physical action, animation, or physics event in temporary in-memory RAM only (zero disk writes)."""
        if not description:
            return
        now = datetime.datetime.now()
        # Coalesce rapid duplicate actions within 4 seconds (e.g., repeated bomb throw ticks, repeated pacing)
        if self.recent_physical_actions:
            last = self.recent_physical_actions[-1]
            if last.get("action") == action:
                try:
                    last_dt = datetime.datetime.fromisoformat(last["timestamp"])
                    if (now - last_dt).total_seconds() < 4.0:
                        count = last.get("count", 1) + 1
                        last["count"] = count
                        last["timestamp"] = now.isoformat()
                        if details:
                            last["details"] = details
                        return
                except Exception as err:
                    log.debug("record_physical_action: ignored %s: %s", type(err).__name__, err)

        entry = {
            "timestamp": now.isoformat(),
            "action": action,
            "description": description.strip(),
            "category": category,
            "details": details.strip() if details else "",
            "count": 1,
        }
        self.recent_physical_actions.append(entry)

    def get_recent_actions_context(
        self,
        current_state_summary: str = "",
        max_items: int = 6,
        max_age_s: int = 120,
    ) -> str:
        """Format very recent physical actions and body state into a situational awareness prompt block."""
        now = datetime.datetime.now()
        valid_entries = []
        for entry in self.recent_physical_actions:
            if "timestamp" in entry:
                try:
                    dt = datetime.datetime.fromisoformat(entry["timestamp"])
                    diff_s = int((now - dt).total_seconds())
                    if diff_s <= max_age_s:
                        valid_entries.append((entry, max(0, diff_s)))
                except Exception:
                    valid_entries.append((entry, 0))

        if not valid_entries and not current_state_summary:
            return ""

        lines = []
        if current_state_summary:
            lines.append(f"- CURRENT BODY STATUS: {current_state_summary}")

        if valid_entries:
            lines.append("- ACTIONS & EVENTS PERFORMED IN THE LAST 2 MINUTES:")
            recent = valid_entries[-max_items:]
            for entry, diff_s in recent:
                if diff_s < 8:
                    ts_str = "just now"
                elif diff_s < 60:
                    ts_str = f"{diff_s}s ago"
                else:
                    mins = diff_s // 60
                    ts_str = f"{mins}m ago"

                desc = entry.get("description", "")
                count = entry.get("count", 1)
                count_str = f" (x{count})" if count > 1 else ""
                details = entry.get("details", "")
                details_str = f" [{details}]" if details else ""
                lines.append(f"  • [{ts_str}] {desc}{count_str}{details_str}")

        return "\n".join(lines)

    def get_recent_sessions_overview(self, max_days: int = 2, max_sessions: int = 6) -> tuple[str, set[str]]:
        """Retrieve a concise timeline of today's and yesterday's past conversations across sessions.
        Returns: (formatted_overview_str, set_of_included_session_filenames)
        """
        now = datetime.datetime.now()
        target_dates = [(now.date() - datetime.timedelta(days=i)).strftime("%Y%m%d") for i in range(max_days)]

        all_target_files = []
        for d_str in target_dates:
            all_target_files.extend(sorted(sessions.session_files(self.sessions_dir, f"session_{d_str}_*")))

        # Filter out current active session file and empty sessions (size <= 120 bytes)
        candidate_files = []
        for f in all_target_files:
            if f.name == self.session_file.name:
                continue
            try:
                if f.stat().st_size <= 120:
                    continue
                candidate_files.append(f)
            except Exception:
                continue
        # Keep the most recent max_sessions with actual conversations
        selected_files = candidate_files[-max_sessions:]

        session_entries = []
        included_files = set()

        for f in selected_files:
            try:
                data = sessions.load_session(f)
                msgs = data.get("messages", [])
                if not msgs:
                    continue
                first_ts = msgs[0].get("timestamp", "")
                last_ts = msgs[-1].get("timestamp", "")

                def _fmt_dt(iso_str: str) -> tuple[str, str]:
                    try:
                        dt = datetime.datetime.fromisoformat(iso_str)
                        d_diff = (now.date() - dt.date()).days
                        if d_diff == 0:
                            day_label = "Today"
                        elif d_diff == 1:
                            day_label = f"Yesterday ({dt.strftime('%b %d')})"
                        else:
                            day_label = dt.strftime("%b %d, %Y")
                        return day_label, dt.strftime("%I:%M:%S %p")
                    except Exception:
                        return "Past", iso_str

                start_day, start_time = _fmt_dt(first_ts)
                _, end_time = _fmt_dt(last_ts)
                span = f"{start_day} | {start_time} - {end_time}"

                lines = [f"### Session ({span}, {len(msgs)} turns):"]
                # Include up to the last 10 turns per session to avoid context explosion
                for m in msgs[-10:]:
                    _, m_ts = _fmt_dt(m.get("timestamp", ""))
                    u = m.get("user", "").strip().replace("\n", " ")
                    if len(u) > 75:
                        u = u[:72] + "..."
                    p = m.get("pink", "").strip().replace("\n", " ")
                    p = re.sub(r"\[anim:\s*[^\]]+\]", "", p).strip()
                    p = protocol.strip_tags(p, protocol.MODE_TAGS).strip()
                    if len(p) > 80:
                        p = p[:77] + "..."
                    if u.startswith("[Pink peeks"):
                        seen = m.get("seen", "")
                        if not seen and "Saw:" in u:
                            seen = u.split("Saw:", 1)[1].strip().rstrip("]")
                        if seen:
                            lines.append(f"- [{m_ts}] (Screen Sight): {seen}")
                    elif u.startswith("[Pink annoyed:"):
                        if "5 dialogue" in u or "moving" in u:
                            lines.append(f"- [{m_ts}] (Event): Pink got annoyed because user was active but ignored 5 dialogues in a row -> Pink: \"{p}\"")
                        else:
                            lines.append(f"- [{m_ts}] (Event): Pink got annoyed after user ignored 2 dialogues in a row while away -> Pink: \"{p}\"")
                    elif u.startswith("[User clicked Pink"):
                        lines.append(f"- [{m_ts}] (Event): User acknowledged Pink -> Pink: \"{p}\"")
                    elif u.startswith("[User returned after being away]"):
                        lines.append(f"- [{m_ts}] (Event): User returned from AFK -> Pink: \"{p}\"")
                    elif u.startswith("[Music played:"):
                        lines.append(f"- [{m_ts}] (Music): {u} -> Pink: \"{p}\"")
                    else:
                        lines.append(f"- [{m_ts}] User: \"{u}\" -> Pink: \"{p}\"")
                session_entries.append("\n".join(lines))
                included_files.add(f.name)
            except Exception as err:
                log.warning("Could not read previous session %s: %s", f, err)

        return "\n\n".join(session_entries), included_files

    def get_today_sessions_overview(self) -> str:
        """Backwards compatibility helper."""
        overview, _ = self.get_recent_sessions_overview(max_days=2, max_sessions=6)
        return overview

    def search_past_sessions(self, query: str, exclude_filenames: set[str] | None = None, max_results: int = 4,
                             max_files: int = 200) -> str:
        """Search the newest ``max_files`` older session files for keywords when the user asks about past events.
        Call it off the GUI thread (see GeminiWorkerThread.system_suffix_fn).
        """
        if not query or len(query.strip()) < 3:
            return ""

        exclude = set(exclude_filenames) if exclude_filenames else set()
        exclude.add(self.session_file.name)

        # Extract search terms (ignore very common short words and syntax)
        stopwords = {
            "what", "when", "where", "which", "who", "whom", "this", "that", "these", "those",
            "am", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
            "do", "does", "did", "doing", "a", "an", "the", "and", "but", "if", "or", "because",
            "as", "until", "while", "of", "at", "by", "for", "with", "about", "against", "between",
            "into", "through", "during", "before", "after", "above", "below", "to", "from", "up",
            "down", "in", "out", "on", "off", "over", "under", "again", "further", "then", "once",
            "here", "there", "all", "any", "both", "each", "few", "more", "most", "other", "some",
            "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very", "can",
            "will", "just", "don", "should", "now", "you", "your", "my", "me", "i", "we", "our",
            "remember", "session", "sessions", "check", "tell", "logs", "cache", "find"
        }
        words = [re.escape(w.lower()) for w in re.findall(r"[a-zA-Z0-9_\-]+", query) if len(w) >= 3 and w.lower() not in stopwords]
        if not words:
            return ""

        pattern = re.compile(r"\b(" + "|".join(words) + r")\b", re.IGNORECASE)

        all_session_files = sessions.session_files(self.sessions_dir)[:max_files]
        matches = []

        for f in all_session_files:
            if f.name in exclude:
                continue
            try:
                if f.stat().st_size <= 120:
                    continue
                data = sessions.load_session(f)
                msgs = data.get("messages", [])
                for m in reversed(msgs):
                    u = m.get("user", "")
                    p = m.get("pink", "")
                    if pattern.search(u) or pattern.search(p):
                        ts = m.get("timestamp", "")
                        try:
                            dt = datetime.datetime.fromisoformat(ts)
                            date_str = dt.strftime("%b %d, %Y at %I:%M %p")
                        except Exception:
                            date_str = ts
                        u_clean = u.replace("\n", " ").strip()
                        p_clean = protocol.strip_tags(p, ("anim", "mode", "ghost")).replace("\n", " ").strip()
                        if len(u_clean) > 80:
                            u_clean = u_clean[:77] + "..."
                        if len(p_clean) > 90:
                            p_clean = p_clean[:87] + "..."
                        matches.append(f"- [{date_str}] User: \"{u_clean}\" -> Pink: \"{p_clean}\"")
                        if len(matches) >= max_results:
                            break
            except Exception:
                continue
            if len(matches) >= max_results:
                break

        if not matches:
            return ""
        return "RELEVANT PAST MEMORIES FOUND FROM OLDER SESSIONS:\n" + "\n".join(matches)

    def _load_token_stats(self) -> None:
        """Load persistent token statistics from token_usage.json."""
        if hasattr(self, "token_usage_path") and self.token_usage_path.exists():
            try:
                data = self._load_json(self.token_usage_path)
                last_q = data.get("last_query", {})
                if isinstance(last_q, dict):
                    self.last_prompt_tokens = int(last_q.get("prompt_tokens", 0))
                    self.last_candidates_tokens = int(last_q.get("candidates_tokens", 0))
                    self.last_total_tokens = int(last_q.get("total_tokens", 0))
                    self.last_model = str(last_q.get("model", GEMINI_MODEL))
                    self.last_token_timestamp = str(last_q.get("timestamp", ""))
            except Exception as err:
                log.debug("Could not load token usage file: %s", err)

    def record_token_usage(self, prompt_tokens: int, candidates_tokens: int, total_tokens: int, model_name: str) -> None:
        """Update in-memory and persistent token usage metrics from a Gemini API response."""
        now_dt = datetime.datetime.now()
        today_str = now_dt.strftime("%Y-%m-%d")
        total = total_tokens if total_tokens > 0 else (prompt_tokens + candidates_tokens)

        # In-memory session counters
        self.session_prompt_tokens += prompt_tokens
        self.session_candidates_tokens += candidates_tokens
        self.session_total_tokens += total
        self.session_queries += 1
        self.last_prompt_tokens = prompt_tokens
        self.last_candidates_tokens = candidates_tokens
        self.last_total_tokens = total
        self.last_model = model_name
        self.last_token_timestamp = now_dt.isoformat()

        # Update persistent file
        data = {}
        if hasattr(self, "token_usage_path") and self.token_usage_path.exists():
            try:
                data = self._load_json(self.token_usage_path)
            except Exception:
                data = {}

        data["lifetime_prompt_tokens"] = data.get("lifetime_prompt_tokens", 0) + prompt_tokens
        data["lifetime_candidates_tokens"] = data.get("lifetime_candidates_tokens", 0) + candidates_tokens
        data["lifetime_total_tokens"] = data.get("lifetime_total_tokens", 0) + total
        data["lifetime_queries"] = data.get("lifetime_queries", 0) + 1

        daily = data.setdefault("daily", {})
        today_data = daily.setdefault(today_str, {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0, "queries": 0})
        today_data["prompt_tokens"] = today_data.get("prompt_tokens", 0) + prompt_tokens
        today_data["candidates_tokens"] = today_data.get("candidates_tokens", 0) + candidates_tokens
        today_data["total_tokens"] = today_data.get("total_tokens", 0) + total
        today_data["queries"] = today_data.get("queries", 0) + 1

        data["last_query"] = {
            "prompt_tokens": prompt_tokens,
            "candidates_tokens": candidates_tokens,
            "total_tokens": total,
            "model": model_name,
            "timestamp": now_dt.isoformat(),
        }

        try:
            if hasattr(self, "token_usage_path"):
                self._save_json(self.token_usage_path, data)
        except Exception as err:
            log.warning("Could not persist token usage: %s", err)

    def get_token_summary(self) -> dict[str, any]:
        """Aggregate token usage statistics across session, daily, and context window."""
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        today_prompt = 0
        today_cand = 0
        today_total = 0
        today_queries = 0
        lifetime_total = self.session_total_tokens
        lifetime_queries = self.session_queries

        if hasattr(self, "token_usage_path") and self.token_usage_path.exists():
            try:
                data = self._load_json(self.token_usage_path)
                daily = data.get("daily", {})
                if today_str in daily:
                    t_info = daily[today_str]
                    today_prompt = t_info.get("prompt_tokens", 0)
                    today_cand = t_info.get("candidates_tokens", 0)
                    today_total = t_info.get("total_tokens", 0)
                    today_queries = t_info.get("queries", 0)
                lifetime_total = data.get("lifetime_total_tokens", lifetime_total)
                lifetime_queries = data.get("lifetime_queries", lifetime_queries)
            except Exception as err:
                log.debug("get_token_summary: ignored %s: %s", type(err).__name__, err)

        if today_total == 0 and self.session_total_tokens > 0:
            today_total = self.session_total_tokens
            today_queries = self.session_queries

        # Gemini Flash context window limit: 1,048,576 tokens
        context_window_limit = 1_048_576
        used_context = self.last_prompt_tokens if self.last_prompt_tokens > 0 else 0
        context_remaining = max(0, context_window_limit - used_context)
        context_pct_free = (context_remaining / context_window_limit) * 100.0

        return {
            "session_prompt_tokens": self.session_prompt_tokens,
            "session_candidates_tokens": self.session_candidates_tokens,
            "session_total_tokens": self.session_total_tokens,
            "session_queries": self.session_queries,
            "last_prompt_tokens": self.last_prompt_tokens,
            "last_candidates_tokens": self.last_candidates_tokens,
            "last_total_tokens": self.last_total_tokens,
            "last_model": self.last_model,
            "today_total_tokens": today_total,
            "today_queries": today_queries,
            "lifetime_total_tokens": lifetime_total,
            "lifetime_queries": lifetime_queries,
            "context_window_limit": context_window_limit,
            "context_window_remaining": context_remaining,
            "context_window_pct_free": context_pct_free,
        }

    def format_token_dialogue_lines(self) -> list[str]:
        """Format an in-character dialogue sequence explaining token status and limits."""
        stats = self.get_token_summary()
        lines = []
        lines.append("* Token Core Status, mew! Here's the rundown:")
        if stats["session_queries"] > 0 or stats["last_total_tokens"] > 0:
            lines.append(
                f"* Last query: {stats['last_prompt_tokens']:,} prompt + {stats['last_candidates_tokens']:,} output = {stats['last_total_tokens']:,} tokens ({stats['last_model']})."
            )
            lines.append(
                f"* Context window: {stats['context_window_remaining']:,} / {stats['context_window_limit']:,} tokens remaining (~{stats['context_window_pct_free']:.1f}% free)!"
            )
            lines.append(
                f"* Usage: {stats['today_total_tokens']:,} tokens across {stats['today_queries']} queries today (session: {stats['session_total_tokens']:,} tokens)."
            )
        else:
            lines.append("* No AI queries sent yet this session!")
            lines.append(
                f"* Context window: {stats['context_window_limit']:,} tokens available (100% free)!"
            )
            if stats["today_queries"] > 0:
                lines.append(
                    f"* Earlier today: {stats['today_total_tokens']:,} tokens across {stats['today_queries']} queries."
                )
        lines.append(
            "* (Gemini API refills rate limits every minute with 1M TPM & 1,500 free daily requests, so don't worry about running out, dummy!)"
        )
        return lines



def _memory_locked(fn):
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self.store.lock:
            return fn(self, *args, **kwargs)
    return wrapper


for _name, _fn in list(vars(MemoryManager).items()):
    if callable(_fn) and not _name.startswith("__") and _name not in ("_load_json", "_save_json", "_store_corrupt"):
        try:
            _src = inspect.getsource(_fn)
        except (OSError, TypeError):
            continue
        if "_save_json(" in _src or "_atomic_write_json(" in _src or "save_goals(" in _src or "save_alarms(" in _src:
            setattr(MemoryManager, _name, _memory_locked(_fn))
