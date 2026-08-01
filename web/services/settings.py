from __future__ import annotations

from pathlib import Path

import yaml

SETTINGS_FILE = ".wes-settings.yml"
MAX_HISTORY = 20


def load_settings() -> dict:
    path = Path(SETTINGS_FILE)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_settings(data: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False)


def record_form_history(entry: dict) -> dict:
    data = load_settings()
    history: dict[str, list[str]] = data.get("form_history", {})
    for key in ("git_url", "ssh", "branch", "job"):
        val = entry.get(key, "").strip()
        if not val:
            continue
        lst = history.setdefault(key, [])
        if val in lst:
            lst.remove(val)
        lst.insert(0, val)
        history[key] = lst[:MAX_HISTORY]
    data["form_history"] = history
    save_settings(data)
    return {"status": "ok"}
