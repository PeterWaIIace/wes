from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from web.engine import (
    cancel_slurm_jobs,
    get_remote_file,
    list_remote_files,
    read_remote_log,
)
from web.models import JobSummary, LogData, ProgressData
from web.services.artifacts import parse_csv, parse_remote_files, read_logs
from web.services.config import RESULTS_DIR, find_local_config, known_ssh_hosts
from web.services.jobs import build_cache_index, get_ssh_user, make_job_dir
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
from wes.jobs.query import JobsQuery

router = APIRouter()


def _to_summary(ssh: str, job, cached: dict) -> JobSummary:
    return JobSummary(
        job_id=job.job_id,
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
def list_jobs() -> list[JobSummary]:
    if mock_enabled():
        return mock_user_jobs()

    engine = Engine()
    for ssh in known_ssh_hosts():
        engine.add_user(ssh)
    engine.scan_jobs()
    engine.scan_slurm_info()

    jobs: list[JobSummary] = []
    for job in engine.get_user_jobs():
        if job.info:
            state = job.info.state
            job_id = job.info.job_id
        else:
            state = "COMPLETED"
            job_id = job.namespace

        jobs.append(
            JobSummary(
                job_id=job_id,
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

    for ssh in known_ssh_hosts():
        try:
            query = JobsQuery(ssh)
            for j in query.get():
                if j.job_id == job_id:
                    return _to_summary(ssh, j, cache_idx.get(j.job_id, {}))
            user = get_ssh_user(ssh)
            for j in query.get_recent(user=user, hours=48):
                if j.job_id == job_id:
                    return _to_summary(ssh, j, cache_idx.get(j.job_id, {}))
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
    for ssh in known_ssh_hosts():
        messages.extend(cancel_slurm_jobs(ssh, [job_id]))
    msg = "; ".join(messages) if messages else f"Job '{job_id}' not found on any host"
    return {"status": "ok", "message": msg}


@router.get("/jobs/{job_id}/logs", response_model=LogData)
def get_job_logs(job_id: str) -> LogData:
    if mock_enabled():
        return mock_log_data(job_id)
    return read_logs(RESULTS_DIR / job_id)


@router.get("/jobs/{job_id}/remote-logs")
def get_job_remote_logs(job_id: str) -> dict[str, str]:
    if mock_enabled():
        logs = mock_remote_logs(job_id)
        if logs is None:
            raise HTTPException(status_code=404, detail="Job not available")
        return logs

    cache_idx = build_cache_index()
    cached = cache_idx.get(job_id, {})

    for ssh in known_ssh_hosts():
        try:
            for j in JobsQuery(ssh).get():
                if j.job_id == job_id:
                    job_dir = make_job_dir(cached, j.name)
                    return {
                        "stdout": read_remote_log(ssh, f"{job_dir}/job_output.txt"),
                        "stderr": read_remote_log(ssh, f"{job_dir}/job_error.txt"),
                        "pre_run": read_remote_log(ssh, f"{job_dir}/pre_run_output.txt"),
                    }
        except Exception:
            pass

    config = find_local_config(job_id)
    if config:
        ssh = config.get("job", {}).get("ssh_config", "")
        task_name = config.get("task", {}).get("name", "")
        namespace = config.get("job", {}).get("namespace", "")
        job_dir = f"{task_name}/{namespace}" if namespace else task_name
        return {
            "stdout": read_remote_log(ssh, f"{job_dir}/job_output.txt"),
            "stderr": read_remote_log(ssh, f"{job_dir}/job_error.txt"),
            "pre_run": read_remote_log(ssh, f"{job_dir}/pre_run_output.txt"),
        }

    raise HTTPException(status_code=404, detail="Job not available")


@router.get("/jobs/{job_id}/remote-artifacts")
def get_job_remote_artifacts(job_id: str) -> list[dict]:
    if mock_enabled():
        artifacts = parse_remote_files(mock_artifact_paths(job_id))
        for a in artifacts:
            a["size"] = mock_artifact_size(a["path"], a["kind"])
        return artifacts

    cache_idx = build_cache_index()
    cached = cache_idx.get(job_id, {})

    for ssh in known_ssh_hosts():
        try:
            for j in JobsQuery(ssh).get():
                if j.job_id == job_id:
                    directory = make_job_dir(cached, j.name)
                    files = list_remote_files(ssh, directory)
                    return parse_remote_files(files)
        except Exception:
            pass

    for config_path in RESULTS_DIR.glob(f"*_{job_id}/*_config.json"):
        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
            ssh = config.get("job", {}).get("ssh_config", "")
            task_name = config.get("task", {}).get("name", "")
            job_dir = f"{task_name}/{job_id}"
            files = list_remote_files(ssh, job_dir)
            return parse_remote_files(files)
        except Exception:
            continue
    return []


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

    cache_idx = build_cache_index()
    cached = cache_idx.get(job_id, {})

    ssh = cached.get("ssh", "")
    if ssh:
        tmp = get_remote_file(ssh, path)
        if tmp:
            return FileResponse(tmp, filename=Path(path).name)

    for ssh in known_ssh_hosts():
        try:
            for j in JobsQuery(ssh).get():
                if j.job_id == job_id:
                    tmp = get_remote_file(ssh, path)
                    if tmp:
                        return FileResponse(tmp, filename=Path(path).name)
        except Exception:
            pass
    raise HTTPException(status_code=404, detail="Artifact not found")


@router.get("/jobs/{job_id}/remote-csv")
def get_job_remote_csv(job_id: str) -> ProgressData:
    if mock_enabled():
        return parse_csv(mock_csv_progress(job_id))

    cache_idx = build_cache_index()
    cached = cache_idx.get(job_id, {})

    for ssh in known_ssh_hosts():
        try:
            for j in JobsQuery(ssh).get():
                if j.job_id == job_id:
                    directory = make_job_dir(cached, j.name)
                    csv_files = list_remote_files(ssh, directory)
                    csv_paths = [f for f in csv_files if f.endswith(".csv")]
                    if not csv_paths:
                        return ProgressData()
                    content = read_remote_log(ssh, csv_paths[0])
                    if not content:
                        return ProgressData()
                    return parse_csv(content)
        except Exception:
            pass
    return ProgressData()
