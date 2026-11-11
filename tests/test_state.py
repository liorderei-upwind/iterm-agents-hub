from pathlib import Path

from agents_hub.models import LiveInfo, SessionMeta, State
from agents_hub.state import WAIT_WINDOW_S, classify

NOW = 2_000_000_000.0


def meta(**kw) -> SessionMeta:
    m = SessionMeta(session_id="s", path=Path("/s.jsonl"))
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def live(status="idle", updated_at=NOW - 10, **kw) -> LiveInfo:
    return LiveInfo(pid=1, session_id="s", cwd="/", status=status, name=None, name_source=None,
                    kind="interactive", updated_at=updated_at, tty="ttys001", **kw)


def test_classify_closed():
    assert classify(meta(), None, NOW) is State.CLOSED


def test_classify_running():
    assert classify(meta(last_activity=NOW - 5000), live("busy"), NOW) is State.RUNNING


def test_classify_waiting_status():
    lv = live("waiting", waiting_for="input needed", updated_at=NOW - 5000)
    assert classify(meta(last_activity=NOW - 5000), lv, NOW) is State.WAITING


def test_classify_waiting_pending_tool():
    m = meta(last_entry_kind="tool_use_pending", last_activity=NOW - 5000)
    assert classify(m, live("idle", updated_at=NOW - 60), NOW) is State.WAITING


def test_classify_waiting_recent_turn():
    m = meta(last_entry_kind="assistant_text", last_activity=NOW - 60)
    assert classify(m, live("idle"), NOW) is State.WAITING


def test_classify_idle_old():
    m = meta(last_entry_kind="assistant_text", last_activity=NOW - WAIT_WINDOW_S - 1)
    assert classify(m, live("idle", updated_at=NOW - WAIT_WINDOW_S - 1), NOW) is State.IDLE


def test_classify_idle_when_user_spoke_last():
    m = meta(last_entry_kind="user", last_activity=NOW - 60)
    assert classify(m, live("idle"), NOW) is State.IDLE
