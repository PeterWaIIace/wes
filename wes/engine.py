from __future__ import annotations
from wes.parser import WESParser
from wes.jobs.job import Job

class User:

    def __init__(self, name: str):
        self.name = name
        self.ssh = None

class Engine:
    def __init__(self):
        pass 
    
    def run(self):
        wes = WESParser()
        new_tasks = wes.parse("task.wes")

        jobs = []
        for task in new_tasks:
            jobs.append(Job(task, task.ssh_config))

        for job in jobs:
            job.upload_scripts()
            job.execute_job()

if __name__ == "__main__":
    engine = Engine()
    engine.run()
