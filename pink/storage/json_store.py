"""One safe way to read and write Pink's JSON files (REVIEW C6, plan 2.1).

Before this, every store loaded with ``except Exception: pass``, fell back to an empty default, and the next change
wrote that default back: one stray comma (or a write cut off by a crash) silently wiped facts, reminders, goals, the
wallet or settings. Now:

* a MISSING file reads as the default;
* a CORRUPT file (bad JSON / bad UTF-8) is copied to ``<name>.corrupt-<unix_ts><suffix>`` (the original is left
  untouched), the owner is told
  (``on_corrupt``), and every later write to that path in this session is REFUSED, so an empty default can never
  overwrite the user's data;
* an OSError (e.g. the file is locked by an editor or antivirus) is retried, then raised; it is never "corrupt";
* writes are atomic (temp file + ``os.replace``; the temp file is removed if anything fails) and serialised by one
  re-entrant lock that ``update`` holds across read-modify-write.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("yellows_pixel_buddies.json_store")

READ_RETRIES = 3
RETRY_DELAY_S = 0.05


class StoreCorrupt(Exception):
    """A memory file could not be parsed; it was moved to ``backup`` and won't be overwritten."""

    def __init__(self, path: Path, backup: Optional[Path] = None) -> None:
        super().__init__(f"{path} is corrupt" + (f" (saved as {backup.name})" if backup else ""))
        self.path, self.backup = path, backup


class JsonStore:
    def __init__(self, on_corrupt: Optional[Callable[[Path, Optional[Path]], None]] = None) -> None:
        self.lock = threading.RLock()
        self.on_corrupt = on_corrupt
        self._blocked: dict[Path, Optional[Path]] = {}   # path -> where its corrupt content was saved

    # ------------------------------------------------------------------ reading
    def read(self, path: Path, default: Any = None, *, strict: bool = False) -> Any:
        """Parsed JSON at ``path``. Missing (or empty) -> a copy of ``default``.

        Corrupt -> quarantined + blocked; then ``default`` (or StoreCorrupt if ``strict``).
        """
        path = Path(path)
        with self.lock:
            if path in self._blocked:
                if strict:
                    raise StoreCorrupt(path, self._blocked[path])
                return copy.deepcopy(default)
            try:
                raw = self._read_bytes(path)
            except FileNotFoundError:
                return copy.deepcopy(default)
            if not raw.strip():
                return copy.deepcopy(default)
            try:
                return json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as err:
                backup = self._quarantine(path, err)
                if strict:
                    raise StoreCorrupt(path, backup) from err
                return copy.deepcopy(default)

    @staticmethod
    def _read_bytes(path: Path) -> bytes:
        last: Optional[OSError] = None
        for attempt in range(READ_RETRIES):
            try:
                return path.read_bytes()
            except FileNotFoundError:
                raise
            except OSError as err:          # locked by another program: retry, never "corrupt"
                last = err
                time.sleep(RETRY_DELAY_S * (attempt + 1))
        assert last is not None
        raise last

    def _quarantine(self, path: Path, err: Exception) -> Optional[Path]:
        """COPY the corrupt file to ``<stem>.corrupt-<ts><suffix>`` (the original stays where it is, untouched) and
        block writes to it. An identical earlier backup is reused, so relaunching doesn't pile up copies."""
        backup: Optional[Path] = None
        try:
            data = path.read_bytes()
            for old in sorted(path.parent.glob(f"{path.stem}.corrupt-*{path.suffix}")):
                if old.stat().st_size == len(data) and old.read_bytes() == data:
                    backup = old
                    break
            if backup is None:
                backup = path.with_name(f"{path.stem}.corrupt-{int(time.time())}{path.suffix}")
                n = 1
                while backup.exists():
                    backup = path.with_name(f"{path.stem}.corrupt-{int(time.time())}-{n}{path.suffix}")
                    n += 1
                backup.write_bytes(data)
        except OSError as copy_err:
            log.error("%s is corrupt and could not be backed up (%s); refusing to write it.", path.name, copy_err)
            backup = None
        self._blocked[path] = backup
        log.error("%s is corrupt (%s). Saved it as %s and will not overwrite it.", path.name, err,
                  backup.name if backup else "<not moved>")
        if self.on_corrupt is not None:
            try:
                self.on_corrupt(path, backup)
            except Exception as cb_err:  # noqa: BLE001 - the notification must never break the read
                log.debug("on_corrupt callback failed: %s", cb_err)
        return backup

    def blocked(self) -> dict:
        """{path: backup} of every file found corrupt this session."""
        return dict(self._blocked)

    def is_blocked(self, path: Path) -> bool:
        return Path(path) in self._blocked

    @staticmethod
    def remove_stale_temp_files(folder: Path) -> int:
        """Delete temp files left by a process killed mid-write (the real file is always intact). Call at startup."""
        removed = 0
        for tmp in Path(folder).glob(".*.json.*.tmp"):
            try:
                tmp.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    # ------------------------------------------------------------------ writing
    def write(self, path: Path, data: Any) -> bool:
        """Atomically replace ``path`` with ``data`` as JSON. False (nothing written) if the path is blocked."""
        path = Path(path)
        with self.lock:
            if path in self._blocked:
                log.warning("Not writing %s: it was corrupt this session (backup: %s).", path.name,
                            self._blocked[path].name if self._blocked[path] else "none")
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            try:
                with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, path)
                return True
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass

    def update(self, path: Path, default: Any, mutate: Callable[[Any], Any]) -> Any:
        """Read-modify-write under the lock. ``mutate(data)`` changes ``data`` in place and returns a result.

        Raises StoreCorrupt (nothing written) if the file is corrupt.
        """
        with self.lock:
            data = self.read(path, default, strict=True)
            result = mutate(data)
            self.write(path, data)
            return result
