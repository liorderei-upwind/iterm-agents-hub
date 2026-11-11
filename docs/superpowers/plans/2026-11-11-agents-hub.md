# agents-hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A full-screen terminal app (`agents`) in an iTerm2 tab that lists all Claude Code sessions on this Mac, shows live state per session, and lets the user go to, resume, preview, stop and rename sessions.

**Architecture:** A pure data layer (transcript parser → incremental index cache → live-session reader → state classifier) feeds a Textual UI. iTerm2 is driven only through `osascript` (AppleScript). The data layer has no Textual or iTerm imports, so it is unit-tested with fixture files.

**Tech Stack:** Python 3.12 (managed by `uv`), Textual, pytest. No other runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-11-11-agents-hub-design.md`

## Global Constraints

- Project root: `the repository root`. **No git commits or pushes** (user preference); there is no commit step in any task.
- Never modify existing hooks, status line, or iTerm status-bar setup.
- The only write to Claude Code files: append one `custom-title` line for rename (§7, §9 of spec).
- Do not open a second copy of a live session; "resume" on a live row = go to tab.
- Index cache: `~/.cache/agents-hub/index.json`. Hub-only titles: `~/.cache/agents-hub/titles.json`. Single-instance lock: `~/.cache/agents-hub/hub.lock`.
- Command name: `agents`, linked into `~/bin`.
- Live refresh every 1.5 s. First screen with warm index < 1 s.
- Title order: `custom-title` → non-derived `name` → `ai-title` (last one) → first user prompt (60 chars) → session id.
- Tokens = context size of last assistant turn = `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`, shown as `188k`.
- Preview = last 10 user/assistant **text** messages; no tool_use, tool_result, thinking.
- Skip `*/subagents/*` transcripts.
- All paths come from one config object so tests can point at a temp dir.

## Review Focus

1. A transcript line that is cut in half (live process mid-write) → parser stops at the last full line and keeps the offset there; the next refresh reads the rest. (Task 2 test.)
2. A stale `sessions/<pid>.json` whose pid is dead or reused by another process → the session is shown as closed, not live. (Task 4 test.)
3. A transcript file that shrinks or is replaced (smaller size than the cached offset) → full re-scan, no crash. (Task 3 test.)
4. A live session that runs outside iTerm (no tty match) → row shows tab `—`; "go to tab" shows a message, does not crash. (Task 5 + Task 7 test.)
5. Non-UTF-8 bytes or non-JSON lines in a transcript → line skipped, the rest parsed. (Task 2 test.)

---

## File Structure

```
pyproject.toml            # uv project, entry point agents = agents_hub.cli:main
install.sh                # uv sync + symlink ~/bin/agents
agents_hub/
  config.py               # Paths dataclass (claude_dir, cache_dir); default_paths()
  models.py               # SessionMeta, LiveInfo, Row, State enum
  transcript.py           # incremental parse of one .jsonl; last_messages()
  index.py                # Index: load/refresh/save cache over all project dirs
  live.py                 # read ~/.claude/sessions/*.json, pid checks, tty
  state.py                # classify(meta, live, now) -> State
  iterm.py                # osascript wrappers
  actions.py              # resume, stop, rename, go_to
  app.py                  # Textual app
  cli.py                  # main(): single-instance lock, run app
tests/
  fixtures/               # small .jsonl and sessions/*.json files
  test_transcript.py test_index.py test_live.py test_state.py test_actions.py test_iterm.py
```

---

### Task 1: Project setup and models

**Files:**
- Create: `pyproject.toml`, `install.sh`, `agents_hub/__init__.py`, `agents_hub/config.py`, `agents_hub/models.py`, `tests/test_models.py`

**Interfaces:**
- Produces:
  - `Paths(claude_dir: Path, cache_dir: Path)` with properties `projects_dir`, `sessions_dir`, `index_file`, `titles_file`, `lock_file`; `default_paths() -> Paths` (`~/.claude`, `~/.cache/agents-hub`).
  - `class State(Enum): RUNNING, WAITING, IDLE, CLOSED`
  - `@dataclass SessionMeta: session_id: str, path: Path, cwd: str | None, ai_title: str | None, custom_title: str | None, first_prompt: str | None, model: str | None, effort: str | None, context_tokens: int | None, last_activity: float | None (epoch s), last_entry_kind: str | None ("assistant_text" | "tool_use_pending" | "user" | None), has_human_prompt: bool, offset: int, size: int, mtime: float, pending_tool_ids: set[str]`
  - `@dataclass LiveInfo: pid: int, session_id: str, cwd: str, status: str, name: str | None, name_source: str | None, kind: str, updated_at: float, tty: str | None`
  - `@dataclass Row: meta: SessionMeta, live: LiveInfo | None, state: State, title: str, tab_label: str | None`
  - `def display_title(meta: SessionMeta, live: LiveInfo | None, hub_title: str | None) -> str` — order: hub_title (only if set by rename fallback) → custom_title → live.name if name_source != "derived" → ai_title → first_prompt[:60] → session_id[:8].
  - `def format_tokens(n: int | None) -> str` — `None`→`"—"`, `<1000`→`"999"`, else `f"{round(n/1000)}k"`.

- [ ] **Step 1:** `uv init --package --python 3.12`, add `textual` and dev dep `pytest`. `pyproject.toml` script `agents = "agents_hub.cli:main"`. `install.sh`: `uv sync` then `ln -sf "$PWD/.venv/bin/agents" ~/bin/agents`.
- [ ] **Step 2: Write failing tests** in `tests/test_models.py`:
  - `test_title_prefers_custom`: custom_title="A", ai_title="B" → `"A"`.
  - `test_title_skips_derived_name`: live.name="proj-b3", name_source="derived", ai_title="CVE hotfix" → `"CVE hotfix"`.
  - `test_title_uses_user_name`: name_source="user", name="my-topic", ai_title="X" → `"my-topic"`.
  - `test_title_falls_back_to_prompt`: only first_prompt of 80 chars → length 60.
  - `test_format_tokens`: `None→"—"`, `512→"512"`, `187_600→"188k"`.
- [ ] **Step 3:** Run `uv run pytest tests/test_models.py -v` → FAIL (import error).
- [ ] **Step 4:** Implement `config.py`, `models.py`.
- [ ] **Step 5:** Run again → PASS.

---

### Task 2: Transcript parser (incremental) and preview

**Files:**
- Create: `agents_hub/transcript.py`, `tests/test_transcript.py`, `tests/fixtures/basic.jsonl`, `tests/fixtures/partial.jsonl`

**Interfaces:**
- Consumes: `SessionMeta` (Task 1).
- Produces:
  - `def scan(path: Path, prev: SessionMeta | None) -> SessionMeta` — if `prev` and file size ≥ `prev.offset`, seek to `prev.offset` and fold new lines into a copy of `prev`; else full scan. Reads in binary; splits on `b"\n"`; the last chunk without a trailing newline is not consumed (offset stays before it).
  - `def last_messages(path: Path, n: int = 10) -> list[tuple[str, str]]` — `(role, text)` pairs, oldest first. Reads the file from the end in blocks (64 KB) until n text messages are found or BOF.

Field rules (per JSON line, skip lines that fail `json.loads` or decode with `errors="replace"`):
- `type == "ai-title"` → `ai_title = aiTitle`. `type == "custom-title"` → `custom_title = <title field>` (shape confirmed in Task 6; accept keys `customTitle` or `title`).
- `type == "user"` and `message.content` is a str, or a list with a `text` block, and `isMeta` is not true and text does not start with `<` (system/command wrappers) → if `first_prompt` is None set it; `has_human_prompt = True`; `last_entry_kind = "user"`.
- `type == "user"` with `tool_result` blocks → remove each `tool_use_id` from `pending_tool_ids`.
- `type == "assistant"` → `model = message.model`; `context_tokens` from `message.usage` (sum of three fields); add each `tool_use` block id to `pending_tool_ids`; `last_entry_kind = "tool_use_pending"` if `pending_tool_ids` else `"assistant_text"`.
- Any line with `"effort"` key at top level or in `message` → `effort`. (Builder: confirm the location with `grep -m3 '"effort"'` on a real file and record it in a comment-free test fixture.)
- Any line with `cwd` → `cwd`. Any line with `timestamp` → `last_activity` (ISO → epoch).
- Skip `isSidechain: true` lines.

- [ ] **Step 1: Build fixtures** from a real transcript shape (copy and cut ~15 lines from `~/.claude/projects/<folder>/*.jsonl`, replace text with short dummy strings). `partial.jsonl` ends with half a JSON line and one line of invalid bytes `\xff\xfe`.
- [ ] **Step 2: Write failing tests:**
  - `test_scan_basic`: ai_title, model `"claude-opus-5-5"`, context_tokens equals the sum from the fixture, first_prompt, effort, cwd, has_human_prompt True.
  - `test_scan_last_ai_title_wins`: two ai-title lines → second.
  - `test_scan_partial_line_not_consumed`: offset == byte index after last `\n`; append the rest of the line; second `scan(path, prev)` picks up its data.
  - `test_scan_skips_bad_lines`: invalid bytes line and non-JSON line do not raise; later lines are parsed.
  - `test_pending_tool_use`: assistant with tool_use, no result → `last_entry_kind == "tool_use_pending"`; after a tool_result line → not pending.
  - `test_shrunk_file_full_rescan`: prev.offset > current size → result equals a fresh scan.
  - `test_last_messages`: returns ≤10 pairs, only text, no tool_result/thinking, order oldest→newest.
- [ ] **Step 3:** `uv run pytest tests/test_transcript.py -v` → FAIL.
- [ ] **Step 4:** Implement.
- [ ] **Step 5:** Run → PASS. Also run `uv run python -c "from agents_hub.transcript import scan; ..."` over all real transcripts and print counts of None titles/models; expect no exceptions.

---

### Task 3: Index cache

**Files:**
- Create: `agents_hub/index.py`, `tests/test_index.py`

**Interfaces:**
- Consumes: `scan` (Task 2), `Paths` (Task 1).
- Produces:
  - `class Index: __init__(self, paths: Paths)`; `load() -> None`; `refresh() -> list[SessionMeta]` (stat every `projects/*/*.jsonl`, skip `subagents` dirs, re-scan only files whose `(size, mtime)` changed, drop entries whose file is gone); `save() -> None` (write to temp file + `os.replace`); `get(session_id) -> SessionMeta | None`.
  - JSON format: `{"version": 1, "sessions": {path_str: <SessionMeta as dict, sets as lists>}}`. Unknown/older version → ignore cache.

- [ ] **Step 1: Write failing tests** (tmp_path with a fake `projects/` tree):
  - `test_refresh_finds_sessions` (2 project dirs, 3 files, one under `subagents/` → 2 results… plus 1 = 3 top-level, subagent excluded).
  - `test_refresh_rescans_only_changed` (monkeypatch `scan` with a counter; second refresh with no changes → 0 calls; touch one file → 1 call).
  - `test_save_load_roundtrip`.
  - `test_corrupt_cache_ignored` (write `"{"` to index file → load does not raise, refresh does full scan).
  - `test_deleted_file_dropped`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5: Timing check:** `uv run python -c` script: cold refresh over real `~/.claude`, then warm refresh; print both times. Expected: warm < 0.3 s. If cold > 20 s, note it in the final report (no change needed).

---

### Task 4: Live sessions and state classification

**Files:**
- Create: `agents_hub/live.py`, `agents_hub/state.py`, `tests/test_live.py`, `tests/test_state.py`, `tests/fixtures/sessions/*.json`

**Interfaces:**
- Consumes: `Paths`, `LiveInfo`, `SessionMeta`, `State`.
- Produces:
  - `def read_live(paths: Paths, pid_alive=_pid_alive, proc_start=_proc_start, tty_of=_tty_of) -> dict[str, LiveInfo]` keyed by session_id. A file counts only if `pid_alive(pid)` and `proc_start(pid)` equals the file's `procStart` (compare via `ps -o lstart= -p <pid>`, whitespace-normalized). One `ps -o pid=,tty=,lstart= -p <pids>` call for all pids, not one per pid.
  - `def classify(meta: SessionMeta, live: LiveInfo | None, now: float) -> State`
  - `WAIT_WINDOW_S = 30 * 60`

Classification (Claude's call; refine in Step 1):
- `live is None` → CLOSED.
- `meta.last_entry_kind == "tool_use_pending"` and `now - live.updated_at > 3` and live.status != "busy" → WAITING (permission prompt / question).
- `live.status == "busy"` → RUNNING.
- Any other status that Step 1 shows means "waiting for input/permission" → WAITING.
- `now - (meta.last_activity or live.updated_at) < WAIT_WINDOW_S` → WAITING (finished turn, user has not answered).
- else → IDLE.

- [ ] **Step 1: Investigate (no code):** In a spare iTerm tab, start `claude`, ask it to run `ls` with permission mode "default", and while the permission prompt is open run `cat ~/.claude/sessions/<pid>.json`. Record the `status` value. Do the same while an AskUserQuestion is open. Put the found values in `state.py` as a constant set `WAITING_STATUSES` and adjust the rule list above. Report the values to the user.
- [ ] **Step 2: Write failing tests:**
  - `test_dead_pid_ignored`, `test_reused_pid_ignored` (proc_start mismatch), `test_live_read` (fields mapped, tty set).
  - `test_classify_closed`, `test_classify_running`, `test_classify_waiting_pending_tool`, `test_classify_waiting_recent_turn` (last_activity = now-60), `test_classify_idle_old` (now-3600), plus one test per value in `WAITING_STATUSES`.
- [ ] **Step 3:** Run → FAIL. **Step 4:** Implement. **Step 5:** Run → PASS.

---

### Task 5: iTerm2 bridge

**Files:**
- Create: `agents_hub/iterm.py`, `tests/test_iterm.py`

**Interfaces:**
- Produces (all call a single `_osascript(script: str) -> str` that runs `osascript -e`, 5 s timeout, raises `ItermError` on non-zero exit):
  - `def tab_map() -> dict[str, str]` — tty (`"ttys002"`, no `/dev/`) → label `"w{win}:t{tab}"` (1-based). One AppleScript call that returns lines `tty<TAB>win<TAB>tab`.
  - `def focus(tty: str) -> bool` — select the window, tab and session with that tty; `activate`. Returns False if not found.
  - `def new_tab(cwd: str, command: str) -> None` — in the current window, create tab with default profile, `write text "cd <shell-quoted cwd> && <command>"`.
  - `def own_tty() -> str | None` — tty of the hub's own process (`os.ttyname(0)` stripped).
- `tests/test_iterm.py` monkeypatches `_osascript`:
  - `test_tab_map_parses` (canned output with 3 lines → dict).
  - `test_focus_not_found_returns_false` (script returns `"notfound"`).
  - `test_new_tab_quotes_cwd` (cwd with a space and `'` → the generated script contains `shlex.quote` result).
- [ ] **Step 1:** tests → FAIL. **Step 2:** Implement. **Step 3:** tests → PASS.
- [ ] **Step 4: Manual check:** `uv run python -c "from agents_hub import iterm; print(iterm.tab_map())"` shows all open tabs. The first run can show a macOS Automation permission dialog; tell the user to allow it.

---

### Task 6: Actions (resume, stop, rename, go to)

**Files:**
- Create: `agents_hub/actions.py`, `tests/test_actions.py`

**Interfaces:**
- Consumes: `iterm.focus`, `iterm.new_tab`, `Row`, `Paths`.
- Produces (each returns a short user-facing message string):
  - `def go_to(row: Row) -> str` — live row with tty → `focus`; no tty → `"Session runs outside iTerm (pid N)"`.
  - `def resume(row: Row) -> str` — live → `go_to(row)`; closed → `new_tab(meta.cwd or ~, f"claude --resume {session_id}")`.
  - `def stop(row: Row, kill=os.kill) -> str` — live only; `kill(pid, SIGTERM)`. Never for the hub's own tty or the session whose pid is the parent of the hub.
  - `def rename(row: Row, title: str, paths: Paths) -> str` — strip; reject empty or > 200 chars. Append one line with one `os.write` on an `O_APPEND` fd: the exact JSON shape from Step 1. If Step 1 shows that an appended line is not used by `claude --resume`, write to `titles.json` instead (spec §9) and return the note `"Saved in hub only; Claude's picker does not show it."`.
- [ ] **Step 1: Investigate (no code):** in a throwaway session run `/rename test-hub-title`, then `grep -h custom-title` its transcript. Record the exact line shape. Then append a line with that shape (new title) to a **closed** test session and check `claude --resume` shows it, and that resuming + one prompt keeps it. Report the result to the user; pick the rename path accordingly.
- [ ] **Step 2: Write failing tests:**
  - `test_resume_live_goes_to_tab` (no new_tab call), `test_resume_closed_opens_tab` (command string exact), `test_go_to_no_tty_message`.
  - `test_stop_sends_sigterm`, `test_stop_closed_rejected`.
  - `test_rename_appends_one_line` (file had N lines → N+1, last line parses, ends with `\n`), `test_rename_rejects_empty`.
  - `test_rename_then_scan_shows_title` (uses `scan` from Task 2).
- [ ] **Step 3:** → FAIL. **Step 4:** Implement. **Step 5:** → PASS.

---

### Task 7: Textual app and CLI

**Files:**
- Create: `agents_hub/app.py`, `agents_hub/cli.py`, `tests/test_app.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `class HubApp(App)`; `def build_rows(index: Index, live: dict[str, LiveInfo], tabs: dict[str, str], hub_titles: dict[str, str], now: float, show_all: bool) -> list[Row]`; `def main() -> None`.

Layout (from the approved mockup, option A):
- Top: search input (hidden until `/`), counter `"N live · M closed"`.
- `DataTable`. Section LIVE: `state icon+word | title | tab | model (short: "opus-5.5") | effort | tokens`. Section CLOSED: `date (YYYY-MM-DD) | title | folder (~-relative)`. Live sorted RUNNING, WAITING, IDLE then last activity desc; closed by last activity desc.
- State look: running `●` green, waiting `◐` yellow, idle `○` dim.
- Preview: a right-side panel (40 % width) toggled by `p`, shows `last_messages` for the selected row.
- Footer keys: `↑↓` move, `enter` go/resume, `p` preview, `s` stop (confirm with `y`), `r` rename (inline input, `enter` saves, `esc` cancels), `/` search, `a` show all, `q` quit.
- Status line at the bottom shows the message returned by actions for 4 s.
- Refresh: `set_interval(1.5, ...)` re-reads live + tab map + `index.refresh()` in a worker thread; table updates keep the selected session id.
- `build_rows` filter: if not `show_all`, keep rows where `live` is not None or `meta.has_human_prompt`. Search: case-insensitive substring on `Row.title`.

CLI `main()`:
- Take `fcntl.flock` on `lock_file` (non-blocking). If held: read the tty stored in the lock file, `iterm.focus(tty)`, exit 0. Else write own tty into it and run `HubApp`.
- Save the index on exit.

- [ ] **Step 1: Write failing tests** (`build_rows` only; no UI driving except one Pilot smoke test):
  - `test_build_rows_live_first_sorted`, `test_build_rows_hides_non_human_unless_show_all`, `test_build_rows_tab_label_from_tty`, `test_build_rows_no_tab_dash`.
  - `test_app_smoke`: `async with HubApp(paths=fixture_paths).run_test() as pilot:` press `/`, type a title fragment, assert the table has 1 row; press `p`, assert the preview panel is visible.
- [ ] **Step 2:** → FAIL. **Step 3:** Implement. **Step 4:** → PASS (`uv run pytest -v`, whole suite).
- [ ] **Step 5: Manual run with the user:** ask the user before installing. Then `./install.sh`, open a new iTerm tab, run `agents`. Check with the user: live sessions show correct tabs and states, `/` finds a known title, `enter` on a live row jumps to the tab, `enter` on a closed row opens a resumed session, `p` shows messages, `r` renames, and a second `agents` jumps to the first hub.
