"""Entry point for `agents`: one hub per machine; a second call jumps to the open hub."""
from __future__ import annotations

import fcntl
import os
import sys

from agents_hub import iterm
from agents_hub.app import HubApp
from agents_hub.config import default_paths


def main() -> None:
    paths = default_paths()
    paths.cache_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(paths.lock_file, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        _jump_to_running_hub(fd)
        return
    os.ftruncate(fd, 0)
    os.write(fd, (iterm.own_tty() or "").encode())
    try:
        HubApp(paths=paths).run()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _jump_to_running_hub(fd: int) -> None:
    tty = os.read(fd, 64).decode().strip()
    os.close(fd)
    try:
        focused = bool(tty) and iterm.focus(tty)
    except iterm.ItermError:
        focused = False
    if focused:
        print("agents hub is already open; switched to its tab.")
    else:
        print("agents hub is already running in another terminal.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
