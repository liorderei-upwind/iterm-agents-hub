import json
import shutil
import signal
from pathlib import Path

import pytest

from agents_hub import actions
from agents_hub.config import Paths
from agents_hub.models import LiveInfo, Row, SessionMeta, State
from agents_hub.transcript import scan

FIX = Path(__file__).parent / "fixtures"


def make_row(tmp_path: Path, live: bool, tty: str | None = "ttys002") -> Row:
    p = tmp_path / "s1.jsonl"
    shutil.copy(FIX / "basic.jsonl", p)
    meta = scan(p, None)
    lv = LiveInfo(pid=4242, session_id="s1", cwd="/Users/me/proj", status="idle", name=None,
                  name_source=None, kind="interactive", updated_at=0, tty=tty) if live else None
    return Row(meta=meta, live=lv, state=State.IDLE if live else State.CLOSED, title="t", tab_label=None)


@pytest.fixture
def calls(monkeypatch):
    rec = {"focus": [], "new_tab": []}
    monkeypatch.setattr(actions.iterm, "focus", lambda tty: rec["focus"].append(tty) or True)
    monkeypatch.setattr(actions.iterm, "new_tab", lambda cwd, cmd: rec["new_tab"].append((cwd, cmd)))
    return rec


def test_resume_live_goes_to_tab(tmp_path, calls):
    actions.resume(make_row(tmp_path, live=True))
    assert calls["focus"] == ["ttys002"]
    assert calls["new_tab"] == []


def test_resume_closed_opens_tab(tmp_path, calls):
    row = make_row(tmp_path, live=False)
    row.meta.cwd = str(tmp_path)
    actions.resume(row)
    assert calls["new_tab"] == [(str(tmp_path), "claude --resume s1")]


def test_resume_missing_cwd_uses_home(tmp_path, calls):
    actions.resume(make_row(tmp_path, live=False))
    assert calls["new_tab"] == [(str(Path.home()), "claude --resume s1")]


def test_go_to_no_tty_message(tmp_path, calls):
    msg = actions.go_to(make_row(tmp_path, live=True, tty=None))
    assert msg == "Session runs outside iTerm (pid 4242)"
    assert calls["focus"] == []


def test_stop_sends_sigterm(tmp_path):
    sent = []
    actions.stop(make_row(tmp_path, live=True), kill=lambda pid, sig: sent.append((pid, sig)))
    assert sent == [(4242, signal.SIGTERM)]


def test_stop_closed_rejected(tmp_path):
    sent = []
    msg = actions.stop(make_row(tmp_path, live=False), kill=lambda pid, sig: sent.append(pid))
    assert sent == [] and msg == "Session is not running"


def test_rename_appends_one_line(tmp_path):
    row = make_row(tmp_path, live=False)
    before = row.meta.path.read_text().splitlines()
    actions.rename(row, "  New topic  ")
    after = row.meta.path.read_text()
    assert after.endswith("\n")
    lines = after.splitlines()
    assert len(lines) == len(before) + 1
    assert json.loads(lines[-1]) == {"type": "custom-title", "customTitle": "New topic", "sessionId": "s1"}


def test_rename_rejects_empty(tmp_path):
    row = make_row(tmp_path, live=False)
    before = row.meta.path.read_text()
    assert actions.rename(row, "   ") == "Title is empty"
    assert row.meta.path.read_text() == before


def test_rename_then_scan_shows_title(tmp_path):
    row = make_row(tmp_path, live=False)
    actions.rename(row, "Renamed topic")
    assert scan(row.meta.path, row.meta).custom_title == "Renamed topic"


def test_rename_refuses_when_last_line_incomplete(tmp_path):
    row = make_row(tmp_path, live=True)
    with open(row.meta.path, "a") as f:
        f.write('{"type":"assist')
    before = row.meta.path.read_text()
    assert actions.rename(row, "X") == "Session is writing; try again"
    assert row.meta.path.read_text() == before


def test_resume_quotes_session_id(tmp_path, calls):
    row = make_row(tmp_path, live=False)
    row.meta.cwd = str(tmp_path)
    row.meta.session_id = "a b;rm"
    actions.resume(row)
    assert calls["new_tab"][0][1] == "claude --resume 'a b;rm'"
