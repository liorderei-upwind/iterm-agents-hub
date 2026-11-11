"""Textual UI for the agents hub."""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import DataTable, Footer, Input, Static

from agents_hub import actions, iterm
from agents_hub.config import Paths, default_paths
from agents_hub.index import Index
from agents_hub.live import read_live
from agents_hub.models import LiveInfo, Row, SessionMeta, State, display_title, format_tokens
from agents_hub.state import classify
from agents_hub.transcript import last_messages

REFRESH_S = 1.5
STATUS_MSG_S = 4
PREVIEW_MESSAGES = 10
STATE_ORDER = {State.RUNNING: 0, State.WAITING: 1, State.IDLE: 2, State.CLOSED: 3}
STATE_LOOK = {
    State.RUNNING: ("● running", "green"),
    State.WAITING: ("◐ waiting", "yellow"),
    State.IDLE: ("○ idle", "grey50"),
    State.CLOSED: ("", "grey50"),
}
COLUMNS = ("State", "Title", "Tab", "Model", "Effort", "Tokens", "Last active", "Folder")


def build_rows(metas: list[SessionMeta], live_by_id: dict[str, LiveInfo], tab_by_tty: dict[str, str],
               now: float, show_all: bool) -> list[Row]:
    retVal = []
    for meta in metas:
        live = live_by_id.get(meta.session_id)
        if live is None and not show_all and not meta.has_human_prompt:
            continue
        tab = tab_by_tty.get(live.tty) if live and live.tty else None
        retVal.append(Row(meta=meta, live=live, state=classify(meta, live, now),
                          title=display_title(meta, live, None), tab_label=tab))
    retVal.sort(key=lambda r: (STATE_ORDER[r.state], -(r.meta.last_activity or r.meta.mtime)))
    return retVal


def short_model(model: str | None) -> str:
    if not model:
        retVal = "—"
    else:
        name = re.sub(r"-\d{8}$", "", model.removeprefix("claude-"))
        retVal = re.sub(r"-(\d+)-(\d+)$", r"-\1.\2", name)
    return retVal


def _folder(cwd: str | None) -> str:
    home = str(Path.home())
    return ("~" + cwd[len(home):]) if cwd and cwd.startswith(home) else (cwd or "—")


