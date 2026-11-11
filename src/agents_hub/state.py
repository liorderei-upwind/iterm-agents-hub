from __future__ import annotations

from agents_hub.models import LiveInfo, SessionMeta, State

WAIT_WINDOW_S = 30 * 60
PENDING_TOOL_GRACE_S = 3


def classify(meta: SessionMeta, live: LiveInfo | None, now: float) -> State:
    if live is None:
        retVal = State.CLOSED
    elif live.status == "waiting":
        retVal = State.WAITING
    elif live.status == "busy":
        retVal = State.RUNNING
    elif meta.last_entry_kind == "tool_use_pending" and now - live.updated_at > PENDING_TOOL_GRACE_S:
        retVal = State.WAITING
    elif meta.last_entry_kind in ("assistant_text", "tool_use_pending") and \
            now - (meta.last_activity or live.updated_at) < WAIT_WINDOW_S:
        retVal = State.WAITING
    else:
        retVal = State.IDLE
    return retVal
