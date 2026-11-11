"""Live Claude Code sessions, from ~/.claude/sessions/<pid>.json plus a process check."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Callable, Iterable

from agents_hub.config import Paths
from agents_hub.models import LiveInfo


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    tty: str | None
    lstart: str


ProcLookup = Callable[[Iterable[int]], dict[int, ProcInfo]]


def ps_lookup(pids: Iterable[int]) -> dict[int, ProcInfo]:
    pid_list = ",".join(str(p) for p in pids)
    retVal: dict[int, ProcInfo] = {}
    if pid_list:
        out = subprocess.run(["ps", "-o", "pid=,tty=,lstart=", "-p", pid_list],
                             capture_output=True, text=True, timeout=5,
                             env={**os.environ, "LC_ALL": "C", "TZ": "UTC"}).stdout
        for line in out.splitlines():
            parts = line.split(None, 2)
            if len(parts) == 3:
                tty = None if parts[1] in ("??", "-") else parts[1]
                retVal[int(parts[0])] = ProcInfo(int(parts[0]), tty, parts[2])
    return retVal


_last_good_by_path: dict[str, dict] = {}


def read_live(paths: Paths, lookup: ProcLookup = ps_lookup) -> dict[str, LiveInfo]:
    records = [r for r in (_load_or_last_good(f) for f in paths.sessions_dir.glob("*.json")) if r]
    proc_by_pid = lookup([r["pid"] for r in records]) if records else {}
    retVal: dict[str, LiveInfo] = {}
    for r in records:
        proc = proc_by_pid.get(r["pid"])
        if proc is not None and _same_start(proc.lstart, r.get("procStart")):
            retVal[r["sessionId"]] = LiveInfo(
                pid=r["pid"], session_id=r["sessionId"], cwd=r.get("cwd") or "",
                status=r.get("status") or "idle", name=r.get("name"),
                name_source=r.get("nameSource"), kind=r.get("kind") or "interactive",
                updated_at=(r.get("statusUpdatedAt") or r.get("updatedAt") or 0) / 1000,
                tty=proc.tty, waiting_for=r.get("waitingFor"), proc_start=r.get("procStart"))
    return retVal


def _load_or_last_good(path) -> dict | None:
    """A file caught mid-write by Claude Code falls back to its last good read."""
    retVal = _load(path)
    if retVal is not None:
        _last_good_by_path[str(path)] = retVal
    else:
        retVal = _last_good_by_path.get(str(path))
    return retVal


def _load(path) -> dict | None:
    retVal = None
    try:
        d = json.loads(path.read_text())
        if isinstance(d, dict) and isinstance(d.get("pid"), int) and d.get("sessionId"):
            retVal = d
    except (OSError, ValueError):
        retVal = None
    return retVal


def _same_start(lstart: str, proc_start: str | None) -> bool:
    """True when proc_start is missing (cannot verify) or matches ps lstart."""
    return proc_start is None or " ".join(lstart.split()) == " ".join(proc_start.split())
