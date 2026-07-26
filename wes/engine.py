from __future__ import annotations
from wes.parser import WESParser
from wes.jobs.job import Job, JobInfo
from wes.jobs.scanner import JobScanner
from wes.jobs.query import JobsQuery
from wes.remote.runner import SshRunner

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

    def start_jobs(self):
        wes = WESParser()
        new_tasks = wes.parse("task.wes")

        for task in new_tasks:
            self.current_users[task.ssh_config] = User(task.ssh_config)
            self.job_scanners[task.ssh_config] = JobScanner(task.ssh_config)
            job = Job(task, task.ssh_config)
            self.jobs[job.namespace] = job

        for job in self.jobs.values():
            job.upload_scripts()
            job.execute_job()

    def sync_jobs(self):
        for job in self.jobs.values():
            job.sync()

    def scan_jobs(self):
        for ssh_conf, scanner in self.job_scanners.items():
            jobs = scanner.scan()
            for job in jobs:
                if job.namespace not in self.jobs.keys():
                    self.jobs[job.namespace] = job

    def get_jobs(self) -> list[Job]:
        jobs = []
        for ssh_conf, user in self.current_users.items():
            jobs += JobsQuery(ssh_conf).get()
        return jobs

    def get_user_jobs(self) -> list[Job]:
        user_jobs = []
        for ssh_conf, user in self.current_users.items():
            for job in self.get_jobs():
                if user.name == job.user:
                    user_jobs.append(job)
        return user_jobs

if __name__ == "__main__":
    engine = Engine()
    engine.start_jobs()
    engine.scan_jobs()
    print("=====================")
    print("engine.get_jobs():", len(engine.jobs))
    engine.sync_jobs()
    print(engine.get_user_jobs())
