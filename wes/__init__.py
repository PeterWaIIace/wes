from __future__ import annotations

import signal
import time

from wes.cluster import Cluster
from wes.clusters.node import NodeCapacity
from wes.engine import Engine
from wes.jobs.job import JobInfo, SshItem
from wes.jobs.scanner import JobScanner


class WES:
    def __init__(self, ssh: str | None = None):
        self.ssh = ssh
        self.cluster = Cluster(ssh) if ssh else None

    def get_nodes(self) -> list:
        return [n.info for n in self.cluster.get_nodes()]

    def get_jobs(self) -> list[JobInfo]:
        return self.cluster.get_jobs()

    def get_capacity(self) -> list[NodeCapacity]:
        return self.cluster.get_capacity()

    def set_ssh(self, ssh):
        self.ssh = ssh
        self.cluster = Cluster(ssh)

    def dispatch(self, config) -> None:
        engine = Engine()
        engine.start_jobs(task_file=config)

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
