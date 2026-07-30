from __future__ import annotations

import time
from threading import Lock, Thread

from wes.jobs.job import Job
from wes.jobs.query import JobsQuery
from wes.jobs.scanner import JobScanner
from wes.parser import WESParser
from wes.remote.runner import SshRunner
from wes.utils import thread_safe


class User:
    def __init__(self, ssh_config: str):
        self.ssh_config = ssh_config
        self.runner = SshRunner(ssh_config)
        self.name = self.runner.get_user()


class Engine:
    def __init__(self):
        self.current_users = {}
        self.job_scanners = {}
        self.jobs = {}
        self.run = True
        self._cleaned: set[str] = set()

        self.engine_lock = Lock()
        self.sync_thread = Thread(target=self.__sync_thread)

    def background_scan(self):
        self.sync_thread.start()

    def __sync_thread(self):
        try:
            while self.run:
                self.sync_jobs()
                self.cleanup_jobs()
                self.scan_jobs()
                self.scan_slurm_info()
        finally:
            print("Sync thread exiting...")

    @thread_safe("engine_lock")
    def add_user(self, ssh_config: str):
        self.current_users[ssh_config] = User(ssh_config)
        self.job_scanners[ssh_config] = JobScanner(ssh_config)

    @thread_safe("engine_lock")
    def start_jobs(self, task_file: str = "task.wes"):
        wes = WESParser()
        new_tasks = wes.parse(task_file)

        for task in new_tasks:
            self.current_users[task.ssh_config] = User(task.ssh_config)
            self.job_scanners[task.ssh_config] = JobScanner(task.ssh_config)
            job = Job(task, task.ssh_config)
            self.jobs[job.namespace] = job

        for job in self.jobs.values():
            job.upload_scripts()
            job.execute_job()

    @thread_safe("engine_lock")
    def sync_jobs(self):
        for job in self.jobs.values():
            job.sync()

    @thread_safe("engine_lock")
    def cleanup_jobs(self):
        for ns, job in list(self.jobs.items()):
            if ns in self._cleaned:
                continue
            if not job.info or not job.task.cleanup_git:
                continue
            if job.info.state in ("COMPLETED", "FAILED", "CANCELLED"):
                print(f"Cleaning up remote files for {job.job_name} ({job.info.state})")
                job.cleanup()
                self._cleaned.add(ns)

    @thread_safe("engine_lock")
    def scan_jobs(self):
        for _ssh_conf, scanner in self.job_scanners.items():
            jobs = scanner.scan()
            for job in jobs:
                if job.namespace not in self.jobs.keys():
                    self.jobs[job.namespace] = job

    @thread_safe("engine_lock")
    def scan_slurm_info(self):
        infos = []
        for ssh_conf, _user in self.current_users.items():
            infos += JobsQuery(ssh_conf).get()

        infos = {info.name: info for info in infos}
        for job in self.jobs.values():
            if job.job_name in infos:
                job.set_info(infos[job.job_name])
                print(job.job_name, "info set:", job.info)

    @thread_safe("engine_lock")
    def get_infos(self) -> list[Job]:
        jobs = []
        for ssh_conf, _user in self.current_users.items():
            jobs += JobsQuery(ssh_conf).get()
        return jobs

    @thread_safe("engine_lock")
    def get_user_infos(self) -> list[Job]:
        user_jobs = []
        for _ssh_conf, user in self.current_users.items():
            for job in self.get_infos():
                if user.name == job.user:
                    user_jobs.append(job)
        return user_jobs

    @thread_safe("engine_lock")
    def get_user_jobs(self) -> list[Job]:
        return list(self.jobs.values())

    @thread_safe("engine_lock")
    def stop(self):
        self.run = False
        print("stopping engine...")
        self.sync_thread.join()
        print("engine stopped.")


if __name__ == "__main__":
    engine = Engine()
    engine.add_user("hpc")
    engine.start_jobs()
    t = 0
    while t < 10:
        time.sleep(1)
        t += 1
    engine.stop()
