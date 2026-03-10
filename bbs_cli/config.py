from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_STORE_ROOT = Path.home() / ".config" / "bbs-cli"
LEGACY_CONFIG_FILENAME = "config.json"
STATE_FILENAME = "state.json"
USERS_DIRNAME = "users"
USER_CONFIG_FILENAME = "config.json"
USER_HISTORY_FILENAME = "history.json"


@dataclass
class CliConfig:
    token: str | None = None
    base_url: str | None = None


@dataclass
class CliState:
    last_username: str | None = None


@dataclass
class UserHistory:
    post_last_visited: dict[str, str]


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.root = self._resolve_root(path)
        self.state_path = self.root / STATE_FILENAME
        # Old single-file location under the same root.
        self.legacy_config_path = self.root / LEGACY_CONFIG_FILENAME

    @property
    def path(self) -> Path:
        """Backward-compatible alias used by CLI output."""
        return self.state_path

    def _resolve_root(self, path: Path | None) -> Path:
        if path is None:
            return DEFAULT_STORE_ROOT
        if path.suffix.lower() == ".json":
            # Backward compatibility for old --config-path file values.
            return path.parent
        return path

    def user_dir(self, username: str) -> Path:
        return self.root / USERS_DIRNAME / username

    def user_config_path(self, username: str) -> Path:
        return self.user_dir(username) / USER_CONFIG_FILENAME

    def user_history_path(self, username: str) -> Path:
        return self.user_dir(username) / USER_HISTORY_FILENAME

    def _load_config_from_path(self, path: Path) -> CliConfig:
        if not path.exists():
            return CliConfig()
        data = json.loads(path.read_text(encoding="utf-8"))
        return CliConfig(
            token=data.get("token"),
            base_url=data.get("base_url"),
        )

    def _save_config_to_path(self, path: Path, config: CliConfig) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(config), ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def load_state(self) -> CliState:
        if not self.state_path.exists():
            return CliState()
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        last_username = data.get("last_username")
        return CliState(last_username=last_username if isinstance(last_username, str) else None)

    def save_state(self, state: CliState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(asdict(state), ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def set_last_username(self, username: str) -> CliState:
        state = self.load_state()
        state.last_username = username
        self.save_state(state)
        return state

    def load_user(self, username: str) -> CliConfig:
        return self._load_config_from_path(self.user_config_path(username))

    def save_user(self, username: str, config: CliConfig) -> None:
        self._save_config_to_path(self.user_config_path(username), config)

    def clear_user_token(self, username: str) -> CliConfig:
        cfg = self.load_user(username)
        cfg.token = None
        self.save_user(username, cfg)
        return cfg

    def load_legacy(self) -> CliConfig:
        return self._load_config_from_path(self.legacy_config_path)

    def has_legacy_config(self) -> bool:
        return self.legacy_config_path.exists()

    def migrate_legacy_to_user(self, username: str) -> CliConfig | None:
        if not self.has_legacy_config():
            return None
        target = self.user_config_path(username)
        if target.exists():
            return self._load_config_from_path(target)
        legacy = self.load_legacy()
        self.save_user(username, legacy)
        return legacy

    def load_user_history(self, username: str) -> UserHistory:
        path = self.user_history_path(username)
        if not path.exists():
            return UserHistory(post_last_visited={})
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_post_last_visited = data.get("post_last_visited")
        if not isinstance(raw_post_last_visited, dict):
            return UserHistory(post_last_visited={})
        parsed = {
            str(post_id): str(visited_at)
            for post_id, visited_at in raw_post_last_visited.items()
            if isinstance(post_id, str) and isinstance(visited_at, str)
        }
        return UserHistory(post_last_visited=parsed)

    def save_user_history(self, username: str, history: UserHistory) -> None:
        path = self.user_history_path(username)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(history), ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def set_post_last_visited(self, username: str, post_id: int, visited_at: str) -> UserHistory:
        history = self.load_user_history(username)
        history.post_last_visited[str(post_id)] = visited_at
        self.save_user_history(username, history)
        return history

