from __future__ import annotations

import re
import io
import csv
import json
import logging
import tempfile
import subprocess
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from wes.jobs.job import SshItem
from wes.jobs.query import JobsQuery
from wes.remote.runner import SshRunner
from wes.jobs.scanner import JobScanner

from web.cache import JobCache
from web.engine import (
    cancel_slurm_jobs,
    get_cluster_data,
    get_nodes,
    read_remote_log,
    remove_remote_dir,
)
from web.models import (
    ArtifactEntry,
    ClusterData,
    CreateTaskRequest,
    JobSummary,
    LogData,
    NodeInfo,
    ProgressData,
    SettingsData,
    TaskInfo,
)
from web.parser import parse_wes_file

log = logging.getLogger("wes.web")

router = APIRouter(prefix="/api")

RESULTS_DIR = Path("results")
_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x1b]*\x1b\\")


def _read_file(path: Path) -> str:
    if path.exists():
        return _ANSI.sub("", path.read_text(encoding="utf-8", errors="replace"))
    return ""


def _find_local_config(job_id: str) -> dict | None:
    for config_path in RESULTS_DIR.glob(f"*_{job_id}/*_config.json"):
        try:
            with open(config_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return None


_REMOTE_KIND_MAP = {
    ".mp4": "video",
    ".zip": "model",
    ".csv": "csv",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
}


def _parse_remote_files(lines: list[str]) -> list[dict]:
    artifacts: list[dict] = []
    for line in lines:
        path = line.strip()
        if not path:
            continue
        suffix = Path(path).suffix.lower()
        artifacts.append(
            {
                "name": Path(path).name,
                "kind": _REMOTE_KIND_MAP.get(suffix, "file"),
                "path": path,
            }
        )
    return artifacts


def _known_ssh_hosts() -> list[str]:
    hosts: set[str] = set()
    for task in _parse_wes_files():
        if task.ssh:
            hosts.add(task.ssh)
    settings = _load_settings()
    for h in settings.get("ssh_hosts", []):
        hosts.add(h)
    return sorted(hosts)


def _parse_wes_files() -> list[TaskInfo]:
    wes_files = sorted(Path(".").glob("*.wes"))
    if not wes_files:
        return []

    cache = JobCache()
    try:
        cached = cache.get_all() or {}
    finally:
        pass

    tasks: list[TaskInfo] = []
    seen_names: set[str] = set()
    for wes_file in wes_files:
        try:
            for task_dict in parse_wes_file(str(wes_file)):
                if task_dict["name"] in seen_names:
                    continue
                seen_names.add(task_dict["name"])
                state = ""
                active_run_id = ""
                for run_id, data in cached.items():
                    if isinstance(data, dict) and data.get("task_name") == task_dict["name"]:
                        state = data.get("state", "")
                        active_run_id = run_id
                        break
                tasks.append(
                    TaskInfo(
                        name=task_dict["name"],
                        git_url=task_dict["git_url"],
                        branch=task_dict["branch"],
                        ssh=task_dict["ssh"],
                        job=task_dict["job"],
                        path=task_dict["path"],
                        run=task_dict["run"],
                        pre=task_dict["pre"],
                        post=task_dict["post"],
                        artifacts=task_dict["artifacts"],
                        cleanup=task_dict["cleanup"],
                        partition=task_dict["partition"],
                        cpus=task_dict["cpus"],
                        gpus=task_dict["gpus"],
                        memory=task_dict["memory"],
                        time=task_dict["time"],
                        nodelist=task_dict["nodelist"],
                        status=state,
                        run_id=active_run_id,
                    )
                )
        except Exception as e:
            log.error("Failed to parse %s: %s", wes_file, e)
    return tasks


# ──────────────────────────────────────────────
#  Task CRUD
# ──────────────────────────────────────────────


@router.get("/tasks", response_model=list[TaskInfo])
def list_tasks() -> list[TaskInfo]:
    return _parse_wes_files()


@router.get("/tasks/{name}", response_model=TaskInfo)
def get_task(name: str) -> TaskInfo:
    for task in _parse_wes_files():
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
    import shutil

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


# ──────────────────────────────────────────────
#  Job management
# ──────────────────────────────────────────────


def _get_ssh_user(ssh: str) -> str:
    try:
        from wes.remote.runner import SshRunner

        return SshRunner(ssh).get_user()
    except Exception:
        return ""


def _build_cache_index() -> dict[str, dict]:
    cache = JobCache()
    index: dict[str, dict] = {}
    for run_id, data in cache.get_all().items():
        if not isinstance(data, dict):
            continue
        for jid in data.get("jobs_ids", []):
            index[str(jid)] = data
        index[run_id] = data
    return index


@router.get("/jobs", response_model=list[JobSummary])
def list_jobs() -> list[JobSummary]:

    cache_idx = _build_cache_index()
    seen: set[str] = set()
    seen_namespaces: set[str] = set()
    jobs: list[JobSummary] = []

    for ssh in _known_ssh_hosts():
        user = _get_ssh_user(ssh)
        try:
            query = JobsQuery(ssh)
            squeue_jobs = query.get()
            recent_jobs = query.get_recent(user=user, hours=48) if user else []
        except Exception:
            continue

        for j in squeue_jobs:
            if user and j.user != user:
                continue
            if j.job_id in seen:
                continue
            seen.add(j.job_id)
            cached = cache_idx.get(j.job_id, {})
            if cached.get("run_id"):
                seen_namespaces.add(cached["run_id"])
            jobs.append(
                JobSummary(
                    job_id=j.job_id,
                    task_name=cached.get("task_name") or j.name,
                    state=j.state,
                    run_id=cached.get("run_id", ""),
                    jobs_ids=cached.get("jobs_ids", []),
                    git_url=cached.get("git_url", ""),
                    branch=cached.get("branch", ""),
                    ssh=ssh,
                    job=cached.get("job", ""),
                    partition=j.partition,
                    cpus=j.cpus,
                    gpus=cached.get("gpus", ""),
                    memory=j.memory,
                    time=j.time,
                    nodelist=j.nodes,
                )
            )

        for j in recent_jobs:
            if j.job_id in seen:
                continue
            seen.add(j.job_id)
            cached = cache_idx.get(j.job_id, {})
            if cached.get("run_id"):
                seen_namespaces.add(cached["run_id"])
            jobs.append(
                JobSummary(
                    job_id=j.job_id,
                    task_name=cached.get("task_name") or j.name,
                    state=j.state,
                    run_id=cached.get("run_id", ""),
                    jobs_ids=cached.get("jobs_ids", []),
                    git_url=cached.get("git_url", ""),
                    branch=cached.get("branch", ""),
                    ssh=ssh,
                    job=cached.get("job", ""),
                    partition=j.partition,
                    cpus=j.cpus,
                    gpus=cached.get("gpus", ""),
                    memory=j.memory,
                    time=j.time,
                    nodelist=j.nodes,
                )
            )

    for ssh in _known_ssh_hosts():
        try:
            scanner = JobScanner(ssh)
            for job in scanner.scan():
                if job.namespace in seen_namespaces:
                    continue
                seen_namespaces.add(job.namespace)
                jobs.append(
                    JobSummary(
                        job_id=job.namespace,
                        task_name=job.task.name,
                        state="COMPLETED",
                        run_id=job.namespace,
                        git_url=job.task.git_url,
                        branch=job.task.branch,
                        ssh=ssh,
                        partition=job.task.partition,
                        cpus=job.task.cpus,
                        gpus=job.task.gpus,
                        memory=job.task.memory,
                        time=job.task.time,
                        nodelist=job.task.nodelist,
                    )
                )
        except Exception:
            continue

    return jobs


@router.get("/jobs/{job_id}", response_model=JobSummary)
def get_job(job_id: str) -> JobSummary:
    cache_idx = _build_cache_index()

    for ssh in _known_ssh_hosts():
        try:
            query = JobsQuery(ssh)
            for j in query.get():
                if j.job_id == job_id:
                    cached = cache_idx.get(j.job_id, {})
                    return JobSummary(
                        job_id=j.job_id,
                        task_name=cached.get("task_name") or j.name,
                        state=j.state,
                        run_id=cached.get("run_id", ""),
                        jobs_ids=cached.get("jobs_ids", []),
                        git_url=cached.get("git_url", ""),
                        branch=cached.get("branch", ""),
                        ssh=ssh,
                        job=cached.get("job", ""),
                        partition=j.partition,
                        cpus=j.cpus,
                        gpus=cached.get("gpus", ""),
                        memory=j.memory,
                        time=j.time,
                        nodelist=j.nodes,
                    )
            user = _get_ssh_user(ssh)
            for j in query.get_recent(user=user, hours=48):
                if j.job_id == job_id:
                    cached = cache_idx.get(j.job_id, {})
                    return JobSummary(
                        job_id=j.job_id,
                        task_name=cached.get("task_name") or j.name,
                        state=j.state,
                        run_id=cached.get("run_id", ""),
                        jobs_ids=cached.get("jobs_ids", []),
                        git_url=cached.get("git_url", ""),
                        branch=cached.get("branch", ""),
                        ssh=ssh,
                        job=cached.get("job", ""),
                        partition=j.partition,
                        cpus=j.cpus,
                        gpus=cached.get("gpus", ""),
                        memory=j.memory,
                        time=j.time,
                        nodelist=j.nodes,
                    )
        except Exception:
            pass

    for config_path in RESULTS_DIR.glob(f"*_{job_id}/*_config.json"):
        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
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
        except Exception:
            continue

    raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")


@router.delete("/jobs/{job_id}")
def cancel_job(job_id: str) -> dict:
    messages: list[str] = []
    for ssh in _known_ssh_hosts():
        messages.extend(cancel_slurm_jobs(ssh, [job_id]))
    msg = "; ".join(messages) if messages else f"Job '{job_id}' not found on any host"
    return {"status": "ok", "message": msg}


@router.get("/jobs/{job_id}/logs", response_model=LogData)
def get_job_logs(job_id: str) -> LogData:
    run_dir = RESULTS_DIR / job_id
    return LogData(
        stdout=_read_file(run_dir / "job_output.txt"),
        stderr=_read_file(run_dir / "job_error.txt"),
        pre_run=_read_file(run_dir / "pre_run_output.txt"),
    )


@router.get("/jobs/{job_id}/remote-logs")
def get_job_remote_logs(job_id: str) -> dict[str, str]:
    cache_idx = _build_cache_index()
    cached = cache_idx.get(job_id, {})

    for ssh in _known_ssh_hosts():
        try:
            for j in JobsQuery(ssh).get():
                if j.job_id == job_id:
                    name = cached.get("task_name") or j.name
                    run_id = cached.get("run_id", "")
                    job_dir = f"{name}/{run_id}" if run_id else name
                    return {
                        "stdout": read_remote_log(ssh, f"{job_dir}/job_output.txt"),
                        "stderr": read_remote_log(ssh, f"{job_dir}/job_error.txt"),
                        "pre_run": read_remote_log(ssh, f"{job_dir}/pre_run_output.txt"),
                    }
        except Exception:
            pass

    config = _find_local_config(job_id)
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

    cache_idx = _build_cache_index()
    cached = cache_idx.get(job_id, {})

    for ssh in _known_ssh_hosts():
        try:
            for j in JobsQuery(ssh).get():
                if j.job_id == job_id:
                    name = cached.get("task_name") or j.name
                    runner = SshRunner(ssh)
                    ok, lines = runner.run_command(f"find {name} -type f 2>/dev/null")
                    if not ok:
                        return []
                    return _parse_remote_files(lines)
        except Exception:
            pass

    for config_path in RESULTS_DIR.glob(f"*_{job_id}/*_config.json"):
        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
            ssh = config.get("job", {}).get("ssh_config", "")
            task_name = config.get("task", {}).get("name", "")
            job_dir = f"{task_name}/{job_id}"
            runner = SshRunner(ssh)
            ok, lines = runner.run_command(f"find {job_dir} -type f 2>/dev/null")
            if not ok:
                return []
            return _parse_remote_files(lines)
        except Exception:
            continue
    return []


@router.get("/jobs/{job_id}/remote-artifacts/{path:path}")
def serve_job_remote_artifact(job_id: str, path: str):

    cache_idx = _build_cache_index()
    cached = cache_idx.get(job_id, {})

    ssh = cached.get("ssh", "")
    if ssh:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(path).suffix)
        item = SshItem(h_path=tmp.name, r_path=path, ssh_config=ssh)
        item.sync()
        if Path(tmp.name).exists():
            return FileResponse(tmp.name, filename=Path(path).name)

    for ssh in _known_ssh_hosts():
        try:
            for j in JobsQuery(ssh).get():
                if j.job_id == job_id:
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(path).suffix)
                    item = SshItem(h_path=tmp.name, r_path=path, ssh_config=ssh)
                    item.sync()
                    if Path(tmp.name).exists():
                        return FileResponse(tmp.name, filename=Path(path).name)
        except Exception:
            pass
    raise HTTPException(status_code=404, detail="Artifact not found")


