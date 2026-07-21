from __future__ import annotations

import csv
import io
import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from web.models import (
    ArtifactEntry,
    ClusterData,
    JobInfo,
    JobsData,
    LogData,
    NodeInfo,
    ProgressData,
    RunRequest,
    SlurmJobResponse,
    SlurmJobSpec,
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
def delete_task(name: str) -> dict:
    cache = JobCache(persistent=True)
    try:
        cache.remove(name)
    finally:
        cache.close()
    return {"status": "ok"}


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
