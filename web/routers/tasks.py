from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from web.cache import JobCache
from web.engine import cancel_slurm_jobs, remove_remote_dir
from web.models import ArtifactEntry, CreateTaskRequest, LogData, ProgressData, TaskInfo
from web.services.artifacts import list_local_artifacts, read_local_logs, read_local_progress
from web.services.config import RESULTS_DIR, parse_wes_files
from web.services.settings import record_form_history

router = APIRouter()


@router.get("/tasks", response_model=list[TaskInfo])
def list_tasks() -> list[TaskInfo]:
    return parse_wes_files()


@router.get("/tasks/{name}", response_model=TaskInfo)
def get_task(name: str) -> TaskInfo:
    for task in parse_wes_files():
        if task.name == name:
            return task
    raise HTTPException(status_code=404, detail=f"Task '{name}' not found in .wes configs")


@router.post("/tasks")
def create_task(req: CreateTaskRequest) -> dict:
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Task name is required")

    task_data: dict[str, str] = {}
    for field, val in [
        ("git_url", req.git_url),
        ("branch", req.branch),
        ("ssh", req.ssh),
        ("job", req.job),
        ("partition", req.partition),
        ("cpus", req.cpus),
        ("gpus", req.gpus),
        ("memory", req.memory),
        ("time", req.time),
        ("nodelist", req.nodelist),
    ]:
        if val.strip():
            task_data[field] = val.strip()

    config = {"sequence": [{name: task_data}]}
    wes_path = Path(name + ".wes")

    try:
        wes_path.write_text(yaml.dump(config, default_flow_style=False), encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}") from e

    record_form_history(task_data)

    return {"status": "ok", "task": name, "message": f"Saved '{name}.wes'"}


@router.put("/tasks/{name}")
def update_task(name: str, req: CreateTaskRequest) -> dict:
    wes_path = Path(name + ".wes")
    if not wes_path.exists():
        raise HTTPException(status_code=404, detail=f"Config '{name}.wes' not found")
    return create_task(req)


@router.delete("/tasks/{name}")
def delete_task(name: str) -> dict:
    messages: list[str] = []
    wes_path = Path(name + ".wes")
    if wes_path.exists():
        wes_path.unlink()
        messages.append(f"deleted {wes_path}")

    cache = JobCache()
    for run_id, data in list((cache.get_all() or {}).items()):
        if not isinstance(data, dict):
            continue
        matches = data.get("task_name") == name or data.get("run_id") == name or run_id == name
        if not matches:
            continue
        job_ids = data.get("jobs_ids", [])
        ssh = data.get("ssh", "")
        if job_ids and ssh:
            messages.extend(cancel_slurm_jobs(ssh, job_ids))
        run_id_val = data.get("run_id", "")
        if run_id_val and ssh:
            if remove_remote_dir(ssh, f"runs/{run_id_val}"):
                messages.append(f"removed runs/{run_id_val}")
        cache.remove(run_id)
        messages.append(f"removed job {run_id} from cache")

    local_results = RESULTS_DIR / name
    if local_results.exists():
        shutil.rmtree(local_results, ignore_errors=True)
        messages.append("removed local results")

    msg = "; ".join(messages) if messages else f"task '{name}' not found"
    return {"status": "ok", "message": msg}


@router.get("/tasks/{name}/logs", response_model=LogData)
def get_task_logs(name: str) -> LogData:
    return read_local_logs(name)


@router.get("/tasks/{name}/artifacts", response_model=list[ArtifactEntry])
def list_artifacts(name: str) -> list[ArtifactEntry]:
    return list_local_artifacts(name)


@router.get("/tasks/{name}/artifacts/{path:path}")
def serve_artifact(name: str, path: str) -> FileResponse:
    file_path = RESULTS_DIR / name / path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(str(file_path))


@router.get("/tasks/{name}/progress")
def get_progress(name: str) -> ProgressData:
    return read_local_progress(name)
