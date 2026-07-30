from __future__ import annotations

from pathlib import Path

import yaml

REQUIRED_FIELDS = {"git_url", "job", "ssh"}
VALID_FIELDS = {
    "git_url",
    "branch",
    "path",
    "ssh",
    "job",
    "run",
    "pre",
    "post",
    "artifacts",
    "cleanup",
    "partition",
    "cpus",
    "gpus",
    "memory",
    "time",
    "nodelist",
}


class ConfigError(Exception):
    """Raised when a .wes config file is invalid."""


def parse_wes_file(config_file: str | Path) -> list[dict]:
    path = Path(config_file)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    if path.suffix != ".wes":
        raise ConfigError(f"Config file must have .wes extension: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ConfigError("Config file must be a YAML mapping")

    sequence = data.get("sequence")
    if sequence is None:
        raise ConfigError("Config file must contain a 'sequence' key")

    tasks_data: list[dict] = []
    if isinstance(sequence, list):
        for item in sequence:
            if not isinstance(item, dict) or len(item) != 1:
                raise ConfigError(
                    f"Each sequence item must be a single-key mapping, got: {item!r}"
                )
            for name, task_data in item.items():
                if not isinstance(task_data, dict):
                    raise ConfigError(f"Task '{name}' config must be a mapping")
                task_data["name"] = name
                tasks_data.append(task_data)
    elif isinstance(sequence, dict):
        for name, task_data in sequence.items():
            if not isinstance(task_data, dict):
                raise ConfigError(f"Task '{name}' config must be a mapping")
            task_data["name"] = name
            tasks_data.append(task_data)
    else:
        raise ConfigError("'sequence' must be a list or mapping of tasks")

    return [_process_task(t) for t in tasks_data]


def _process_task(task_data: dict) -> dict:
    name = task_data.get("name", "Unnamed Task")
    _validate_task(name, task_data)
    return {
        "name": name,
        "git_url": task_data["git_url"],
        "branch": task_data.get("branch", ""),
        "path": task_data.get("path", ""),
        "ssh": task_data["ssh"],
        "job": task_data["job"],
        "run": task_data.get("run", []),
        "pre": task_data.get("pre", ""),
        "post": task_data.get("post", ""),
        "artifacts": task_data.get("artifacts", []),
        "cleanup": task_data.get("cleanup", False),
        "partition": str(task_data.get("partition", "")),
        "cpus": str(task_data.get("cpus", "")),
        "gpus": str(task_data.get("gpus", "")),
        "memory": str(task_data.get("memory", "")),
        "time": str(task_data.get("time", "")),
        "nodelist": str(task_data.get("nodelist", "")),
    }


def _validate_task(name: str, data: dict) -> None:
    unknown = set(data.keys()) - VALID_FIELDS - {"name"}
    if unknown:
        raise ConfigError(f"Task '{name}' has unknown fields: {', '.join(sorted(unknown))}")

    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise ConfigError(
            f"Task '{name}' is missing required fields: {', '.join(sorted(missing))}"
        )

    if not isinstance(data["git_url"], str) or not data["git_url"].strip():
        raise ConfigError(f"Task '{name}': 'git_url' must be a non-empty string")

    if not isinstance(data["ssh"], str) or not data["ssh"].strip():
        raise ConfigError(f"Task '{name}': 'ssh' must be a non-empty string")

    if not isinstance(data["job"], str) or not data["job"].strip():
        raise ConfigError(f"Task '{name}': 'job' must be a non-empty string")

    for field in ("run", "artifacts"):
        val = data.get(field)
        if val is not None and not isinstance(val, list):
            raise ConfigError(f"Task '{name}': '{field}' must be a list")


def task_to_wes_yaml(task: dict) -> str:
    name = task.get("name", "unnamed")
    fields: dict[str, str | list | bool] = {}
    for key in ("git_url", "branch", "ssh", "job", "run", "pre", "post", "artifacts", "cleanup"):
        val = task.get(key)
        if val is not None and val != "" and val != [] and val is not False:
            fields[key] = val
    for key in ("partition", "cpus", "gpus", "memory", "time", "nodelist"):
        val = task.get(key, "")
        if val:
            fields[key] = val
    config = {"sequence": [{name: fields}]}
    return yaml.dump(config, default_flow_style=False)