def _when(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "—"


class HubApp(App):
    TITLE = "agents"
    CSS = """
    #topbar { height: 1; padding: 0 1; }
    #search, #rename { dock: top; display: none; }
    #main { height: 1fr; }
    #sessions { width: 1fr; }
    #preview { width: 40%; display: none; border-left: solid $panel-lighten-2; padding: 0 1; }
    #status { height: 1; padding: 0 1; color: $warning; }
    """
    BINDINGS = [
        Binding("enter", "open", "go/resume", priority=False),
        Binding("p", "toggle_preview", "preview"),
        Binding("slash", "search", "search"),
        Binding("r", "rename", "rename"),
        Binding("s", "stop", "stop"),
        Binding("y", "confirm_stop", "confirm", show=False),
        Binding("a", "toggle_all", "show all"),
        Binding("escape", "cancel", "cancel", show=False),
        Binding("q", "quit", "quit"),
    ]

    def __init__(self, paths: Paths | None = None):
        super().__init__()
        self._paths = paths or default_paths()
        self._index = Index(self._paths)
        self._index.load()
        self._rows: list[Row] = []
        self._filter = ""
        self._show_all = False
        self._pending_stop: Row | None = None
        self._preview_for: str | None = None
        self._status_msg = ""
        self._refresh_guard = threading.Lock()
        self._rename_target: str | None = None
        self._shown: list | None = None

    def compose(self) -> ComposeResult:
        yield Input(placeholder="search titles…", id="search")
        yield Input(placeholder="new title", id="rename")
        yield Static("indexing sessions… (first start can take ~10 s)", id="topbar")
        with Horizontal(id="main"):
            yield DataTable(id="sessions", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="preview"):
                yield Static("", id="preview-text")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#sessions", DataTable)
        table.add_columns(*COLUMNS)
        table.focus()
        self._reload()
        self.set_interval(REFRESH_S, self._reload)

    def on_unmount(self) -> None:
        try:
            self._index.save()
        except OSError:
            pass

    # region data refresh
    def _reload(self) -> None:
        if self._refresh_guard.acquire(blocking=False):
            self._reload_worker()

    @work(thread=True, group="refresh")
    def _reload_worker(self) -> None:
        try:
            metas = self._index.refresh()
            live = read_live(self._paths)
            try:
                tabs = iterm.tab_map() if live else {}
            except iterm.ItermError:
                tabs = {}
            rows = build_rows(metas, live, tabs, time.time(), self._show_all)
            self.call_from_thread(self._show_rows, rows)
        except Exception as e:  # a refresh error must never close the hub
            self.call_from_thread(self._status, f"Refresh error: {e}")
        finally:
            self._refresh_guard.release()

    def _show_rows(self, rows: list[Row]) -> None:
        self._rows = rows
        table = self.query_one("#sessions", DataTable)
        selected = self._selected_id()
        visible = [r for r in rows if self._filter in r.title.lower()]
        cells = [(r.meta.session_id, self._cells(r)) for r in visible]
        shown = [(sid, tuple(str(c) for c in row)) for sid, row in cells]
        if shown != self._shown:
            self._shown = shown
            table.clear()
            for sid, row in cells:
                table.add_row(*row, key=sid)
        if selected is not None and selected != self._selected_id():
            try:
                table.move_cursor(row=table.get_row_index(selected), animate=False)
            except Exception:
                pass
        n_live = sum(1 for r in rows if r.live)
        self.query_one("#topbar", Static).update(
            f"{n_live} live · {len(rows) - n_live} closed"
            + (f"   filter: {self._filter!r}" if self._filter else "")
            + ("   [all sessions]" if self._show_all else ""))
        self._update_preview()

    def _cells(self, r: Row) -> tuple:
        label, color = STATE_LOOK[r.state]
        dim = "grey50" if r.state is State.CLOSED else ""
        if r.live:
            return (Text(label, style=color), Text(r.title, style="bold"), r.tab_label or "—",
                    short_model(r.meta.model), r.meta.effort or "—", format_tokens(r.meta.context_tokens),
                    _when(r.meta.last_activity), _folder(r.live.cwd or r.meta.cwd))
        return (Text(label), Text(r.title, style=dim), "", Text(short_model(r.meta.model), style=dim),
                "", "", Text(_when(r.meta.last_activity or r.meta.mtime), style=dim),
                Text(_folder(r.meta.cwd), style=dim))
    # endregion

    # region selection helpers
    def _selected_id(self) -> str | None:
        table = self.query_one("#sessions", DataTable)
        retVal = None
        if table.row_count:
            try:
                retVal = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            except Exception:
                retVal = None
        return retVal

    def _selected_row(self) -> Row | None:
        sid = self._selected_id()
        return next((r for r in self._rows if r.meta.session_id == sid), None)

    def _status(self, msg: str) -> None:
        self._status_msg = msg
        self.query_one("#status", Static).update(msg)
        self.set_timer(STATUS_MSG_S, lambda: self._clear_status(msg))

    def _clear_status(self, msg: str) -> None:
        if self._status_msg == msg:
            self._status_msg = ""
            self.query_one("#status", Static).update("")

    def _run_action(self, fn, *args) -> None:
        try:
            self._status(fn(*args))
        except Exception as e:  # iTerm errors, OS errors: show, never crash the hub
            self._status(f"Error: {e}")
        self._reload()
    # endregion

    # region preview
    @on(DataTable.RowHighlighted)
    def _row_changed(self, _event) -> None:
        self._update_preview()

    def _update_preview(self) -> None:
        pane = self.query_one("#preview")
        row = self._selected_row()
        if not pane.display or row is None:
            return
        key = f"{row.meta.session_id}:{row.meta.size}"
        if key == self._preview_for:
            return
        self._preview_for = key
        text = Text()
        text.append(row.title + "\n", style="bold")
        if row.live and row.live.waiting_for:
            text.append(f"waiting for: {row.live.waiting_for}\n", style="yellow")
        text.append(f"{row.meta.session_id}  {_folder(row.meta.cwd)}\n\n", style="grey50")
        try:
            msgs = last_messages(row.meta.path, PREVIEW_MESSAGES)
        except OSError:
            msgs = []
        for role, body in msgs:
            text.append("you: " if role == "user" else "claude: ", style="cyan" if role == "user" else "green")
            text.append(body.strip()[:1500] + "\n\n")
        self.query_one("#preview-text", Static).update(text)
    # endregion

    # region actions
    @on(DataTable.RowSelected)
    def _row_selected(self, _event) -> None:
        self.action_open()

    def action_open(self) -> None:
        row = self._selected_row()
        if row is not None:
            self._run_action(actions.resume, row)

    def action_toggle_preview(self) -> None:
        pane = self.query_one("#preview")
        pane.display = not pane.display
        self._preview_for = None
        self._update_preview()

    def action_search(self) -> None:
        box = self.query_one("#search", Input)
        box.display = True
        box.value = self._filter
        box.focus()

    @on(Input.Changed, "#search")
    def _search_changed(self, event: Input.Changed) -> None:
        self._filter = event.value.strip().lower()
        self._show_rows(self._rows)

    @on(Input.Submitted, "#search")
    def _search_done(self, _event) -> None:
        self.query_one("#search").display = False
        self.query_one("#sessions").focus()

    def action_rename(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        self._rename_target = row.meta.session_id
        box = self.query_one("#rename", Input)
        box.display = True
        box.value = row.title
        box.focus()

    @on(Input.Submitted, "#rename")
    def _rename_done(self, event: Input.Submitted) -> None:
        event.input.display = False
        self.query_one("#sessions").focus()
        target, self._rename_target = self._rename_target, None
        row = next((r for r in self._rows if r.meta.session_id == target), None)
        if row is not None:
            self._run_action(actions.rename, row, event.value)

    def action_stop(self) -> None:
        row = self._selected_row()
        if row is None or row.live is None:
            self._status("Session is not running")
            return
        self._pending_stop = row
        self._status(f"Stop '{row.title}'? Press y to confirm, any other key to cancel.")
        self.set_timer(STATUS_MSG_S, lambda: self._expire_stop(row))

    def _expire_stop(self, row: Row) -> None:
        if self._pending_stop is row:
            self._pending_stop = None

    def action_confirm_stop(self) -> None:
        row, self._pending_stop = self._pending_stop, None
        if row is not None:
            self._run_action(actions.stop, row)

    def on_key(self, event) -> None:
        if self._pending_stop is not None and event.key != "y":
            self._pending_stop = None
            self._status("Stop cancelled")

    def action_toggle_all(self) -> None:
        self._show_all = not self._show_all
        self._reload()

    def action_cancel(self) -> None:
        for box_id in ("#search", "#rename"):
            self.query_one(box_id).display = False
        self.query_one("#search", Input).value = ""
        self._filter = ""
        self.query_one("#sessions").focus()
        self._show_rows(self._rows)
    # endregion
