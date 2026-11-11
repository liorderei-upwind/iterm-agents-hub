# agents-hub

A terminal app for **iTerm2** that shows all your **Claude Code** sessions in one place: the live ones and the closed ones.

- Find an old session by its topic and **resume** it.
- See which agents are **running**, which are **waiting for you**, and which are **idle**.
- See the **iTerm tab** of each live session and **go to** it with one key.
- **Preview** the last messages of a session without resuming it.
- **Stop** or **rename** a session.

```
5 live · 157 closed
State      Title                                   Tab    Model     Effort  Tokens  Last active       Folder
● running  iTerm2 session manager GUI              w1:t5  opus-5.5  medium  167k    2026-11-11 13:35  ~/git/work
◐ waiting  CVE hotfix branches                     w1:t3  opus-5.5  medium  183k    2026-11-11 13:06  ~/git/work
○ idle     Flink processes job cost optimization   w1:t1  opus-5.5  medium  213k    2026-11-10 12:30  ~/git/work/flink
           Prod processes job CPU spike                   opus-5.5                  2026-11-10 17:04  ~/git/work/flink
           Process job crash in prod                      opus-5.5                  2026-11-10 11:19  ~/git/work/flink
```

---

## Requirements

| Item | Version |
|---|---|
| macOS | any recent version |
| iTerm2 | 3.4 or later |
| Claude Code CLI | 2.1 or later (`claude --version`) |
| [uv](https://docs.astral.sh/uv/) | 0.4 or later (`brew install uv`) |

You do not need to install Python yourself. `uv` gets Python 3.12 for the project.

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/liorderei-upwind/iterm-agents-hub.git ~/git/iterm-agents-hub
   cd ~/git/iterm-agents-hub
   ```
2. Run the install script:
   ```bash
   ./install.sh
   ```
   The script creates a virtual environment in `.venv` and puts a link at `~/bin/agents`.
3. Make sure that `~/bin` is on your `PATH`. If it is not, add this line to `~/.zshrc` and open a new tab:
   ```bash
   export PATH="$HOME/bin:$PATH"
   ```
4. Open a new iTerm tab and type:
   ```bash
   agents
   ```
5. The first time, macOS asks if your terminal can control iTerm2. Click **Allow**. If you clicked **Don't Allow**, go to **System Settings → Privacy & Security → Automation** and turn on **iTerm2** for your terminal.

The first start reads all your session files and builds an index. This can take 5–10 seconds. Later starts take less than a second.

### Update

```bash
cd ~/git/iterm-agents-hub && git pull && ./install.sh
```

### Uninstall

```bash
rm ~/bin/agents
rm -rf ~/.cache/agents-hub
rm -rf ~/git/iterm-agents-hub
```

agents-hub does not change Claude Code's settings or hooks, so there is nothing else to remove.

---

## Usage

| Key | Action |
|---|---|
| `↑` `↓` | Move the selection |
| `Enter` | **Live** session: go to its iTerm tab. **Closed** session: open a new iTerm tab and run `claude --resume <id>` in the session's folder |
| `/` | Search the titles. `Enter` keeps the filter. `Esc` clears it |
| `p` | Show or hide the preview panel (the last 10 messages from you and from Claude) |
| `r` | Rename the selected session. `Enter` saves. `Esc` cancels |
| `s`, then `y` | Stop the selected live session (sends SIGTERM). The tab stays open. The request expires after 4 seconds |
| `a` | Show all sessions, also sessions that a script started (`claude -p`, SDK) |
| `q` | Quit |

Only one hub runs at a time. If you type `agents` when a hub is already open, iTerm goes to the tab of that hub.

### Columns

| Column | Meaning |
|---|---|
| **State** | `● running`: Claude is working. `◐ waiting`: Claude waits for you (a permission, a question, or a finished answer from the last 30 minutes). `○ idle`: nothing has happened for 30 minutes or more. Empty: the session is closed |
| **Title** | Your rename, else a name you gave the session, else Claude's automatic title, else your first prompt |
| **Tab** | `w<window>:t<tab>` in iTerm. `—` means that the session runs outside iTerm |
| **Model / Effort** | From the last answer of Claude |
| **Tokens** | The context size of the last answer (input + cache tokens) |
| **Last active** | The time of the last message |
| **Folder** | The folder where the session runs, and where resume starts it |

The list refreshes every 1.5 seconds.

---

## How it works

agents-hub only reads the files that Claude Code already writes. It does not need a hook, a daemon, or a change to your Claude settings.

```
~/.claude/projects/<folder>/<session-id>.jsonl   ──►  transcript parser ──► index cache (~/.cache/agents-hub/index.json)
~/.claude/sessions/<pid>.json  +  ps             ──►  live sessions (state, pid, tty)
osascript (AppleScript)                          ──►  iTerm tabs (tty → window/tab), go to tab, new tab
```

- **Sessions and titles.** Each `.jsonl` file is one session. The parser reads `ai-title`, `custom-title`, the model, the effort, the token usage and the folder. Transcripts only grow, so the index remembers the byte position it has read and reads only new lines on the next refresh. Large files are read in 8 MB parts. A file that was replaced (new inode) is read again from the start.
- **Live sessions.** Claude Code writes `~/.claude/sessions/<pid>.json` for each running session, with `status` = `busy`, `idle` or `waiting` (with a `waitingFor` reason). agents-hub uses `ps` to make sure that the process is still alive and is the same process (same start time). Thus a reused process ID does not show as live.
- **iTerm tabs.** The tty of the Claude process is compared with the tty of each iTerm session, through AppleScript. The hub does not start iTerm2 if iTerm2 is not running.
- **Rename** adds one line, `{"type":"custom-title","customTitle":"…"}`, to the end of the session file. Claude Code's `/rename` writes the same line, so the new title also shows in `claude --resume`. The write is a single append. If Claude is writing a line at that moment, the hub tells you to try again. It does not split the line.

### Files that agents-hub writes

| File | Content |
|---|---|
| `~/.cache/agents-hub/index.json` | The index cache. You can delete it at any time |
| `~/.cache/agents-hub/hub.lock` | The single-instance lock and the tty of the open hub |
| `~/.claude/projects/…/<id>.jsonl` | Only on **rename**: one appended `custom-title` line |

---

## Development

```bash
uv sync                 # install dependencies
uv run pytest -q        # run the tests
uv run agents           # run without installing
```

Project layout:

```
src/agents_hub/
  config.py      paths (~/.claude, ~/.cache/agents-hub)
  models.py      SessionMeta, LiveInfo, Row, State, title rules
  transcript.py  incremental .jsonl parser, last-messages preview
  index.py       index cache over all project folders
  live.py        live sessions from ~/.claude/sessions + ps
  state.py       running / waiting / idle rules
  iterm.py       AppleScript bridge to iTerm2
  actions.py     go to, resume, stop, rename
  app.py         Textual user interface
  cli.py         `agents` entry point and single-instance lock
tests/           pytest suite (fixtures in tests/fixtures)
docs/superpowers design document and implementation plan
```

## Known limits

- Search uses titles only. It does not search the text of the conversation.
- The Claude Code session file format is not a public API. A new Claude Code version can change it. If the hub shows no titles or no live sessions after an update, run `uv run pytest` and open an issue.
- Sessions on other machines or in the cloud are not shown.

## Troubleshooting

| Problem | Fix |
|---|---|
| `agents: command not found` | Add `~/bin` to your `PATH` (installation step 3) |
| The **Tab** column shows `—` for all sessions | Allow Automation for iTerm2 (installation step 5) |
| No live sessions show | Make sure that `ls ~/.claude/sessions/` shows `.json` files. You need Claude Code 2.1 or later |
| Wrong or old data | Quit the hub, run `rm ~/.cache/agents-hub/index.json`, and start it again |
| "agents hub is already running in another terminal" | The open hub runs outside iTerm. Close it there |
