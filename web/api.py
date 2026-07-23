from __future__ import annotations

import csv
import io
import logging
import re
import time
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from web.models import (
    ArtifactEntry,
    ClusterData,
    CreateTaskRequest,
    JobSummary,
    LaunchJobRequest,
    LogData,
    NodeInfo,
    ProgressData,
    RunRequest,
    SettingsData,
    TaskConfig,
    TaskInfo,
)
from wes.cache import JobCache
from wes.states import State

log = logging.getLogger("wes.web")

router = APIRouter(prefix="/api")

RESULTS_DIR = Path("results")
_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x1b]*\x1b\\")
_CONFIG_CACHE: tuple[float, list[TaskConfig]] | None = None


def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def _read_file(path: Path) -> str:
    if path.exists():
        return _strip_ansi(path.read_text(encoding="utf-8", errors="replace"))
    return ""


def _parse_wes_files() -> list[TaskInfo]:
    from wes.parser import WESParser

    wes_files = sorted(Path(".").glob("*.wes"))
    if not wes_files:
        return []

    cache = JobCache(persistent=True)
    try:
        cached = cache.get_all() or {}
    finally:
        cache.close()

    parser = WESParser()
    tasks: list[TaskInfo] = []
    for wes_file in wes_files:
        try:
            for task in parser.parse(str(wes_file)):
                state = ""
                active_run_id = ""
                for run_id, data in cached.items():
                    if isinstance(data, dict) and data.get("task_name") == task.name:
                        state = data.get("state", "")
                        active_run_id = run_id
                        break
                tasks.append(
                    TaskInfo(
                        name=task.name,
                        git_url=task.git_url,
                        branch=task.branch,
                        ssh=task.ssh_config,
                        job=task.job or "",
                        path=task.path,
                        run=task.run,
                        post=task.post,
                        artifacts=task.artifacts,
                        cleanup=task.cleanup_git,
                        partition=task.partition,
                        cpus=task.cpus,
                        gpus=task.gpus,
                        memory=task.memory,
                        time=task.time,
                        nodelist=task.nodelist,
                        status=state,
                        run_id=active_run_id,
                    )
                )
        except Exception as e:
            log.error("Failed to parse %s: %s", wes_file, e)
    return tasks


# ──────────────────────────────────────────────
#  Task CRUD (reads/writes .wes files)
# ──────────────────────────────────────────────


@router.get("/tasks", response_model=list[TaskInfo])
def list_tasks() -> list[TaskInfo]:
    """List all task recipes from .wes files."""
    return _parse_wes_files()


@router.get("/tasks/{name}", response_model=TaskInfo)
def get_task(name: str) -> TaskInfo:
    """Get a single task recipe by name."""
    for task in _parse_wes_files():
        if task.name == name:
            return task
    raise HTTPException(status_code=404, detail=f"Task '{name}' not found in .wes configs")


@router.post("/tasks")
def create_task(req: CreateTaskRequest) -> dict:
    """Create or update a task .wes file (no execution)."""
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
    global _CONFIG_CACHE
    _CONFIG_CACHE = None

    return {"status": "ok", "task": name, "message": f"Saved '{name}.wes'"}


@router.put("/tasks/{name}")
def update_task(name: str, req: CreateTaskRequest) -> dict:
    """Update an existing task .wes file."""
    wes_path = Path(name + ".wes")
    if not wes_path.exists():
        raise HTTPException(status_code=404, detail=f"Config '{name}.wes' not found")
    return create_task(req)


