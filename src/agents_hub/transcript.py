"""Incremental parser for Claude Code session transcripts (.jsonl, append-only)."""
from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from pathlib import Path

from agents_hub.models import SessionMeta

TAIL_BLOCK = 256 * 1024
READ_CHUNK = 8 * 1024 * 1024


def scan(path: Path, prev: SessionMeta | None) -> SessionMeta:
    st = path.stat()
    if prev is not None and st.st_size >= prev.offset and st.st_ino == prev.inode:
        meta = copy.deepcopy(prev)
    else:
        meta = SessionMeta(session_id=path.stem, path=path)
    with open(path, "rb") as f:
        f.seek(meta.offset)
        carry = b""
        while chunk := f.read(READ_CHUNK):
            data = carry + chunk
            consumed = data.rfind(b"\n") + 1
            for raw in data[:consumed].split(b"\n"):
                _apply_safe(meta, _parse_line(raw))
            meta.offset += consumed
            carry = data[consumed:]
    meta.size = st.st_size
    meta.mtime = st.st_mtime
    meta.inode = st.st_ino
    return meta


def last_messages(path: Path, n: int = 10) -> list[tuple[str, str]]:
    size = path.stat().st_size
    block = TAIL_BLOCK
    retVal: list[tuple[str, str]] = []
    while True:
        start = max(0, size - block)
        with open(path, "rb") as f:
            f.seek(start)
            data = f.read()
        lines = data.split(b"\n")
        if start > 0:
            lines = lines[1:]
        found = [m for m in (_message_text(_parse_line(l)) for l in lines) if m]
        retVal = found[-n:]
        if len(found) >= n or start == 0:
            break
        block *= 4
    return retVal


def _parse_line(raw: bytes) -> dict | None:
    retVal = None
    if raw.strip():
        try:
            parsed = json.loads(raw.decode("utf-8", errors="replace"))
            retVal = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            retVal = None
    return retVal


def _apply_safe(meta: SessionMeta, entry: dict | None) -> None:
    if entry is not None:
        try:
            _apply(meta, entry)
        except (AttributeError, TypeError, ValueError):
            pass


def _apply(meta: SessionMeta, e: dict) -> None:
    if e.get("isSidechain"):
        return
    kind = e.get("type")
    if e.get("cwd"):
        meta.cwd = e["cwd"]
    ts = _epoch(e.get("timestamp"))
    if ts is not None and kind in ("user", "assistant"):
        meta.last_activity = ts
    if kind == "ai-title" and e.get("aiTitle"):
        meta.ai_title = e["aiTitle"]
    elif kind == "custom-title":
        title = e.get("customTitle") or e.get("title")
        if title:
            meta.custom_title = title
    elif kind == "user":
        _apply_user(meta, e)
    elif kind == "assistant":
        _apply_assistant(meta, e)


def _apply_user(meta: SessionMeta, e: dict) -> None:
    content = (e.get("message") or {}).get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                meta.pending_tool_ids.discard(block.get("tool_use_id"))
    text = _human_text(e)
    if text is not None:
        meta.has_human_prompt = True
        meta.last_entry_kind = "user"
        if meta.first_prompt is None:
            meta.first_prompt = " ".join(text.split())
    elif not meta.pending_tool_ids and meta.last_entry_kind == "tool_use_pending":
        meta.last_entry_kind = "assistant_text"


def _apply_assistant(meta: SessionMeta, e: dict) -> None:
    msg = e.get("message") or {}
    if msg.get("model") and msg["model"] != "<synthetic>":
        meta.model = msg["model"]
    if e.get("effort"):
        meta.effort = e["effort"]
    usage = msg.get("usage")
    if isinstance(usage, dict):
        meta.context_tokens = sum(int(usage.get(k) or 0) for k in (
            "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    for block in msg.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id"):
            meta.pending_tool_ids.add(block["id"])
    meta.last_entry_kind = "tool_use_pending" if meta.pending_tool_ids else "assistant_text"


def _human_text(e: dict) -> str | None:
    """Text of a prompt a person typed, or None for tool results, meta and system entries."""
    retVal = None
    if e.get("type") == "user" and not e.get("isMeta") and not e.get("isSidechain"):
        origin = e.get("origin")
        origin_kind = origin.get("kind") if isinstance(origin, dict) else None
        text = _text_of((e.get("message") or {}).get("content"))
        if text and origin_kind in ("human", None) and not text.lstrip().startswith("<"):
            retVal = text
    return retVal


def _message_text(e: dict | None) -> tuple[str, str] | None:
    retVal = None
    if e is not None and not e.get("isSidechain"):
        if e.get("type") == "user":
            text = _human_text(e)
            retVal = ("user", text) if text else None
        elif e.get("type") == "assistant":
            text = _text_of((e.get("message") or {}).get("content"))
            retVal = ("assistant", text) if text else None
    return retVal


def _text_of(content) -> str | None:
    if isinstance(content, str):
        retVal = content
    elif isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        retVal = "\n".join(p for p in parts if p) or None
    else:
        retVal = None
    return retVal.strip() if retVal and retVal.strip() else None


def _epoch(ts) -> float | None:
    retVal = None
    if isinstance(ts, str):
        try:
            retVal = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            retVal = None
    return retVal