@router.get("/jobs/{job_id}/remote-csv")
def get_job_remote_csv(job_id: str) -> ProgressData:

    cache_idx = _build_cache_index()
    cached = cache_idx.get(job_id, {})

    for ssh in _known_ssh_hosts():
        try:
            for j in JobsQuery(ssh).get():
                if j.job_id == job_id:
                    name = cached.get("task_name") or j.name
                    csv_paths = _ssh_run(
                        ssh, f"find {name} -name '*.csv' -type f 2>/dev/null | head -1"
                    )
                    if not csv_paths:
                        return ProgressData()
                    content_lines = _ssh_run(ssh, f"cat {csv_paths[0].strip()}")
                    if not content_lines:
                        return ProgressData()
                    content = "\n".join(content_lines)
                    reader = csv.reader(io.StringIO(content))
                    rows = list(reader)
                    if rows:
                        return ProgressData(columns=rows[0], rows=rows[1:])
        except Exception:
            pass
    return ProgressData()


# ──────────────────────────────────────────────
#  Legacy endpoints
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


# ──────────────────────────────────────────────
#  Cluster / nodes / slurm
# ──────────────────────────────────────────────


@router.get("/nodes", response_model=ClusterData)
def api_get_nodes(ssh: str = "") -> ClusterData:
    if not ssh:
        cache = JobCache()
        for data in (cache.get_all() or {}).values():
            if data.get("ssh"):
                ssh = data["ssh"]
                break
    if not ssh:
        return ClusterData(ssh="", error="No SSH host specified")
    try:
        nodes = get_nodes(ssh)
    except Exception as e:
        return ClusterData(ssh=ssh, error=str(e))
    return ClusterData(
        ssh=ssh,
        nodes=[
            NodeInfo(
                name=n["name"],
                partition=n["partition"],
                state=n["state"],
                cpus=n["cpus"],
                gpus=n["gpus"],
                memory=n["memory"],
                reason=n["reason"],
            )
            for n in nodes
        ],
    )


@router.get("/cluster")
def api_get_cluster(ssh: str = "") -> dict:
    if not ssh:
        cache = JobCache()
        for data in (cache.get_all() or {}).values():
            if data.get("ssh"):
                ssh = data["ssh"]
                break
    if not ssh:
        return {"ssh": "", "error": "No SSH host specified"}
    try:
        return get_cluster_data(ssh)
    except Exception as e:
        return {"ssh": ssh, "error": str(e)}


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
