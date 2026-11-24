"""Chat session files: append-only JSON Lines, with readers that also understand the old .json format (REVIEW M21).

Every chat turn used to read the whole session JSON, append one message, and rewrite the file. Sessions are now
``session_<id>.jsonl``: a header line ``{"session_id", "started_at"}`` followed by one message per line, appended with
flush + fsync. A crash can at worst lose or cut off the last line, which readers skip. Old ``session_*.json`` files
are still read (they are never rewritten), so nothing needs migrating.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

log = logging.getLogger("yellows_pixel_buddies.sessions")

SUFFIXES = (".jsonl", ".json")
_lock = threading.RLock()


def session_files(sessions_dir: Path, pattern: str = "session_*") -> list[Path]:
    """Every session file (both formats), newest first (file names start with the timestamp)."""
    if not Path(sessions_dir).is_dir():
        return []
    files = {p for suf in SUFFIXES for p in Path(sessions_dir).glob(pattern + suf)}
    return sorted(files, key=lambda p: p.stem, reverse=True)


def load_session(path: Path) -> dict[str, Any]:
    """{"session_id", "started_at", "messages": [...]} for either format. Unreadable lines/files -> skipped/empty."""
    path = Path(path)
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"messages": []}
    out: dict[str, Any] = {"messages": []}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                log.debug("Skipping unreadable line %d in %s", i + 1, path.name)
                continue
            if i == 0 and isinstance(obj, dict) and "session_id" in obj and "user" not in obj:
                out.update({k: v for k, v in obj.items() if k != "messages"})
            elif isinstance(obj, dict):
                out["messages"].append(obj)
    return out


def iter_messages(paths: Iterable[Path]):
    for p in paths:
        try:
            yield p, load_session(p).get("messages", [])
        except (OSError, ValueError) as err:
            log.debug("Skipping unreadable session %s: %s", Path(p).name, err)


def append_message(path: Path, message: dict, header: Optional[dict] = None) -> None:
    """Append one message line (creating the file with ``header`` first). Durable: flush + fsync."""
    path = Path(path)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists() or path.stat().st_size == 0
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            if new and header is not None:
                f.write(json.dumps(header, ensure_ascii=False) + "\n")
            f.write(json.dumps(message, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())


def has_messages(path: Path) -> bool:
    try:
        return bool(load_session(path).get("messages"))
    except (OSError, ValueError):
        return True   # unreadable: keep it, never delete what we can't read
