from __future__ import annotations

import csv
import io
import logging
import re
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from web.models import (
    ArtifactEntry,
    ClusterData,
    CreateTaskRequest,
    JobInfo,
    JobsData,
    LogData,
    NodeInfo,
    ProgressData,
    RunRequest,
    SettingsData,
    SlurmJobResponse,
    SlurmJobSpec,
    SubmitRequest,
    TaskConfig,
    TaskSummary,
)
from wes.cache import JobCache
from wes.states import State

log = logging.getLogger("wes.web")

router = APIRouter(prefix="/api")

RESULTS_DIR = Path("results")
_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x1b]*\x1b\\")


def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def _read_file(path: Path) -> str:
    if path.exists():
        return _strip_ansi(path.read_text(encoding="utf-8", errors="replace"))
    return ""


@router.get("/tasks", response_model=list[TaskSummary])
def list_tasks() -> list[TaskSummary]:
    cache = JobCache(persistent=True)
    seen: set[str] = set()
    tasks: list[TaskSummary] = []
    try:
        for name, data in cache.get_all().items():
            seen.add(name)
            tasks.append(
                TaskSummary(
                    name=name,
                    status=data.get("state", "UNKNOWN"),
                    git_url=data.get("git_url", ""),
                    branch=data.get("branch", ""),
                    ssh=data.get("ssh", ""),
                    job_ids=data.get("jobs_ids", []),
                    job=data.get("job"),
                    artifacts=data.get("artifacts", []),
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

    if RESULTS_DIR.exists():
        for entry in sorted(RESULTS_DIR.iterdir()):
            if entry.is_dir() and entry.name not in seen:
                has_output = (entry / "job_output.txt").exists()
                tasks.append(
                    TaskSummary(
                        name=entry.name,
                        status="COMPLETED" if has_output else "UNKNOWN",
                        git_url="",
                        branch="",
                        ssh="",
                        job_ids=[],
                    )
                )
    return tasks


@router.get("/tasks/{name}", response_model=TaskSummary)
def get_task(name: str) -> TaskSummary:
    cache = JobCache(persistent=True)
    try:
        data = cache.get_all().get(name)
        if data:
            return TaskSummary(
                name=name,
                status=data.get("state", "UNKNOWN"),
                git_url=data.get("git_url", ""),
                branch=data.get("branch", ""),
                ssh=data.get("ssh", ""),
                job_ids=data.get("jobs_ids", []),
                job=data.get("job"),
                artifacts=data.get("artifacts", []),
                partition=data.get("partition", ""),
                cpus=data.get("cpus", ""),
                gpus=data.get("gpus", ""),
                memory=data.get("memory", ""),
                time=data.get("time", ""),
                nodelist=data.get("nodelist", ""),
            )
    finally:
        cache.close()

    task_dir = RESULTS_DIR / name
    if task_dir.exists():
        has_output = (task_dir / "job_output.txt").exists()
        return TaskSummary(
            name=name,
            status="COMPLETED" if has_output else "UNKNOWN",
            git_url="",
            branch="",
            ssh="",
            job_ids=[],
        )
    raise HTTPException(status_code=404, detail=f"Task '{name}' not found")


@router.get("/tasks/{name}/logs", response_model=LogData)
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
            if suffix == ".mp4":
                kind = "video"
            elif suffix == ".zip":
                kind = "model"
            elif suffix == ".csv":
                kind = "csv"
            elif suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                kind = "image"
            else:
                kind = "file"
            artifacts.append(
                ArtifactEntry(
                    name=path.name,
                    kind=kind,
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

    csv_path = csv_files[0]
    content = csv_path.read_text(encoding="utf-8", errors="replace")
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return ProgressData()

    columns = rows[0]
    data_rows = rows[1:]
    return ProgressData(columns=columns, rows=data_rows)


@router.post("/tasks/{name}/refresh")
def refresh_artifacts(name: str) -> dict:
    cache = JobCache(persistent=True)
    try:
        data = cache.get_all().get(name)
        if not data:
            raise HTTPException(status_code=404, detail=f"Task '{name}' not found")
        task = JobCache.cached_task(name, data)
        if task.artifacts:
            task._Task__sync_artifacts()
        return {"status": "ok", "message": f"Refreshed artifacts for '{name}'"}
    finally:
        cache.close()


@router.post("/run")
def submit_run(req: RunRequest) -> dict:
    import os
    import subprocess
    import tempfile

    from wes.parser import WESParser

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

    cache = JobCache(persistent=True)
    started: list[str] = []
    errors: list[str] = []
    try:
        for task in tasks:
            if task.name in cache.get_all():
                log.info("Task '%s' already in cache, skipping", task.name)
                continue

            log.info("Executing task '%s'", task.name)
            try:
                task.execute()
            except (subprocess.CalledProcessError, OSError) as e:
                msg = f"{task.name}: {e}"
                log.error("Task '%s' failed: %s", task.name, e)
                errors.append(msg)
                continue

            log.info("Task '%s' status: %s", task.name, task.status.value)
            if task.status == State.RUNNING:
                cache.set(task.name, JobCache.task_to_cache_data(task))
            started.append(task.name)
    finally:
        cache.close()

    return {"status": "ok", "tasks": started, "errors": errors}


@router.delete("/tasks/{name}")
def delete_task(name: str, remove_config: bool = True) -> dict:
    """Remove a task: cancel jobs, clean up remote dirs, remove cache + config."""
    import subprocess as _subprocess

    cache = JobCache(persistent=True)
    messages: list[str] = []
    try:
        data = cache.get_all().get(name)
        if data:
            task = JobCache.cached_task(name, data)
            if task.jobs_ids and task.ssh_config:
                for jid in task.jobs_ids:
                    try:
                        _subprocess.run(
                            ["ssh", task.ssh_config, f"scancel {jid}"],
                            capture_output=True, text=True, check=False,
                        )
                        messages.append(f"cancelled job {jid}")
                    except Exception:
                        pass
                if task.run_id and task.ssh_config:
                    try:
                        _subprocess.run(
                            ["ssh", task.ssh_config, f"rm -rf runs/{task.run_id}"],
                            capture_output=True, text=True, check=False,
                        )
                        messages.append(f"removed runs/{task.run_id}")
                    except Exception:
                        pass
            cache.remove(name)
            messages.append("removed from cache")
    finally:
        cache.close()

    if remove_config:
        wes_path = Path(name + ".wes")
        if wes_path.exists():
            wes_path.unlink()
            messages.append(f"deleted {wes_path}")

    local_results = Path("results") / name
    if local_results.exists():
        import shutil
        shutil.rmtree(local_results, ignore_errors=True)
        messages.append("removed local results")

    msg = "; ".join(messages) if messages else f"task '{name}' not found"
    return {"status": "ok", "message": msg}


@router.get("/nodes", response_model=ClusterData)
def get_nodes(ssh: str = "") -> ClusterData:
    if not ssh:
        cache = JobCache(persistent=True)
        try:
            for data in cache.get_all().values():
                if data.get("ssh"):
                    ssh = data["ssh"]
                    break
        finally:
            cache.close()

    if not ssh:
        return ClusterData(ssh="", error="No SSH host specified and none found in cached tasks")

    from wes import WES

    try:
        nodes = WES(ssh).get_nodes()
    except Exception as e:
        log.error("Failed to fetch nodes from '%s': %s", ssh, e)
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


@router.get("/jobs", response_model=JobsData)
def get_jobs(ssh: str = "") -> JobsData:
    if not ssh:
        cache = JobCache(persistent=True)
        try:
            for data in cache.get_all().values():
                if data.get("ssh"):
                    ssh = data["ssh"]
                    break
        finally:
            cache.close()

    if not ssh:
        return JobsData(ssh="", error="No SSH host specified and none found in cached tasks")

    from wes import WES

    try:
        jobs = WES(ssh).get_jobs()
    except Exception as e:
        log.error("Failed to fetch jobs from '%s': %s", ssh, e)
        return JobsData(ssh=ssh, error=str(e))

    return JobsData(
        ssh=ssh,
        jobs=[
            JobInfo(
                job_id=j.job_id,
                user=j.user,
                name=j.name,
                state=j.state,
                time=j.time,
                nodes=j.nodes,
                partition=j.partition,
                reason=j.reason,
                cpus=j.cpus,
                memory=j.memory,
            )
            for j in jobs
        ],
    )


@router.get("/cluster")
def get_cluster(ssh: str = "") -> dict:
    """Return both nodes and jobs for a cluster in one call."""
    if not ssh:
        cache = JobCache(persistent=True)
        try:
            for data in cache.get_all().values():
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
        log.error("Failed to fetch cluster data from '%s': %s", ssh, e)
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


@router.get("/config", response_model=list[TaskConfig])
def get_config() -> list[TaskConfig]:
    """Parse .wes files in project root and return structured task configs."""
    from wes.parser import WESParser

    wes_files = sorted(Path(".").glob("*.wes"))
    if not wes_files:
        return []

    parser = WESParser()
    tasks: list[TaskConfig] = []
    for wes_file in wes_files:
        try:
            for task in parser.parse(str(wes_file)):
                tasks.append(
                    TaskConfig(
                        name=task.name,
                        git_url=task.git_url,
                        branch=task.branch,
                        ssh=task.ssh_config,
                        job=task.job or "",
                        partition=task.partition,
                        cpus=task.cpus,
                        gpus=task.gpus,
                        memory=task.memory,
                        time=task.time,
                        nodelist=task.nodelist,
                    )
                )
        except Exception as e:
            log.error("Failed to parse %s: %s", wes_file, e)
    return tasks


@router.post("/submit")
def submit_task(req: SubmitRequest) -> dict:
    """Submit a task from .wes config with optional resource overrides."""
    import subprocess

    from wes.parser import WESParser
    from wes.tasks import Task

    wes_files = sorted(Path(".").glob("*.wes"))
    if not wes_files:
        raise HTTPException(status_code=400, detail="No .wes config files found")

    parser = WESParser()
    target: Task | None = None
    for wes_file in wes_files:
        try:
            for task in parser.parse(str(wes_file)):
                if task.name == req.name:
                    target = task
                    break
        except Exception as e:
            log.error("Failed to parse %s: %s", wes_file, e)
        if target:
            break

    if not target:
        raise HTTPException(status_code=404, detail=f"Task '{req.name}' not found in .wes configs")

    for key, val in req.overrides.items():
        if hasattr(target, key):
            setattr(target, key, val)

    cache = JobCache(persistent=True)
    try:
        if target.name in cache.get_all():
            return {
                "status": "skipped",
                "message": f"Task '{target.name}' already in cache",
            }
        try:
            target.execute()
        except (subprocess.CalledProcessError, OSError) as e:
            log.error("Task '%s' failed: %s", target.name, e)
            raise HTTPException(status_code=500, detail=str(e)) from e

        if target.status == State.RUNNING:
            cache.set(target.name, JobCache.task_to_cache_data(target))
    finally:
        cache.close()

    return {"status": "ok", "task": target.name, "state": target.status.value}


@router.post("/tasks")
def create_task(req: CreateTaskRequest) -> dict:
    """Create a new task: generate .wes config, parse, and execute."""
    import subprocess

    from wes.parser import WESParser

    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Task name is required")

    task_data: dict[str, str] = {}
    if req.git_url.strip():
        task_data["git_url"] = req.git_url.strip()
    if req.branch.strip():
        task_data["branch"] = req.branch.strip()
    if req.ssh.strip():
        task_data["ssh"] = req.ssh.strip()
    if req.job.strip():
        task_data["job"] = req.job.strip()
    if req.partition.strip():
        task_data["partition"] = req.partition.strip()
    if req.cpus.strip():
        task_data["cpus"] = req.cpus.strip()
    if req.gpus.strip():
        task_data["gpus"] = req.gpus.strip()
    if req.memory.strip():
        task_data["memory"] = req.memory.strip()
    if req.time.strip():
        task_data["time"] = req.time.strip()
    if req.nodelist.strip():
        task_data["nodelist"] = req.nodelist.strip()

    config = {"sequence": [{name: task_data}]}
    wes_path = Path(name + ".wes")

    if wes_path.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Config file '{wes_path}' already exists",
        )

    try:
        wes_path.write_text(yaml.dump(config, default_flow_style=False), encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}") from e

    record_form_history(task_data)

    has_required = all(task_data.get(f) for f in ("git_url", "ssh", "job"))
    if not has_required:
        return {
            "status": "ok",
            "task": name,
            "state": "CREATED",
            "message": f"Created '{name}.wes' (fill in git_url, ssh, job to run)",
        }

    parser = WESParser()
    try:
        tasks = parser.parse(str(wes_path))
    except Exception as e:
        log.error("Failed to parse generated config: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not tasks:
        raise HTTPException(status_code=400, detail="No tasks found in generated config")

    target = tasks[0]
    cache = JobCache(persistent=True)
    try:
        try:
            target.execute()
        except (subprocess.CalledProcessError, OSError) as e:
            log.error("Task '%s' failed: %s", target.name, e)
            raise HTTPException(status_code=500, detail=str(e)) from e

        if target.status == State.RUNNING:
            cache.set(target.name, JobCache.task_to_cache_data(target))
    finally:
        cache.close()

    return {"status": "ok", "task": target.name, "state": target.status.value}


@router.post("/slurm")
def generate_slurm(spec: SlurmJobSpec) -> SlurmJobResponse:
    """Generate an sbatch script and CLI args from a SlurmJobSpec."""
    from wes import SlurmJob

    job = SlurmJob(
        name=spec.name,
        partition=spec.partition,
        nodes=spec.nodes,
        ntasks=spec.ntasks,
        cpus_per_task=spec.cpus_per_task,
        gres=spec.gres,
        memory=spec.memory,
        time=spec.time,
        nodelist=spec.nodelist,
        output=spec.output,
        error=spec.error,
        email=spec.email,
        mail_type=spec.mail_type,
        account=spec.account,
        qos=spec.qos,
        workdir=spec.workdir,
        env_vars=spec.env_vars,
        command=spec.command,
        script_path=spec.script_path,
    )
    return SlurmJobResponse(script=job.to_script(), args=job.sbatch_args())


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
    )


@router.put("/settings")
def update_settings(req: SettingsData) -> dict:
    _save_settings({
        "ssh_hosts": req.ssh_hosts,
        "form_history": req.form_history,
    })
    return {"status": "ok"}


@router.post("/settings/history")
def record_form_history(entry: dict) -> dict:
    """Record form field values for autocomplete suggestions."""
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
