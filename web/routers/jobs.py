from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from web.engine import cancel_slurm_jobs
from web.models import JobSummary, LogData, ProgressData
from web.services.artifacts import (
    list_job_artifacts,
    parse_csv,
    parse_remote_files,
    read_local_logs,
    read_local_progress,
    read_logs,
)
from web.services.config import RESULTS_DIR, find_local_config, known_ssh_hosts
from web.services.jobs import build_cache_index, get_ssh_user
from web.services.mock import (
    mock_artifact_content,
    mock_artifact_paths,
    mock_artifact_size,
    mock_csv_progress,
    mock_enabled,
    mock_has_job,
    mock_log_data,
    mock_remote_logs,
    mock_user_jobs,
)
from wes.engine import Engine
from wes.jobs.job import JobInfo
from wes.jobs.query import JobsQuery
from wes.remote.runner import SshRunner

router = APIRouter()


def _reachable_hosts() -> set[str]:
    reachable: set[str] = set()
    for ssh in known_ssh_hosts():
        runner = SshRunner(ssh)
        ok, _ = runner.run_command("squeue")
        if ok:
            reachable.add(ssh)
    return reachable


def _git_name(git_url: str) -> str:
    return git_url.split("/")[-1].replace(".git", "")


def _local_job_context(job_id: str) -> dict | None:
    cached = build_cache_index().get(job_id, {})
    task_name = cached.get("task_name", "")
    run_id = cached.get("run_id", "")
    if task_name and run_id:
        return {
            "task_name": task_name,
            "run_id": run_id,
            "git_url": cached.get("git_url", ""),
            "artifacts": cached.get("artifacts", []),
        }
    config = find_local_config(job_id)
    if config:
        task = config.get("task", {})
        job = config.get("job", {})
        task_name = task.get("name", "")
        run_id = job.get("namespace", "")
        if task_name and run_id:
            return {
                "task_name": task_name,
                "run_id": run_id,
                "git_url": task.get("git_url", ""),
                "artifacts": task.get("artifacts", []),
            }
    return None


def _find_slurm_job(query: JobsQuery, job_id: str, cached: dict | None) -> JobInfo | None:
    want_ids = {str(i) for i in (cached or {}).get("jobs_ids", [])}
    for j in query.get():
        if (
            j.job_id == job_id
            or (want_ids and j.job_id in want_ids)
            or j.name.endswith("_" + job_id)
        ):
            return j
    return None


def _to_summary(ssh: str, job, cached: dict) -> JobSummary:
    return JobSummary(
        job_id=cached.get("run_id") or job.job_id,
        task_name=cached.get("task_name") or job.name,
        state=job.state,
        run_id=cached.get("run_id", ""),
        jobs_ids=cached.get("jobs_ids", []),
        git_url=cached.get("git_url", ""),
        branch=cached.get("branch", ""),
        ssh=ssh,
        job=cached.get("job", ""),
        partition=job.partition,
        cpus=job.cpus,
        gpus=cached.get("gpus", ""),
        memory=job.memory,
        time=job.time,
        nodelist=job.nodes,
    )


@router.get("/jobs", response_model=list[JobSummary])
def list_jobs(response: Response = None) -> list[JobSummary]:
    if mock_enabled():
        return mock_user_jobs()

    engine = Engine()
    for ssh in known_ssh_hosts():
        engine.add_user(ssh)
    engine.scan_jobs()
    engine.scan_slurm_info()

    # The cluster may be unreachable while the API still responds. In that
    # case the scan returns no live slurm info, which would degrade running
    # jobs to COMPLETED. Signal it so the dashboard keeps showing last seen.
    reachable = _reachable_hosts()
    if response is not None:
        response.headers["X-WES-STALE"] = "1" if len(reachable) < len(known_ssh_hosts()) else "0"

    jobs: list[JobSummary] = []
    for job in engine.get_user_jobs():
        if job.info:
            state = job.info.state
        else:
            state = "COMPLETED"

        jobs.append(
            JobSummary(
                job_id=job.namespace,
                task_name=job.task.name,
                state=state,
                run_id=job.namespace,
                git_url=job.task.git_url,
                branch=job.task.branch,
                ssh=job.ssh_config,
                partition=job.task.partition,
                cpus=job.task.cpus,
                gpus=job.task.gpus,
                memory=job.task.memory,
                time=job.task.time,
                nodelist=job.task.nodelist,
                priority=job.info.priority if job.info else "",
            )
        )

    return jobs


