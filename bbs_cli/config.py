from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "bbs-cli" / "config.json"


@dataclass
class CliConfig:
    token: str | None = None
    base_url: str | None = None


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_CONFIG_PATH

    def load(self) -> CliConfig:
        if not self.path.exists():
            return CliConfig()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return CliConfig(
            token=data.get("token"),
            base_url=data.get("base_url"),
        )

    def save(self, config: CliConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(config), ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def clear_token(self) -> CliConfig:
        cfg = self.load()
        cfg.token = None
        self.save(cfg)
        return cfg

