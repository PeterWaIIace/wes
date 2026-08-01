from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from web.models import ArtifactEntry, LogData, ProgressData
from web.services.config import RESULTS_DIR

_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x1b]*\x1b\\")

KIND_BY_SUFFIX = {
    ".mp4": "video",
    ".zip": "model",
    ".csv": "csv",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
}


def _read_file(path: Path) -> str:
    if path.exists():
        return _ANSI.sub("", path.read_text(encoding="utf-8", errors="replace"))
    return ""


def classify(path: str | Path) -> str:
    return KIND_BY_SUFFIX.get(Path(path).suffix.lower(), "file")


def parse_remote_files(lines: list[str]) -> list[dict]:
    artifacts: list[dict] = []
    for line in lines:
        path = line.strip()
        if not path:
            continue
        artifacts.append({"name": Path(path).name, "kind": classify(path), "path": path})
    return artifacts


def list_local_artifacts(name: str) -> list[ArtifactEntry]:
    artifacts: list[ArtifactEntry] = []
    task_dir = RESULTS_DIR / name
    if not task_dir.exists():
        return artifacts
    for path in sorted(task_dir.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(task_dir))
            artifacts.append(
                ArtifactEntry(
                    name=path.name,
                    kind=classify(path),
                    path=rel,
                    size=path.stat().st_size,
                )
            )
    return artifacts


def read_local_logs(name: str) -> LogData:
    return read_logs(RESULTS_DIR / name)


def read_logs(directory: Path) -> LogData:
    return LogData(
        stdout=_read_file(directory / "job_output.txt"),
        stderr=_read_file(directory / "job_error.txt"),
        pre_run=_read_file(directory / "pre_run_output.txt"),
    )


def parse_csv(content: str) -> ProgressData:
    rows = list(csv.reader(io.StringIO(content)))
    if not rows:
        return ProgressData()
    return ProgressData(columns=rows[0], rows=rows[1:])


def read_local_progress(name: str) -> ProgressData:
    csv_files = list((RESULTS_DIR / name).rglob("*.csv"))
    if not csv_files:
        return ProgressData()
    content = csv_files[0].read_text(encoding="utf-8", errors="replace")
    return parse_csv(content)
