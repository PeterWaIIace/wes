from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from web.api import get_logs, get_progress, list_artifacts, list_tasks

router = APIRouter()

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    tasks = list_tasks()
    ssh_hosts = sorted({t.ssh for t in tasks if t.ssh})
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"tasks": tasks, "ssh_hosts": ssh_hosts, "active_page": "dashboard"},
    )


@router.get("/tasks/{name}", response_class=HTMLResponse)
def task_detail(request: Request, name: str) -> HTMLResponse:
    tasks = list_tasks()
    task = next((t for t in tasks if t.name == name), None)
    if not task:
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"tasks": tasks, "error": f"Task '{name}' not found", "active_page": "dashboard"},
        )
    logs = get_logs(name)
    artifacts = list_artifacts(name)
    progress = get_progress(name)
    return templates.TemplateResponse(
        request,
        "task.html",
        {
            "tasks": tasks,
            "task": task,
            "active_task": name,
            "active_page": "dashboard",
            "logs": logs,
            "artifacts": [a.model_dump() for a in artifacts],
            "progress": progress,
        },
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: str) -> HTMLResponse:
    tasks = list_tasks()
    return templates.TemplateResponse(
        request,
        "job.html",
        {
            "tasks": tasks,
            "job_id": job_id,
            "active_page": "dashboard",
        },
    )


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    tasks = list_tasks()
    return templates.TemplateResponse(
        request, "settings.html", {"tasks": tasks, "active_page": "settings"}
    )
