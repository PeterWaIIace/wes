from __future__ import annotations

import tempfile
from pathlib import Path

from wes.cluster import Cluster
from wes.jobs.job import SshItem
from wes.remote.runner import SshRunner


def get_cluster_data(ssh: str) -> dict:
    cluster = Cluster(ssh)
    nodes = cluster.get_nodes()
    jobs = cluster.get_jobs()
    capacity = cluster.get_capacity()
    return {
        "ssh": ssh,
        "nodes": [
            {
                "name": n.info.name,
                "partition": n.info.partition,
                "state": n.info.state,
                "cpus": n.info.cpus,
                "gpus": n.info.gpus,
                "memory": n.info.memory,
                "reason": n.info.reason,
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


def get_nodes(ssh: str) -> list[dict]:
    cluster = Cluster(ssh)
    nodes = cluster.get_nodes()
    return [
        {
            "name": n.info.name,
            "partition": n.info.partition,
            "state": n.info.state,
            "cpus": n.info.cpus,
            "gpus": n.info.gpus,
            "memory": n.info.memory,
            "reason": n.info.reason,
        }
        for n in nodes
    ]


def cancel_slurm_jobs(ssh: str, job_ids: list[str]) -> list[str]:
    runner = SshRunner(ssh)
    messages: list[str] = []
    for jid in job_ids:
        ok, _ = runner.run_command(f"scancel {jid}")
        if ok:
            messages.append(f"cancelled slurm job {jid}")
    return messages


def remove_remote_dir(ssh: str, path: str) -> bool:
    runner = SshRunner(ssh)
    ok, _ = runner.run_command(f"rm -rf {path}")
    return ok


def check_jobs_alive(ssh: str, job_ids: list[str]) -> bool:
    from wes.jobs.query import JobsQuery

    if not job_ids:
        return False
    alive_jobs = JobsQuery(ssh).get()
    alive_ids = {j.job_id for j in alive_jobs}
    return any(jid in alive_ids for jid in job_ids)


def read_remote_log(ssh: str, path: str) -> str:
    runner = SshRunner(ssh)
    ok, lines = runner.run_command(f"cat {path}")
    return "\n".join(lines) if ok else ""


def list_remote_files(ssh: str, directory: str) -> list[str]:
    runner = SshRunner(ssh)
    ok, lines = runner.run_command(f"find {directory} -type f 2>/dev/null")
    return lines if ok else []


def get_remote_file(ssh: str, path: str) -> str | None:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(path).suffix)
    item = SshItem(h_path=tmp.name, r_path=path, ssh_config=ssh)
    item.sync()
    if Path(tmp.name).exists():
        return tmp.name
    return None
