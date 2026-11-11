"""Cache of parsed session metadata, refreshed incrementally from transcript files."""
from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import threading
from pathlib import Path

from agents_hub.config import Paths
from agents_hub.models import SessionMeta
from agents_hub.transcript import scan

INDEX_VERSION = 1


class Index:
    def __init__(self, paths: Paths):
        self._paths = paths
        self._meta_by_path: dict[str, SessionMeta] = {}
        self._lock = threading.Lock()

    def load(self) -> None:
        try:
            raw = json.loads(self._paths.index_file.read_text())
            if raw.get("version") == INDEX_VERSION:
                self._meta_by_path = {p: _from_dict(d) for p, d in raw["sessions"].items()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self._meta_by_path = {}

    def refresh(self) -> list[SessionMeta]:
        fresh: dict[str, SessionMeta] = {}
        for path in self._paths.projects_dir.glob("*/*.jsonl"):
            key = str(path)
            try:
                st = path.stat()
                prev = self._meta_by_path.get(key)
                if prev is not None and prev.size == st.st_size and prev.mtime == st.st_mtime \
                        and prev.inode == st.st_ino:
                    fresh[key] = prev
                else:
                    fresh[key] = scan(path, prev)
            except Exception:  # one bad file must not hide the others
                continue
        with self._lock:
            self._meta_by_path = fresh
        return list(fresh.values())

    def get(self, session_id: str) -> SessionMeta | None:
        with self._lock:
            return next((m for m in self._meta_by_path.values() if m.session_id == session_id), None)

    def save(self) -> None:
        self._paths.cache_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            payload = {"version": INDEX_VERSION,
                       "sessions": {p: _to_dict(m) for p, m in self._meta_by_path.items()}}
        fd, tmp = tempfile.mkstemp(dir=self._paths.cache_dir, prefix=".index-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f)
            os.replace(tmp, self._paths.index_file)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def _to_dict(m: SessionMeta) -> dict:
    retVal = dataclasses.asdict(m)
    retVal["path"] = str(m.path)
    retVal["pending_tool_ids"] = sorted(m.pending_tool_ids)
    return retVal


def _from_dict(d: dict) -> SessionMeta:
    d = dict(d)
    d["path"] = Path(d["path"])
    d["pending_tool_ids"] = set(d.get("pending_tool_ids") or [])
    return SessionMeta(**d)
