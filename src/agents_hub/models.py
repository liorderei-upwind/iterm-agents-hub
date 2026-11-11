from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class State(Enum):
    RUNNING = "running"
    WAITING = "waiting"
    IDLE = "idle"
    CLOSED = "closed"


@dataclass
class SessionMeta:
    session_id: str
    path: Path
    cwd: str | None = None
    ai_title: str | None = None
    custom_title: str | None = None
    first_prompt: str | None = None
    model: str | None = None
    effort: str | None = None
    context_tokens: int | None = None
    last_activity: float | None = None
    last_entry_kind: str | None = None
    has_human_prompt: bool = False
    offset: int = 0
    size: int = 0
    mtime: float = 0.0
    inode: int = 0
    pending_tool_ids: set[str] = field(default_factory=set)


@dataclass
class LiveInfo:
    pid: int
    session_id: str
    cwd: str
    status: str
    name: str | None
    name_source: str | None
    kind: str
    updated_at: float
    tty: str | None
    waiting_for: str | None = None
    proc_start: str | None = None


@dataclass
class Row:
    meta: SessionMeta
    live: LiveInfo | None
    state: State
    title: str
    tab_label: str | None


TITLE_PROMPT_LEN = 60


def display_title(meta: SessionMeta, live: LiveInfo | None, hub_title: str | None) -> str:
    user_name = live.name if live and live.name and live.name_source != "derived" else None
    candidates = [
        hub_title,
        meta.custom_title,
        user_name,
        meta.ai_title,
        meta.first_prompt[:TITLE_PROMPT_LEN] if meta.first_prompt else None,
    ]
    return next((c for c in candidates if c), meta.session_id[:8])


def format_tokens(n: int | None) -> str:
    if n is None:
        retVal = "—"
    elif n < 1000:
        retVal = str(n)
    else:
        retVal = f"{round(n / 1000)}k"
    return retVal
