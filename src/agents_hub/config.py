from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    claude_dir: Path
    cache_dir: Path

    @property
    def projects_dir(self) -> Path:
        return self.claude_dir / "projects"

    @property
    def sessions_dir(self) -> Path:
        return self.claude_dir / "sessions"

    @property
    def index_file(self) -> Path:
        return self.cache_dir / "index.json"

    @property
    def titles_file(self) -> Path:
        return self.cache_dir / "titles.json"

    @property
    def lock_file(self) -> Path:
        return self.cache_dir / "hub.lock"


def default_paths() -> Paths:
    return Paths(Path.home() / ".claude", Path.home() / ".cache" / "agents-hub")
