from __future__ import annotations

from wes.jobs.job import JobInfo
from wes.remote.runner import _ssh_run


class JobsQuery:
    def __init__(self, ssh_config: str):
        self.ssh_config = ssh_config

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
