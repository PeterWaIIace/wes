from __future__ import annotations

from fastapi import APIRouter

from web.models import SettingsData
from web.services.mock import mock_enabled
from web.services.settings import load_settings, record_form_history, save_settings

router = APIRouter()


@router.get("/settings", response_model=SettingsData)
def get_settings() -> SettingsData:
    data = load_settings()
    return SettingsData(
        ssh_hosts=data.get("ssh_hosts", []),
        form_history=data.get("form_history", {}),
        query_interval=data.get("query_interval", 10),
        mock=mock_enabled(),
    )


@router.put("/settings")
def update_settings(req: SettingsData) -> dict:
    save_settings(
        {
            "ssh_hosts": req.ssh_hosts,
            "form_history": req.form_history,
            "query_interval": req.query_interval,
        }
    )
    return {"status": "ok"}


@router.post("/settings/history")
def post_form_history(entry: dict) -> dict:
    return record_form_history(entry)
