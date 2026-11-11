"""User actions on a session row. Each returns a short message for the status line."""
from __future__ import annotations

import json
import os
import shlex
import signal
from pathlib import Path

from agents_hub import iterm
from agents_hub.models import Row

MAX_TITLE_LEN = 200


def go_to(row: Row) -> str:
    if row.live is None:
        retVal = "Session is not running"
    elif row.live.tty is None:
        retVal = f"Session runs outside iTerm (pid {row.live.pid})"
    elif iterm.focus(row.live.tty):
        retVal = f"Went to {row.title}"
    else:
        retVal = f"No iTerm tab found for {row.live.tty}"
    return retVal


def resume(row: Row) -> str:
    if row.live is not None:
        retVal = go_to(row)
    else:
        cwd = row.meta.cwd if row.meta.cwd and Path(row.meta.cwd).is_dir() else str(Path.home())
        iterm.new_tab(cwd, f"claude --resume {shlex.quote(row.meta.session_id)}")
        retVal = f"Resumed {row.title}"
    return retVal


def stop(row: Row, kill=os.kill) -> str:
    if row.live is None:
        retVal = "Session is not running"
    elif row.live.pid in (os.getpid(), os.getppid()):
        retVal = "Will not stop the hub itself"
    else:
        try:
            kill(row.live.pid, signal.SIGTERM)
            retVal = f"Stopped {row.title}"
        except ProcessLookupError:
            retVal = "Session already ended"
    return retVal


def rename(row: Row, title: str) -> str:
    title = " ".join(title.split())
    if not title:
        retVal = "Title is empty"
    elif len(title) > MAX_TITLE_LEN:
        retVal = f"Title is longer than {MAX_TITLE_LEN} characters"
    elif _needs_newline(row.meta.path):
        retVal = "Session is writing; try again"
    else:
        line = json.dumps({"type": "custom-title", "customTitle": title,
                           "sessionId": row.meta.session_id}) + "\n"
        _append_line(row.meta.path, line.encode())
        retVal = f"Renamed to {title}"
    return retVal


def _append_line(path: Path, data: bytes) -> None:
    """One write() on an O_APPEND fd, so a concurrent writer cannot split the line."""
    fd = os.open(path, os.O_WRONLY | os.O_APPEND)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _needs_newline(path: Path) -> bool:
    retVal = False
    size = path.stat().st_size
    if size > 0:
        with open(path, "rb") as f:
            f.seek(size - 1)
            retVal = f.read(1) != b"\n"
    return retVal
