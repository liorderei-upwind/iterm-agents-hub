import json
import shutil
from pathlib import Path

from agents_hub.transcript import last_messages, scan

FIX = Path(__file__).parent / "fixtures"


def copy_fixture(tmp_path: Path, name: str = "basic.jsonl") -> Path:
    dst = tmp_path / "s1.jsonl"
    shutil.copy(FIX / name, dst)
    return dst


def test_scan_basic(tmp_path):
    m = scan(copy_fixture(tmp_path), None)
    assert m.session_id == "s1"
    assert m.ai_title == "Flink process-events pilot"
    assert m.model == "claude-opus-5-5"
    assert m.context_tokens == 3 + 500 + 40000
    assert m.first_prompt == "Fix the flink pilot bug"
    assert m.effort == "medium"
    assert m.cwd == "/Users/me/proj"
    assert m.has_human_prompt is True
    assert m.last_entry_kind == "assistant_text"
    assert m.last_activity is not None
    assert m.offset == m.size


def test_scan_last_ai_title_wins(tmp_path):
    assert scan(copy_fixture(tmp_path), None).ai_title == "Flink process-events pilot"


def test_scan_partial_line_not_consumed(tmp_path):
    p = copy_fixture(tmp_path)
    full = json.dumps({"type": "ai-title", "aiTitle": "Later title"})
    with open(p, "a") as f:
        f.write(full[:10])
    m1 = scan(p, None)
    assert m1.ai_title == "Flink process-events pilot"
    assert m1.offset == p.stat().st_size - 10
    with open(p, "a") as f:
        f.write(full[10:] + "\n")
    m2 = scan(p, m1)
    assert m2.ai_title == "Later title"
    assert m2.offset == p.stat().st_size


def test_scan_skips_bad_lines(tmp_path):
    p = copy_fixture(tmp_path)
    with open(p, "ab") as f:
        f.write(b"\xff\xfe not json\n")
        f.write(b"{broken\n")
        f.write(json.dumps({"type": "custom-title", "customTitle": "Renamed"}).encode() + b"\n")
    assert scan(p, None).custom_title == "Renamed"


def test_pending_tool_use(tmp_path):
    p = tmp_path / "s2.jsonl"
    p.write_text(json.dumps({"type": "assistant", "message": {"model": "m", "content": [
        {"type": "tool_use", "id": "tuX", "name": "Bash", "input": {}}]}}) + "\n")
    m = scan(p, None)
    assert m.last_entry_kind == "tool_use_pending"
    with open(p, "a") as f:
        f.write(json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tuX", "content": "ok"}]}}) + "\n")
    m2 = scan(p, m)
    assert m2.last_entry_kind != "tool_use_pending"
    assert m2.pending_tool_ids == set()


def test_shrunk_file_full_rescan(tmp_path):
    p = copy_fixture(tmp_path)
    m1 = scan(p, None)
    p.write_text(json.dumps({"type": "ai-title", "aiTitle": "New"}) + "\n")
    m2 = scan(p, m1)
    assert m2.ai_title == "New"
    assert m2.model is None


def test_human_prompt_detection(tmp_path):
    p = tmp_path / "s3.jsonl"
    p.write_text("\n".join(json.dumps(d) for d in [
        {"type": "user", "isMeta": True, "message": {"content": "meta"}},
        {"type": "user", "message": {"content": "<command-name>/x</command-name>"}},
        {"type": "user", "origin": {"kind": "task-notification"}, "message": {"content": "note"}},
    ]) + "\n")
    m = scan(p, None)
    assert m.has_human_prompt is False
    assert m.first_prompt is None


def test_last_messages(tmp_path):
    msgs = last_messages(copy_fixture(tmp_path), 10)
    assert msgs == [
        ("user", "Fix the flink pilot bug"),
        ("assistant", "I look at the code."),
        ("user", "Second question"),
        ("assistant", "Final answer."),
    ]


def test_last_messages_limit(tmp_path):
    assert last_messages(copy_fixture(tmp_path), 2) == [
        ("user", "Second question"), ("assistant", "Final answer.")]


def test_scan_reads_in_chunks(tmp_path, monkeypatch):
    from agents_hub import transcript
    monkeypatch.setattr(transcript, "READ_CHUNK", 64)
    p = copy_fixture(tmp_path)
    m = scan(p, None)
    assert m.ai_title == "Flink process-events pilot"
    assert m.context_tokens == 3 + 500 + 40000
    assert m.offset == p.stat().st_size


def test_scan_survives_odd_shapes(tmp_path):
    p = tmp_path / "s4.jsonl"
    p.write_text("\n".join(json.dumps(d) for d in [
        {"type": "assistant", "message": "not a dict"},
        {"type": "assistant", "message": {"usage": {"input_tokens": "x"}, "content": "str"}},
        {"type": "user", "message": ["list"]},
        {"type": "ai-title", "aiTitle": "Still parsed"},
    ]) + "\n")
    assert scan(p, None).ai_title == "Still parsed"


def test_replaced_file_same_size_full_rescan(tmp_path):
    p = copy_fixture(tmp_path)
    m1 = scan(p, None)
    other = tmp_path / "other.jsonl"
    data = p.read_bytes().replace(b"Flink process-events pilot", b"Other topic title here....")
    other.write_bytes(data)
    assert other.stat().st_size == p.stat().st_size
    other.replace(p)
    assert scan(p, m1).ai_title == "Other topic title here...."