@router.delete("/tasks/{name}")
def delete_task(name: str) -> dict:
    """Remove a task .wes file and any associated cache/results."""
    import shutil

    messages: list[str] = []
    wes_path = Path(name + ".wes")
    if wes_path.exists():
        wes_path.unlink()
        messages.append(f"deleted {wes_path}")
        global _CONFIG_CACHE
        _CONFIG_CACHE = None

    cache = JobCache(persistent=True)
    try:
        for run_id, data in list((cache.get_all() or {}).items()):
            if not isinstance(data, dict):
                continue
            matches = (
                data.get("task_name") == name
                or data.get("run_id") == name
                or run_id == name
            )
            if not matches:
                continue
            task = JobCache.cached_task(run_id, data)
            if task.jobs_ids and task.ssh_config:
                for jid in task.jobs_ids:
                    try:
                        import subprocess

                        subprocess.run(
                            ["ssh", task.ssh_config, f"scancel {jid}"],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        messages.append(f"cancelled slurm job {jid}")
                    except Exception:
                        pass
            if task.run_id and task.ssh_config:
                try:
                    import subprocess

                    subprocess.run(
                        ["ssh", task.ssh_config, f"rm -rf runs/{task.run_id}"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    messages.append(f"removed runs/{task.run_id}")
                except Exception:
                    pass
            cache.remove(run_id)
            messages.append(f"removed job {run_id} from cache")
    finally:
        cache.close()

    local_results = RESULTS_DIR / name
    if local_results.exists():
        shutil.rmtree(local_results, ignore_errors=True)
        messages.append("removed local results")

    msg = "; ".join(messages) if messages else f"task '{name}' not found"
    return {"status": "ok", "message": msg}


# ──────────────────────────────────────────────
#  Job management (cache-backed executions)
# ──────────────────────────────────────────────


@router.get("/jobs", response_model=list[JobSummary])
def list_jobs() -> list[JobSummary]:
    """List all job executions from cache."""
    cache = JobCache(persistent=True)
    jobs: list[JobSummary] = []
    try:
        for job_id, data in (cache.get_all() or {}).items():
            jobs.append(
                JobSummary(
                    job_id=job_id,
                    task_name=data.get("task_name", job_id),
                    state=data.get("state", "UNKNOWN"),
                    run_id=data.get("run_id", ""),
                    jobs_ids=data.get("jobs_ids", []),
                    git_url=data.get("git_url", ""),
                    branch=data.get("branch", ""),
                    ssh=data.get("ssh", ""),
                    job=data.get("job", ""),
                    partition=data.get("partition", ""),
                    cpus=data.get("cpus", ""),
                    gpus=data.get("gpus", ""),
                    memory=data.get("memory", ""),
                    time=data.get("time", ""),
                    nodelist=data.get("nodelist", ""),
                )
            )
    finally:
        cache.close()
    return jobs


@router.get("/jobs/{job_id}", response_model=JobSummary)
def get_job(job_id: str) -> JobSummary:
    """Get a single job by ID."""
    cache = JobCache(persistent=True)
    try:
        data = (cache.get_all() or {}).get(job_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        return JobSummary(
            job_id=job_id,
            task_name=data.get("task_name", job_id),
            state=data.get("state", "UNKNOWN"),
            run_id=data.get("run_id", ""),
            jobs_ids=data.get("jobs_ids", []),
            git_url=data.get("git_url", ""),
            branch=data.get("branch", ""),
            ssh=data.get("ssh", ""),
            job=data.get("job", ""),
            partition=data.get("partition", ""),
            cpus=data.get("cpus", ""),
            gpus=data.get("gpus", ""),
            memory=data.get("memory", ""),
            time=data.get("time", ""),
            nodelist=data.get("nodelist", ""),
        )
    finally:
        cache.close()


@router.post("/jobs")
def launch_job(req: LaunchJobRequest) -> dict:
    """Launch a job: parse .wes, apply overrides, run via Processor."""

    from wes.parser import WESParser
    from wes.processor import Processor

    task_name = req.task_name.strip()
    if not task_name:
        raise HTTPException(status_code=400, detail="Task name is required")

    wes_path = Path(task_name + ".wes")
    if not wes_path.exists():
        raise HTTPException(status_code=404, detail=f"Config '{wes_path}' not found")

    processor = Processor()

    for _run_id, task in processor.cache.clean_for_task_names({task_name}):
        if task.jobs_ids and task.ssh_config:
            for jid in task.jobs_ids:
                try:
                    import subprocess
                    subprocess.run(
                        ["ssh", task.ssh_config, f"scancel {jid}"],
                        capture_output=True, text=True, check=False,
                    )
                except Exception:
                    pass

    wes = WESParser()
    try:
        tasks = wes.parse(str(wes_path))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not tasks:
        raise HTTPException(status_code=400, detail="No tasks found in config")

    target = tasks[0]
    for key, val in req.overrides.items():
        if hasattr(target, key):
            setattr(target, key, val)

    from wes.tasks.tasks import TaskManager

    terminal = {State.COMPLETED, State.FAILED, State.CANCELLED}
    task_mgr = TaskManager([target])
    task_mgr.add_create_cb(processor.create_task)
    task_mgr.add_pending_cb(processor.pending_task)
    task_mgr.add_running_cb(processor.running_task)
    task_mgr.add_completed_cb(processor.completed_task)
    task_mgr.add_failing_cb(processor.failing_task)
    try:
        task_mgr.check(target.name)
        deadline = time.time() + 60
        while target.getStatus() not in terminal and time.time() < deadline:
            time.sleep(2)
            task_mgr.check(target.name)
    finally:
        processor.cache.close()

    return {
        "status": "ok",
        "task_name": target.name,
        "run_id": target.run_id,
        "state": target.status.value,
    }


@router.delete("/jobs/{job_id}")
def cancel_job(job_id: str) -> dict:
    """Cancel a running job and clean up."""
    import subprocess as _subprocess

    cache = JobCache(persistent=True)
    messages: list[str] = []
    try:
        data = (cache.get_all() or {}).get(job_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

        task = JobCache.cached_task(job_id, data)
        if task.jobs_ids and task.ssh_config:
            for jid in task.jobs_ids:
                try:
                    _subprocess.run(
                        ["ssh", task.ssh_config, f"scancel {jid}"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    messages.append(f"cancelled slurm job {jid}")
                except Exception:
                    pass
        if task.run_id and task.ssh_config:
            try:
                _subprocess.run(
                    ["ssh", task.ssh_config, f"rm -rf runs/{task.run_id}"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                messages.append(f"removed runs/{task.run_id}")
            except Exception:
                pass
        cache.remove(job_id)
        messages.append("removed from cache")
    finally:
        cache.close()

    msg = "; ".join(messages) if messages else f"job '{job_id}' not found"
    return {"status": "ok", "message": msg}


@router.get("/jobs/{job_id}/logs", response_model=LogData)
def get_job_logs(job_id: str) -> LogData:
    """Get local logs for a job."""
    cache = JobCache(persistent=True)
    try:
        data = (cache.get_all() or {}).get(job_id)
    finally:
        cache.close()

    if data and data.get("run_id"):
        run_dir = Path("results") / data.get("task_name", job_id) / data["run_id"]
    else:
        run_dir = RESULTS_DIR / job_id

    return LogData(
        stdout=_read_file(run_dir / "job_output.txt"),
        stderr=_read_file(run_dir / "job_error.txt"),
        pre_run=_read_file(run_dir / "pre_run_output.txt"),
    )


@router.get("/jobs/{job_id}/remote-logs")
def get_job_remote_logs(job_id: str) -> dict[str, str]:
    """Get remote logs for a job via SSH."""
    cache = JobCache(persistent=True)
    try:
        data = (cache.get_all() or {}).get(job_id)
    finally:
        cache.close()
    if not data or not data.get("ssh"):
        raise HTTPException(status_code=404, detail="Job not available")
    from wes.tasks import Task

    t = Task(
        name=data.get("task_name", job_id),
        git_url=data.get("git_url", ""),
        path=data.get("path", "."),
        ssh_config=data.get("ssh", ""),
        job=data.get("job"),
        branch=data.get("branch", ""),
        run_id=data.get("run_id", ""),
    )
    return t.fetch_remote_logs()


# ──────────────────────────────────────────────
#  Legacy endpoints (backward compat)
# ──────────────────────────────────────────────


@router.get("/tasks/{name}/logs", response_model=LogData)
def get_task_logs(name: str) -> LogData:
    return get_logs(name)


def get_logs(name: str) -> LogData:
    task_dir = RESULTS_DIR / name
    return LogData(
        stdout=_read_file(task_dir / "job_output.txt"),
        stderr=_read_file(task_dir / "job_error.txt"),
        pre_run=_read_file(task_dir / "pre_run_output.txt"),
    )


@router.get("/tasks/{name}/artifacts", response_model=list[ArtifactEntry])
def list_artifacts(name: str) -> list[ArtifactEntry]:
    artifacts: list[ArtifactEntry] = []
    task_dir = RESULTS_DIR / name
    if not task_dir.exists():
        return artifacts
    for path in sorted(task_dir.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(task_dir))
            suffix = path.suffix.lower()
            kind_map = {
                ".mp4": "video",
                ".zip": "model",
                ".csv": "csv",
                ".png": "image",
                ".jpg": "image",
                ".jpeg": "image",
                ".gif": "image",
                ".webp": "image",
            }
            artifacts.append(
                ArtifactEntry(
                    name=path.name,
                    kind=kind_map.get(suffix, "file"),
                    path=rel,
                    size=path.stat().st_size,
                )
            )
    return artifacts


@router.get("/tasks/{name}/artifacts/{path:path}")
def serve_artifact(name: str, path: str) -> FileResponse:
    file_path = RESULTS_DIR / name / path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(str(file_path))


@router.get("/tasks/{name}/progress")
def get_progress(name: str) -> ProgressData:
    csv_files = list((RESULTS_DIR / name).rglob("*.csv"))
    if not csv_files:
        return ProgressData()
    content = csv_files[0].read_text(encoding="utf-8", errors="replace")
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return ProgressData()
    return ProgressData(columns=rows[0], rows=rows[1:])


@router.post("/tasks/{name}/refresh")
def refresh_artifacts(name: str) -> dict:
    cache = JobCache(persistent=True)
    try:
        matches = cache.find_by_task_name(name)
        if not matches:
            raise HTTPException(status_code=404, detail=f"Job '{name}' not found")
        run_id, data = matches[-1]
        task = JobCache.cached_task(run_id, data)
        if task.artifacts:
            task._Task__sync_artifacts()
        return {"status": "ok", "message": f"Refreshed artifacts for '{name}'"}
    finally:
        cache.close()


@router.post("/run")
def submit_run(req: RunRequest) -> dict:
    import os
    import tempfile

    from wes.parser import WESParser
    from wes.processor import Processor

    parser = WESParser()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".wes", delete=False, encoding="utf-8"
        ) as f:
            f.write(req.config)
            tmp_path = f.name
        tasks = parser.parse(tmp_path)
    except Exception as e:
        log.error("Failed to parse config: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        if tmp_path:
            os.unlink(tmp_path)

    processor = Processor()
    terminal = {State.COMPLETED, State.FAILED, State.CANCELLED}
    from wes.tasks.tasks import TaskManager

    started: list[str] = []
    errors: list[str] = []
    try:
        for task in tasks:
            task_mgr = TaskManager([task])
            task_mgr.add_create_cb(processor.create_task)
            task_mgr.add_pending_cb(processor.pending_task)
            task_mgr.add_running_cb(processor.running_task)
            task_mgr.add_completed_cb(processor.completed_task)
            task_mgr.add_failing_cb(processor.failing_task)
            try:
                task_mgr.check(task.name)
                deadline = time.time() + 60
                while task.getStatus() not in terminal and time.time() < deadline:
                    time.sleep(2)
                    task_mgr.check(task.name)
                started.append(task.name)
            except Exception as e:
                errors.append(f"{task.name}: {e}")
    finally:
        processor.cache.close()

    return {"status": "ok", "tasks": started, "errors": errors}


# ──────────────────────────────────────────────
#  Cluster / nodes / slurm
# ──────────────────────────────────────────────


@router.get("/nodes", response_model=ClusterData)
def get_nodes(ssh: str = "") -> ClusterData:
    if not ssh:
        cache = JobCache(persistent=True)
        try:
            for data in (cache.get_all() or {}).values():
                if data.get("ssh"):
                    ssh = data["ssh"]
                    break
        finally:
            cache.close()
    if not ssh:
        return ClusterData(ssh="", error="No SSH host specified")
    from wes import WES

    try:
        nodes = WES(ssh).get_nodes()
    except Exception as e:
        return ClusterData(ssh=ssh, error=str(e))
    return ClusterData(
        ssh=ssh,
        nodes=[
            NodeInfo(
                name=n.name,
                partition=n.partition,
                state=n.state,
                cpus=n.cpus,
                gpus=n.gpus,
                memory=n.memory,
                reason=n.reason,
            )
            for n in nodes
        ],
    )


@router.get("/cluster")
def get_cluster(ssh: str = "") -> dict:
    if not ssh:
        cache = JobCache(persistent=True)
        try:
            for data in (cache.get_all() or {}).values():
                if data.get("ssh"):
                    ssh = data["ssh"]
                    break
        finally:
            cache.close()
    if not ssh:
        return {"ssh": "", "error": "No SSH host specified"}
    from wes import WES

    try:
        wes = WES(ssh)
        nodes = wes.get_nodes()
        jobs = wes.get_jobs()
        capacity = wes.get_capacity()
    except Exception as e:
        return {"ssh": ssh, "error": str(e)}
    return {
        "ssh": ssh,
        "nodes": [
            {
                "name": n.name,
                "partition": n.partition,
                "state": n.state,
                "cpus": n.cpus,
                "gpus": n.gpus,
                "memory": n.memory,
                "reason": n.reason,
            }
            for n in nodes
        ],
        "capacity": [
            {
                "name": c.name,
                "cpu_total": c.cpu_total,
                "cpu_alloc": c.cpu_alloc,
                "cpu_free": c.cpu_free,
                "mem_total_mb": c.mem_total_mb,
                "mem_alloc_mb": c.mem_alloc_mb,
                "mem_free_mb": c.mem_free_mb,
                "gpu_total": c.gpu_total,
                "gpu_alloc": c.gpu_alloc,
                "gpu_free": c.gpu_free,
            }
            for c in capacity
        ],
        "jobs": [
            {
                "job_id": j.job_id,
                "user": j.user,
                "name": j.name,
                "state": j.state,
                "time": j.time,
                "nodes": j.nodes,
                "partition": j.partition,
                "reason": j.reason,
                "cpus": j.cpus,
                "memory": j.memory,
            }
            for j in jobs
        ],
    }


# ──────────────────────────────────────────────
#  Settings
# ──────────────────────────────────────────────

_SETTINGS_FILE = ".wes-settings.yml"
_MAX_HISTORY = 20


def _load_settings() -> dict:
    path = Path(_SETTINGS_FILE)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_settings(data: dict) -> None:
    with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False)


@router.get("/settings", response_model=SettingsData)
def get_settings() -> SettingsData:
    data = _load_settings()
    return SettingsData(
        ssh_hosts=data.get("ssh_hosts", []),
        form_history=data.get("form_history", {}),
        query_interval=data.get("query_interval", 10),
    )


@router.put("/settings")
def update_settings(req: SettingsData) -> dict:
    _save_settings(
        {
            "ssh_hosts": req.ssh_hosts,
            "form_history": req.form_history,
            "query_interval": req.query_interval,
        }
    )
    return {"status": "ok"}


@router.post("/settings/history")
def record_form_history(entry: dict) -> dict:
    data = _load_settings()
    history: dict[str, list[str]] = data.get("form_history", {})
    for key in ("git_url", "ssh", "branch", "job"):
        val = entry.get(key, "").strip()
        if not val:
            continue
        lst = history.setdefault(key, [])
        if val in lst:
            lst.remove(val)
        lst.insert(0, val)
        history[key] = lst[:_MAX_HISTORY]
    data["form_history"] = history
    _save_settings(data)
    return {"status": "ok"}
