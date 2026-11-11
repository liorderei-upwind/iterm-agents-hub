import json
from pathlib import Path

import pytest

from agents_hub import index as index_mod
from agents_hub.config import Paths
from agents_hub.index import Index


def line(d: dict) -> str:
    return json.dumps(d) + "\n"


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    p = Paths(tmp_path / "claude", tmp_path / "cache")
    a = p.projects_dir / "-proj-a"
    b = p.projects_dir / "-proj-b"
    (a / "sub1" / "subagents").mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "s1.jsonl").write_text(line({"type": "ai-title", "aiTitle": "One"}))
    (a / "s2.jsonl").write_text(line({"type": "ai-title", "aiTitle": "Two"}))
    (b / "s3.jsonl").write_text(line({"type": "ai-title", "aiTitle": "Three"}))
    (a / "sub1" / "subagents" / "agent-x.jsonl").write_text(line({"type": "ai-title", "aiTitle": "Sub"}))
    return p


def test_refresh_finds_sessions(paths):
    metas = Index(paths).refresh()
    assert sorted(m.ai_title for m in metas) == ["One", "Three", "Two"]


def test_refresh_rescans_only_changed(paths, monkeypatch):
    calls = []
    real = index_mod.scan

    def counting(path, prev):
        calls.append(path.name)
        return real(path, prev)

    monkeypatch.setattr(index_mod, "scan", counting)
    idx = Index(paths)
    idx.refresh()
    calls.clear()
    idx.refresh()
    assert calls == []
    with open(paths.projects_dir / "-proj-a" / "s1.jsonl", "a") as f:
        f.write(line({"type": "ai-title", "aiTitle": "One v2"}))
    idx.refresh()
    assert calls == ["s1.jsonl"]
    assert idx.get("s1").ai_title == "One v2"


def test_save_load_roundtrip(paths):
    idx = Index(paths)
    idx.refresh()
    idx.get("s1").pending_tool_ids.add("t1")
    idx.save()
    idx2 = Index(paths)
    idx2.load()
    assert idx2.get("s1").ai_title == "One"
    assert idx2.get("s1").pending_tool_ids == {"t1"}
    assert isinstance(idx2.get("s1").path, Path)


def test_corrupt_cache_ignored(paths):
    paths.cache_dir.mkdir(parents=True)
    paths.index_file.write_text("{")
    idx = Index(paths)
    idx.load()
    assert len(idx.refresh()) == 3


def test_deleted_file_dropped(paths):
    idx = Index(paths)
    idx.refresh()
    (paths.projects_dir / "-proj-b" / "s3.jsonl").unlink()
    assert sorted(m.session_id for m in idx.refresh()) == ["s1", "s2"]
    assert idx.get("s3") is None


def test_refresh_skips_file_that_raises(paths, monkeypatch):
    real = index_mod.scan

    def flaky(path, prev):
        if path.name == "s2.jsonl":
            raise ValueError("boom")
        return real(path, prev)

    monkeypatch.setattr(index_mod, "scan", flaky)
    assert sorted(m.session_id for m in Index(paths).refresh()) == ["s1", "s3"]


def test_save_failure_leaves_no_temp_file(paths, monkeypatch):
    idx = Index(paths)
    idx.refresh()
    monkeypatch.setattr(index_mod.json, "dump", lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))
    with pytest.raises(ValueError):
        idx.save()
    assert [f.name for f in paths.cache_dir.iterdir() if f.name.startswith(".index-")] == []


def test_old_cache_entry_without_inode_loads(paths):
    idx = Index(paths)
    idx.refresh()
    idx.save()
    raw = json.loads(paths.index_file.read_text())
    for d in raw["sessions"].values():
        d.pop("inode", None)
    paths.index_file.write_text(json.dumps(raw))
    idx2 = Index(paths)
    idx2.load()
    assert len(idx2.refresh()) == 3
