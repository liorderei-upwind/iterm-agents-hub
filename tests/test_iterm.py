import shlex

from agents_hub import iterm


def test_tab_map_parses(monkeypatch):
    out = "/dev/ttys000\t1\t1\n/dev/ttys002\t1\t3\n/dev/ttys005\t2\t1\n"
    monkeypatch.setattr(iterm, "_osascript", lambda s: out)
    assert iterm.tab_map() == {"ttys000": "w1:t1", "ttys002": "w1:t3", "ttys005": "w2:t1"}


def test_tab_map_empty(monkeypatch):
    monkeypatch.setattr(iterm, "_osascript", lambda s: "")
    assert iterm.tab_map() == {}


def test_focus_not_found_returns_false(monkeypatch):
    monkeypatch.setattr(iterm, "_osascript", lambda s: "notfound")
    assert iterm.focus("ttys009") is False


def test_focus_found(monkeypatch):
    scripts = []
    monkeypatch.setattr(iterm, "_osascript", lambda s: scripts.append(s) or "ok")
    assert iterm.focus("ttys002") is True
    assert '"/dev/ttys002"' in scripts[0]


def test_new_tab_quotes_cwd(monkeypatch):
    scripts = []
    monkeypatch.setattr(iterm, "_osascript", lambda s: scripts.append(s) or "")
    cwd = "/Users/me/my dir/it's"
    iterm.new_tab(cwd, "claude --resume abc")
    expected = f"cd {shlex.quote(cwd)} && claude --resume abc"
    assert iterm._as_string(expected) in scripts[0]


def test_as_string_escapes():
    assert iterm._as_string('a"b\\c') == '"a\\"b\\\\c"'


def test_tab_map_does_not_launch_iterm(monkeypatch):
    scripts = []
    monkeypatch.setattr(iterm, "_osascript", lambda s: scripts.append(s) or "")
    iterm.tab_map()
    assert 'if application "iTerm2" is not running then return ""' in scripts[0]
