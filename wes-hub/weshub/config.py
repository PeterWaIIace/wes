from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

WES_HUB_DIR = Path(__file__).resolve().parent


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8420
    data_dir: Path = field(default_factory=lambda: Path("./data").resolve())
    poll_interval: float = 15.0
    scheduler_interval: float = 30.0
    discover_interval: float = 60.0
    progress_interval: float = 100.0
    ssh_timeout: float = 45.0
    max_status_workers: int = 8
    catalog_repo: str = ""
    catalog_branch: str = "main"
    mock_mode: bool = False

    @classmethod
    def from_file(cls, path: str | Path) -> Settings:
        path = Path(path).resolve()
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as e:
            raise ValueError(f"could not load server config {path}: {e}") from e
        if not isinstance(data, dict):
            raise ValueError("server config must be a YAML mapping")
        server = data.get("server", {})
        catalog = data.get("catalog", {})
        if not isinstance(server, dict) or not isinstance(catalog, dict):
            raise ValueError("server and catalog config sections must be mappings")
        data_dir = Path(server.get("data_dir", "data"))
        if not data_dir.is_absolute():
            data_dir = path.parent / data_dir
        allowed = {
            "host",
            "port",
            "poll_interval",
            "scheduler_interval",
            "discover_interval",
            "progress_interval",
            "ssh_timeout",
            "max_status_workers",
        }
        values = {key: value for key, value in server.items() if key in allowed}
        values["data_dir"] = data_dir.resolve()
        values["catalog_repo"] = catalog.get("repo", "")
        values["catalog_branch"] = catalog.get("branch", "main")
        return cls(**values)

    @property
    def pipelines_dir(self) -> Path:
        return self.data_dir / "pipelines"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"

    @property
    def catalog_dir(self) -> Path:
        return self.data_dir / "catalog"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.pipelines_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
