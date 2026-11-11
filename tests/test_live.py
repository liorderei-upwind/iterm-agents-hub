import json
from pathlib import Path

import pytest

from agents_hub.config import Paths
from agents_hub.live import ProcInfo, read_live


def write_session(p: Paths, pid: int, sid: str, **extra) -> None:
    p.sessions_dir.mkdir(parents=True, exist_ok=True)
    d = {"pid": pid, "sessionId": sid, "cwd": "/w", "procStart": "Wed Nov 11 10:37:31 2026",
         "kind": "interactive", "name": "w-b3", "nameSource": "derived", "status": "idle",
         "updatedAt": 1794394750975}
    d.update(extra)
    (p.sessions_dir / f"{pid}.json").write_text(json.dumps(d))


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(tmp_path / "claude", tmp_path / "cache")


def procs(*entries):
    return lambda pids: {e.pid: e for e in entries if e.pid in pids}


def test_live_read(paths):
    write_session(paths, 10, "sA", status="waiting", waitingFor="input needed")
    live = read_live(paths, procs(ProcInfo(10, "ttys002", "Wed Nov 11  10:37:31 2026")))
    info = live["sA"]
    assert info.pid == 10 and info.tty == "ttys002" and info.status == "waiting"
    assert info.waiting_for == "input needed"
    assert info.updated_at == pytest.approx(1794394750.975)
    assert info.name_source == "derived"


def test_dead_pid_ignored(paths):
    write_session(paths, 11, "sB")
    assert read_live(paths, procs()) == {}


def test_reused_pid_ignored(paths):
    write_session(paths, 12, "sC")
    assert read_live(paths, procs(ProcInfo(12, "ttys001", "Thu Nov 12 09:00:00 2026"))) == {}


def test_no_tty(paths):
    write_session(paths, 13, "sD")
    live = read_live(paths, procs(ProcInfo(13, None, "Wed Nov 11 10:37:31 2026")))
    assert live["sD"].tty is None


def test_bad_json_ignored(paths):
    paths.sessions_dir.mkdir(parents=True)
    (paths.sessions_dir / "99.json").write_text("{")
    assert read_live(paths, procs()) == {}


def test_half_written_file_keeps_last_good(paths):
    write_session(paths, 14, "sE")
    lookup = procs(ProcInfo(14, "ttys001", "Wed Nov 11 10:37:31 2026"))
    assert "sE" in read_live(paths, lookup)
    (paths.sessions_dir / "14.json").write_text('{"pid":14,"sess')
    assert "sE" in read_live(paths, lookup)
