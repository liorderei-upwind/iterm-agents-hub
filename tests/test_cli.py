import fcntl
import os

import pytest

from agents_hub import cli
from agents_hub.config import Paths


def test_second_instance_iterm_error_no_traceback(tmp_path, monkeypatch, capsys):
    paths = Paths(tmp_path / "claude", tmp_path / "cache")
    paths.cache_dir.mkdir(parents=True)
    paths.lock_file.write_text("ttys009")
    holder = os.open(paths.lock_file, os.O_RDWR)
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    monkeypatch.setattr(cli, "default_paths", lambda: paths)

    def boom(tty):
        raise cli.iterm.ItermError("no iTerm")
    monkeypatch.setattr(cli.iterm, "focus", boom)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert "already running" in capsys.readouterr().err
    os.close(holder)
