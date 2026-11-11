"""iTerm2 control through AppleScript (osascript)."""
from __future__ import annotations

import os
import shlex
import subprocess

OSASCRIPT_TIMEOUT_S = 5


class ItermError(RuntimeError):
    pass


def tab_map() -> dict[str, str]:
    """Map tty name (e.g. 'ttys002') to a 'w<window>:t<tab>' label, both 1-based."""
    script = '''
set out to ""
set sep to (ASCII character 9)
if application "iTerm2" is not running then return ""
tell application "iTerm2"
  set wi to 0
  repeat with w in windows
    set wi to wi + 1
    set ti to 0
    repeat with t in tabs of w
      set ti to ti + 1
      repeat with s in sessions of t
        set out to out & (tty of s) & sep & wi & sep & ti & (ASCII character 10)
      end repeat
    end repeat
  end repeat
end tell
return out
'''
    retVal: dict[str, str] = {}
    for line in _osascript(script).splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            retVal[parts[0].removeprefix("/dev/")] = f"w{parts[1]}:t{parts[2]}"
    return retVal


def focus(tty: str) -> bool:
    script = f'''
tell application "iTerm2"
  repeat with w in windows
    repeat with t in tabs of w
      repeat with s in sessions of t
        if tty of s is {_as_string("/dev/" + tty)} then
          select w
          select t
          select s
          activate
          return "ok"
        end if
      end repeat
    end repeat
  end repeat
end tell
return "notfound"
'''
    return _osascript(script).strip() == "ok"


def new_tab(cwd: str, command: str) -> None:
    line = f"cd {shlex.quote(cwd)} && {command}"
    script = f'''
tell application "iTerm2"
  tell current window
    set t to (create tab with default profile)
    tell current session of t to write text {_as_string(line)}
  end tell
  activate
end tell
'''
    _osascript(script)


def own_tty() -> str | None:
    try:
        retVal = os.ttyname(0).removeprefix("/dev/")
    except OSError:
        retVal = None
    return retVal


def _as_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _osascript(script: str) -> str:
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True,
                              timeout=OSASCRIPT_TIMEOUT_S)
    except subprocess.TimeoutExpired as e:
        raise ItermError("iTerm did not answer in time") from e
    if proc.returncode != 0:
        raise ItermError(proc.stderr.strip() or "osascript failed")
    return proc.stdout