@router.get("/jobs/{job_id}", response_model=JobSummary)
def get_job(job_id: str) -> JobSummary:
    if mock_enabled():
        for job in mock_user_jobs():
            if job.job_id == job_id:
                return job
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    cache_idx = build_cache_index()
    cached = cache_idx.get(job_id, {})

    for ssh in known_ssh_hosts():
        try:
            query = JobsQuery(ssh)
            j = _find_slurm_job(query, job_id, cached)
            if j:
                return _to_summary(ssh, j, cached)
            user = get_ssh_user(ssh)
            for rj in query.get_recent(user=user, hours=48):
                if rj.job_id == job_id:
                    return _to_summary(ssh, rj, cached)
        except Exception:
            pass

    config = find_local_config(job_id)
    if config:
        t = config.get("task", {})
        j = config.get("job", {})
        return JobSummary(
            job_id=j.get("namespace", job_id),
            task_name=t.get("name", ""),
            state="COMPLETED",
            run_id=j.get("namespace", ""),
            git_url=t.get("git_url", ""),
            branch=t.get("branch", ""),
            ssh=j.get("ssh_config", ""),
            partition=t.get("partition", ""),
            cpus=t.get("cpus", ""),
            gpus=t.get("gpus", ""),
            memory=t.get("memory", ""),
            time=t.get("time", ""),
            nodelist=t.get("nodelist", ""),
        )

    raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")


@router.delete("/jobs/{job_id}")
def cancel_job(job_id: str) -> dict:
    messages: list[str] = []
    cache_idx = build_cache_index()
    cached = cache_idx.get(job_id, {})
    slurm_ids = cached.get("jobs_ids", []) or [job_id]
    for ssh in known_ssh_hosts():
        messages.extend(cancel_slurm_jobs(ssh, slurm_ids))
    msg = "; ".join(messages) if messages else f"Job '{job_id}' not found on any host"
    return {"status": "ok", "message": msg}


@router.get("/jobs/{job_id}/logs", response_model=LogData)
def get_job_logs(job_id: str) -> LogData:
    if mock_enabled():
        return mock_log_data(job_id)
    config = find_local_config(job_id)
    if config:
        task_name = config.get("task", {}).get("name", "")
        namespace = config.get("job", {}).get("namespace", "")
        if task_name and namespace:
            return read_logs(RESULTS_DIR / task_name / namespace)
    return read_logs(RESULTS_DIR / job_id)


@router.get("/jobs/{job_id}/remote-logs")
def get_job_remote_logs(job_id: str) -> dict[str, str]:
    if mock_enabled():
        logs = mock_remote_logs(job_id)
        if logs is None:
            raise HTTPException(status_code=404, detail="Job not available")
        return logs

    ctx = _local_job_context(job_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Job not available")
    return read_local_logs(f"{ctx['task_name']}/{ctx['run_id']}").model_dump()


@router.get("/jobs/{job_id}/remote-artifacts")
def get_job_remote_artifacts(job_id: str) -> list[dict]:
    if mock_enabled():
        artifacts = parse_remote_files(mock_artifact_paths(job_id))
        for a in artifacts:
            a["size"] = mock_artifact_size(a["path"], a["kind"])
        return artifacts

    ctx = _local_job_context(job_id)
    if not ctx:
        return []
    entries = list_job_artifacts(
        ctx["task_name"], ctx["run_id"], _git_name(ctx["git_url"]), ctx["artifacts"]
    )
    return [a.model_dump() for a in entries]


@router.get("/jobs/{job_id}/remote-artifacts/{path:path}")
def serve_job_remote_artifact(job_id: str, path: str):
    if mock_enabled():
        if not mock_has_job(job_id):
            raise HTTPException(status_code=404, detail="Artifact not found")
        content = mock_artifact_content(path)
        if content is None:
            raise HTTPException(status_code=404, detail="Artifact not found")
        if path.lower().endswith(".png"):
            media_type = "image/png"
        elif path.lower().endswith(".csv"):
            media_type = "text/csv"
        elif path.lower().endswith(".zip"):
            media_type = "application/zip"
        else:
            media_type = "application/octet-stream"
        return Response(content=content, media_type=media_type)

    ctx = _local_job_context(job_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Artifact not found")
    file_path = RESULTS_DIR / ctx["task_name"] / ctx["run_id"] / _git_name(ctx["git_url"]) / path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(str(file_path), filename=Path(path).name)


@router.get("/jobs/{job_id}/remote-csv")
def get_job_remote_csv(job_id: str) -> ProgressData:
    if mock_enabled():
        return parse_csv(mock_csv_progress(job_id))

    ctx = _local_job_context(job_id)
    if not ctx:
        return ProgressData()
    return read_local_progress(
        f"{ctx['task_name']}/{ctx['run_id']}/{_git_name(ctx['git_url'])}"
    )
