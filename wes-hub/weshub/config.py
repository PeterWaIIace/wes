from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

WES_HUB_DIR = Path(__file__).resolve().parent


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8420
    data_dir: Path = field(default_factory=lambda: Path("./data").resolve())
    poll_interval: float = 15.0
    scheduler_interval: float = 30.0
    discover_interval: float = 60.0
    ssh_timeout: float = 45.0
    max_status_workers: int = 8

    @property
    def pipelines_dir(self) -> Path:
        return self.data_dir / "pipelines"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.pipelines_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
