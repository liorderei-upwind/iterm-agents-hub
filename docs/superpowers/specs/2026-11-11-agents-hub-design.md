# agents-hub — design

Date: 2026-11-11

## 1. Intent

A terminal app that runs in one iTerm2 tab. It shows all Claude Code sessions on this Mac, live and closed, in one list. It lets the user find a session by its topic, see its state, go to it, resume it, read its last messages, stop it, or rename it.

### Why

- The user closes a session when work on a topic stops.
- Later, the user must get information from that work or continue it.
- The user remembers each session by its **topic**. Each session is a different topic. Today there is no easy way to find "the session about X" and resume it.
- The user runs many agents at the same time in different iTerm tabs. There is no single place that shows which agent runs, which agent waits for the user, and which tab holds which session.

### Success

- The user types `agents`, types part of a topic, presses Enter, and is in that session (its live tab, or a new tab with the resumed session).
- At a glance, the user sees which live agents wait for them.

## 2. Goals

1. One list of all sessions on the machine (all project folders under `~/.claude/projects/`).
2. Live sessions at the top. Each live row shows:
   - state: **running**, **waiting for user**, **idle**
   - title
   - iTerm tab (window/tab number, or a short label)
   - model
   - effort
   - tokens (context size of the last turn, for example `188k`)
3. Closed sessions below. Each closed row shows: last-activity date, title, folder.
4. `/` filters the list by title (case-insensitive substring is sufficient).
5. Actions on the selected row:
   - **Go to tab** (live): bring the iTerm window and tab to the front and select the pane.
   - **Resume** (closed): open a new iTerm tab, `cd` to the session folder, run `claude --resume <sessionId>`.
   - **Preview** (both): show the last 10 user and assistant text messages. Do not show tool calls, tool output, or thinking.
   - **Stop** (live): send SIGTERM to the Claude process. The tab stays open. The row moves to "closed".
   - **Rename** (both): set a new title. The title must also show in Claude Code's own `claude --resume` picker.
6. Live data refreshes every 1–2 seconds.
7. Starts fast (target: under 1 second to the first screen with a warm index).

## 3. Non-goals (for now)

- Full-text search in conversation content. Title search only. (Possible later.)
- A side panel / iTerm2 toolbelt view. (Possible later, from the same data layer.)
- Sending prompts to sessions from the tool.
- Sessions on other machines or in the cloud.
- Subagent transcripts (`*/subagents/*`) as separate rows.

## 4. Anti-goals

- Do not change or remove the user's existing hooks, status line, or iTerm status bar setup (`iTerm2-claude-status`, `~/.config/iterm2/cc-status`, `ccnotifier-hook.sh`, `statusline.sh`).
- Do not corrupt session files. Writes to session files are allowed only for rename, and only as Claude Code itself writes them (append one line).
- Do not open a second copy of a session that is already live. If the user selects "resume" on a live session, go to its tab.
- Do not make the app slow by reading all 1.7 GB of transcripts at each start.

## 5. Constraints and facts found on this machine

- macOS, iTerm2, zsh. Python 3.15 at `/opt/homebrew/bin/python3`. Claude Code 2.1.319.
- 177 top-level session files in 22 project folders, 1.7 GB total. Files can be large (thousands of lines).
- **Live sessions:** `~/.claude/sessions/<pid>.json`. Example:
  ```json
  {"pid":52623,"sessionId":"da9d25c5-…","cwd":"/Users/me/git/work",
   "name":"work-b3","status":"busy","updatedAt":1794394750975, "kind":"interactive", ...}
  ```
  Observed `status` values: `busy`, `idle`. Files of dead processes can stay in the folder, so check that the pid is alive (and that `procStart` matches, to avoid pid reuse).
- **Transcripts:** `~/.claude/projects/<folder-slug>/<sessionId>.jsonl`, one JSON object per line. Useful entry types:
  - `ai-title` → `{"aiTitle": "CVE hotfix branches"}` (written many times; the last one wins)
  - `custom-title` → written by `/rename` (none exist on this machine yet; the builder must confirm the exact shape by running `/rename` once in a test session)
  - `assistant` → `message.model`, `message.usage` (input + cache-read + cache-creation tokens = context size)
  - `effort` appears as `"effort":"high"|"medium"` inside entries
  - `user` / `assistant` → message text for preview
  - `cwd` on message entries → the folder to resume in
