from __future__ import annotations

import os
import signal
import time

import yaml

from wes.cluster import Cluster
from wes.clusters.node import NodeCapacity
from wes.engine import Engine
from wes.jobs.job import JobInfo, SshItem, STATUS_FILENAME
from wes.jobs.scanner import JobScanner
from wes.remote.runner import SshRunner

class WES:
    def __init__(self, ssh: str | None = None):
        self.ssh = ssh
        self.cluster = Cluster(ssh) if ssh else None

    def set_ssh(self, ssh):
        self.ssh = ssh
        self.cluster = Cluster(ssh)

    def get_nodes(self) -> list:
        return [n.info for n in self.cluster.get_nodes()]

    def get_jobs(self) -> list[JobInfo]:
        return self.cluster.get_jobs()

    def get_capacity(self) -> list[NodeCapacity]:
        return self.cluster.get_capacity()

    def dispatch(self, config) -> None:
        engine = Engine()
        engine.start_jobs(task_file=config)

    def get_job_status(self):
        pass

    def pull(self, pull_dir) -> list:
        SshItem(pull_dir, pull_dir, self.ssh).sync()

    def sync(self) -> None:
        engine = Engine()
        engine.add_user(self.ssh)
        engine.background_scan()

        def _shutdown(signum, frame):
            engine.run = False

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        try:
            while engine.run:
                time.sleep(1)
        except KeyboardInterrupt:
            engine.run = False
        finally:
            print("\nShutting down...")
            engine.stop()

    def ls(self, lsdir=None, recursive=False, depth=None) -> list:
        return JobScanner(self.ssh).list_dir(lsdir, recursive=recursive, depth=depth)

    def check(self, rootdir="."):
        statuses = []
        dirs_to_discover = [rootdir]
        while dirs_to_discover:
            current_dir = dirs_to_discover.pop()
            results = JobScanner(self.ssh).list_dir(current_dir, recursive=False, depth=1)

            status_paths = [p for p in results if os.path.basename(p) == STATUS_FILENAME]
            if status_paths:
                # current_dir directly holds wes.status: it is a job dir, read
                # the status and do not descend into it (find -prune semantics)
                for path in status_paths:
                    ok, lines = SshRunner(self.ssh).run_command(f"cat {path}")
                    if ok and lines:
                        data = yaml.safe_load("\n".join(lines))
                        if data:
                            statuses.append(data)
                continue

            for path in results:
                if any(part.startswith(".") and len(part) > 1 for part in path.split("/")):
                    continue
                dirs_to_discover.append(path)
        return statuses