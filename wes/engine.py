from __future__ import annotations
from wes.parser import WESParser
from wes.jobs.job import Job
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
    
    def run(self):
        wes = WESParser()
        new_tasks = wes.parse("task.wes")

        jobs = []
        for task in new_tasks:
            self.current_users[task.ssh_config] = User(task.ssh_config)
            jobs.append(Job(task, task.ssh_config))

        for job in jobs:
            job.upload_scripts()
            job.execute_job()

    def get_jobs(self) -> list[Job]:
        for ssh_conf, user in self.current_users.items():
            print(user)
            return JobsQuery(ssh_conf).get()

    def get_user_jobs(self) -> list[Job]:
        user_jobs = []
        for ssh_conf, user in self.current_users.items():
            for job in self.get_jobs():
                if user.name == job.user:
                    user_jobs.append(job)
        return user_jobs

if __name__ == "__main__":
    engine = Engine()
    engine.run()
    print(engine.get_user_jobs())