- **Tab link:** pid → tty with `ps -o tty= -p <pid>`. iTerm2 AppleScript returns the tty of every session (`tell application "iTerm2" to get tty of sessions of tabs of windows`). Tested: works. iTerm2's Python API server is also enabled, but the `iterm2` Python module is not installed.

## 6. Decisions made with the user

| Decision | Choice |
|---|---|
| Form | Full-screen terminal app in its own iTerm tab (option A). Keyboard driven. |
| Search | Title only, for now. |
| Actions | Go to tab, resume, preview last messages, stop, rename. |
| Tokens | Context size of the last turn. |
| Preview | Last 10 user/assistant text messages, no tool output. |
| Stop | SIGTERM to the Claude process; tab stays open. |
| Rename | Visible also in Claude Code's own resume picker. |
| Command name | `agents` |
| Location | `iterm-agents-hub` (local folder) |
| Language / tools | Left to Claude. See §7. |

## 7. Calls made by Claude (the user gave these to Claude)

- **Python + Textual** for the terminal UI.
- **AppleScript via `osascript`** for iTerm: find tab by tty, focus tab, open new tab and run a command. No iTerm Python API dependency.
- **Index cache** at `~/.cache/agents-hub/index.json`: per session file store `mtime`, `size`, title, folder, last activity, model, effort, last context tokens, byte offset read so far. On start, re-read only files whose `mtime`/`size` changed, and read only the new bytes (append-only files).
- **Rename** appends a `custom-title` line in the same shape that `/rename` writes. Title shown = last `custom-title`, else last `ai-title`, else first user prompt (cut to 60 chars), else session id.
- **Rename of a live session:** appending to a file that a live process also appends to can interleave lines. The builder must check this is safe (a single short `write()` with `O_APPEND` is atomic for small writes on macOS local disk). If it is not safe, rename of live sessions shows a message that tells the user to use `/rename` in that tab.
- Install with a small `install.sh` that makes a venv and links `agents` into `~/bin` (already on PATH for `claude-status`).

## 8. Left to the builder

- **How to detect "waiting for user" vs "idle".** Required behavior:
  - **running**: Claude works on a turn (`status: busy`).
  - **waiting for user**: Claude stopped and needs the user — a permission prompt, a question (AskUserQuestion), or a finished turn the user has not answered yet.
  - **idle**: no activity and nothing asked for a while.
  The builder must find a reliable signal. Options: other values of `status` in `sessions/<pid>.json` (check when a permission prompt is open); the last transcript entry (a pending `tool_use` with no `tool_result` = permission prompt); time since the last assistant turn. A new, separate hook is acceptable only if it does not change existing hooks; prefer no hook.
- Exact key bindings and column widths.
- Sort order inside the closed list (recommended: last activity, newest first).
- How to show a live session whose tab cannot be found (for example, Claude runs in another terminal app).
- Tests: unit tests for the transcript parser and index update with small fixture files.

## 9. Calls made after the builder check (Claude's calls, not confirmed by the user)

- **Title source.** The `name` field in `sessions/<pid>.json` (for example `work-b3`) has `nameSource: "derived"`. It is a folder name plus a short id, not a topic. Do not use it as the title when `nameSource` is `derived`. If `nameSource` has any other value (the user named the session), use `name` first. Full order: `custom-title` → non-derived `name` → `ai-title` → first user prompt (60 chars) → session id. Search uses this title.
- **Rename fallback.** First confirm by test that an appended `custom-title` line shows in `claude --resume` and survives when the session is resumed and used again. If it does not, keep the new title in the hub's own store (`~/.cache/agents-hub/titles.json`), show it in the hub, and show a one-line note that Claude Code's picker does not show it. Never write to Claude Code files in any other way.
- **Which sessions show.** By default show only interactive sessions (live `kind: "interactive"`; for closed sessions, transcripts that contain at least one real user prompt typed by a person, not `claude -p` / SDK runs, when this can be detected). A key toggles "show all". Do not merge sessions: each transcript file is one row. If two rows have the same title, show the folder and date so the user can tell them apart.
- **Hub lifecycle.** The hub stays open after "go to tab" and "resume". Resume always opens a new tab. Only one hub runs: if `agents` runs while a hub is already open, it brings the existing hub tab to the front and exits.

## 10. Open questions

None known at time of writing.
