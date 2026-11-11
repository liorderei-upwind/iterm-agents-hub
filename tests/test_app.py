import json
from pathlib import Path

import pytest

from agents_hub import app as app_mod
from agents_hub.app import HubApp, build_rows, short_model
from agents_hub.config import Paths
from agents_hub.index import Index
from agents_hub.models import LiveInfo, State

NOW = 2_000_000_000.0


def write(p: Path, *entries: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(e) + "\n" for e in entries))


def human(text: str, ts: str = "2033-05-18T03:00:00Z") -> dict:
    return {"type": "user", "origin": {"kind": "human"}, "timestamp": ts, "message": {"content": text}}


def reply(text: str, ts: str = "2033-05-18T03:00:05Z") -> dict:
    return {"type": "assistant", "timestamp": ts, "effort": "high",
            "message": {"model": "claude-opus-5-5", "content": [{"type": "text", "text": text}],
                        "usage": {"input_tokens": 1, "cache_read_input_tokens": 187_599}}}


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    p = Paths(tmp_path / "claude", tmp_path / "cache")
    proj = p.projects_dir / "-proj"
    write(proj / "live1.jsonl", {"type": "ai-title", "aiTitle": "Flink pilot"}, human("go"), reply("done"))
    write(proj / "old1.jsonl", {"type": "ai-title", "aiTitle": "CVE hotfix"},
          human("fix", "2026-01-01T00:00:00Z"), reply("ok", "2026-01-01T00:00:05Z"))
    write(proj / "old2.jsonl", {"type": "ai-title", "aiTitle": "SIEM design"},
          human("design", "2026-02-01T00:00:00Z"), reply("ok", "2026-02-01T00:00:05Z"))
    write(proj / "script.jsonl", {"type": "ai-title", "aiTitle": "Scripted run"},
          {"type": "user", "origin": {"kind": "task-notification"}, "message": {"content": "auto"}})
    return p


def live_info(sid="live1", status="busy", tty="ttys002") -> LiveInfo:
    return LiveInfo(pid=1, session_id=sid, cwd="/", status=status, name="x-b3", name_source="derived",
                    kind="interactive", updated_at=NOW, tty=tty)


def rows_for(paths, live, show_all=False, tabs=None):
    idx = Index(paths)
    return build_rows(idx.refresh(), live, tabs or {"ttys002": "w1:t3"}, NOW, show_all)


def test_build_rows_live_first_sorted(paths):
    rows = rows_for(paths, {"live1": live_info()})
    assert [r.title for r in rows] == ["Flink pilot", "SIEM design", "CVE hotfix"]
    assert rows[0].state is State.RUNNING
    assert rows[1].state is State.CLOSED


def test_build_rows_hides_non_human_unless_show_all(paths):
    assert "Scripted run" not in [r.title for r in rows_for(paths, {})]
    assert "Scripted run" in [r.title for r in rows_for(paths, {}, show_all=True)]


def test_build_rows_tab_label_from_tty(paths):
    assert rows_for(paths, {"live1": live_info()})[0].tab_label == "w1:t3"


def test_build_rows_no_tab_dash(paths):
    rows = rows_for(paths, {"live1": live_info(tty=None)})
    assert rows[0].tab_label is None


def test_short_model():
    assert short_model("claude-opus-5-5") == "opus-5.5"
    assert short_model("claude-sonnet-4-5-20250929") == "sonnet-4.5"
    assert short_model(None) == "—"


async def test_app_smoke(paths, monkeypatch):
    monkeypatch.setattr(app_mod, "read_live", lambda p: {})
    monkeypatch.setattr(app_mod.iterm, "tab_map", lambda: {})
    hub = HubApp(paths=paths)
    async with hub.run_test() as pilot:
        await pilot.pause()
        table = hub.query_one("#sessions")
        assert table.row_count == 3
        await pilot.press("slash")
        await pilot.press(*"cve")
        await pilot.press("enter")
        await pilot.pause()
        assert table.row_count == 1
        await pilot.press("p")
        await pilot.pause()
        assert hub.query_one("#preview").display is True


async def test_reload_error_does_not_close_hub(paths, monkeypatch):
    def boom(p):
        raise TimeoutError("ps hung")
    monkeypatch.setattr(app_mod, "read_live", boom)
    monkeypatch.setattr(app_mod.iterm, "tab_map", lambda: {})
    hub = HubApp(paths=paths)
    async with hub.run_test() as pilot:
        await pilot.pause(0.5)
        assert hub.is_running
        assert "ps hung" in hub._status_msg


async def test_refresh_does_not_overlap(paths, monkeypatch):
    import threading, time as _t
    active, peak = [0], [0]
    lock = threading.Lock()

    def slow(p):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        _t.sleep(0.3)
        with lock:
            active[0] -= 1
        return {}
    monkeypatch.setattr(app_mod, "read_live", slow)
    monkeypatch.setattr(app_mod.iterm, "tab_map", lambda: {})
    hub = HubApp(paths=paths)
    async with hub.run_test() as pilot:
        for _ in range(5):
            hub._reload()
        await pilot.pause(1.0)
    assert peak[0] == 1


async def test_rename_targets_row_from_when_box_opened(paths, monkeypatch):
    monkeypatch.setattr(app_mod, "read_live", lambda p: {})
    monkeypatch.setattr(app_mod.iterm, "tab_map", lambda: {})
    renamed = []
    monkeypatch.setattr(app_mod.actions, "rename", lambda row, t: renamed.append(row.meta.session_id) or "ok")
    hub = HubApp(paths=paths)
    async with hub.run_test() as pilot:
        await pilot.pause()
        table = hub.query_one("#sessions")
        table.move_cursor(row=1)
        target = hub._selected_id()
        await pilot.press("r")
        table.move_cursor(row=0)
        await pilot.press("enter")
        await pilot.pause()
    assert renamed == [target]


async def _hub_with_live(paths, monkeypatch):
    monkeypatch.setattr(app_mod, "read_live", lambda p: {"live1": live_info()})
    monkeypatch.setattr(app_mod.iterm, "tab_map", lambda: {})
    return HubApp(paths=paths)


async def test_stop_confirmation_expires(paths, monkeypatch):
    monkeypatch.setattr(app_mod, "STATUS_MSG_S", 0.2)
    stopped = []
    monkeypatch.setattr(app_mod.actions, "stop", lambda row: stopped.append(row) or "ok")
    hub = await _hub_with_live(paths, monkeypatch)
    async with hub.run_test() as pilot:
        await pilot.pause()
        hub.query_one("#sessions").move_cursor(row=0)
        await pilot.press("s")
        await pilot.pause(0.5)
        await pilot.press("y")
        await pilot.pause()
    assert stopped == []


async def test_escape_clears_filter(paths, monkeypatch):
    monkeypatch.setattr(app_mod, "read_live", lambda p: {})
    monkeypatch.setattr(app_mod.iterm, "tab_map", lambda: {})
    hub = HubApp(paths=paths)
    async with hub.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash", *"zzz")
        await pilot.pause()
        assert hub.query_one("#sessions").row_count == 0
        await pilot.press("escape")
        await pilot.pause()
        assert hub.query_one("#sessions").row_count == 3
