from __future__ import annotations

from wes.jobs.job import JobInfo
from wes.remote.runner import _ssh_run


class JobsQuery:
    def __init__(self, ssh_config: str):
        self.ssh_config = ssh_config

    def has_alive_jobs(self, job_ids: list[str]) -> bool:
        if not job_ids:
            return False
        alive = {j.job_id for j in self.get()}
        return any(jid in alive for jid in job_ids)

    def get(self) -> list[JobInfo]:
        fmt = "%i|%u|%j|%T|%M|%N|%P|%R|%C|%m"
        lines = _ssh_run(self.ssh_config, f"squeue -o '{fmt}'")
        jobs: list[JobInfo] = []
        for line in lines:
            parts = line.split("|")
            if len(parts) < 10:
                continue
            jobs.append(
                JobInfo(
                    job_id=parts[0].strip(),
                    user=parts[1].strip(),
                    name=parts[2].strip(),
                    state=parts[3].strip(),
                    time=parts[4].strip(),
                    nodes=parts[5].strip(),
                    partition=parts[6].strip(),
                    reason=parts[7].strip(),
                    cpus=parts[8].strip(),
                    memory=parts[9].strip(),
                )
            )
        return jobs

    def get_recent(self, user: str = "", hours: int = 24) -> list[JobInfo]:
        fmt = "%i|%u|%j|%T|%M|%N|%P|%R|%C|%m"
        user_flag = f"-u {user}" if user else ""
        lines = _ssh_run(
            self.ssh_config,
            f"sacct {user_flag} --hours={hours} -o '{fmt}' --noheader",
        )
        jobs: list[JobInfo] = []
        for line in lines:
            parts = line.split("|")
            if len(parts) < 10:
                continue
            job_id = parts[0].strip()
            if "." in job_id:
                continue
            state = parts[3].strip()
            if state in ("PENDING", "RUNNING", "SUSPENDED", "COMPLETING"):
                continue
            jobs.append(
                JobInfo(
                    job_id=job_id,
                    user=parts[1].strip(),
                    name=parts[2].strip(),
                    state=state,
                    time=parts[4].strip(),
                    nodes=parts[5].strip(),
                    partition=parts[6].strip(),
                    reason=parts[7].strip(),
                    cpus=parts[8].strip(),
                    memory=parts[9].strip(),
                )
            )
        return jobs
