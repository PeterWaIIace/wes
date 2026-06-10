#!/usr/bin/env python3
import sys
import os
import shutil
import subprocess
from typing import List
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse
import yaml

prejob = """
git clone {git_urlr}
# preactions
{actions}
"""

postjob = """
scp {ssh_target} {to_path}
"""


class Task:
    def __init__(self, name: str, git_url: str, path: str, pre : str = "", post : str = "", ssh_config : str = "", sbatch: str = "", command: str = ""):
        self.name = name
        self.ssh_config = ssh_config
        self.git_url = git_url
        self.path = path
        self.command = command
        self.sbatch = sbatch
        self.pre = pre
        self.post = post
        self.cleanup_git = True

    def execute_remote_job(self):
        self.__clone_repository()
        self.__execurte_pre_script()
        self.__execture_job()
        self.__execute_post_script()
        if self.cleanup_git:
            self.__cleanup_repository()

    def __cleanup_repository(self):
        repo_name = self.git_url.split('/')[-1].replace('.git', '')
        result = subprocess.run(
            ["ssh", self.ssh_config, "rm", "-rf", repo_name],
            capture_output=True, text=True
        )
        if result.stdout:
            print(result.stdout, end='')
        if result.returncode != 0:
            print(result.stderr, end='', file=sys.stderr)

    def __clone_repository(self):
        result = subprocess.run(
            ["ssh", self.ssh_config, "git", "clone", self.git_url],
            capture_output=True, text=True
        )
        if result.stdout:
            print(result.stdout, end='')
        if result.returncode != 0:
            print(result.stderr, end='', file=sys.stderr)

    def __execurte_pre_script(self):
        pre_script = Path(self.pre).read_text(encoding="utf-8")
        result = subprocess.run(
            ["ssh", self.ssh_config, "bash -s"],
            input=pre_script,          # sends local script content to remote bash stdin
            text=True,
            capture_output=True,
            check=True,
        )

    def __execute_post_script(self):
        post_script = Path(self.post).read_text(encoding="utf-8")
        result = subprocess.run(
            ["ssh", self.ssh_config, "bash -s"],
            input=post_script,          # sends local script content to remote bash stdin
            text=True,
            capture_output=True,
            check=True,
        )

    def __execture_job(self):
        result = subprocess.run(
            ['ssh', self.ssh_config, 'sbatch', '--parsable', self.sbatch],
            capture_output=True, text=True
        )
        raw = result.stdout.strip()
        job_id = raw.split(";")[0]
        print(f"Submitted job with ID: {job_id}")
        if result.stdout:
            print(result.stdout, end='')
        if result.returncode != 0:
            print(result.stderr, end='', file=sys.stderr)


class WESParser:

    def __init__(self):
        self.file_to_process = ""
        self.task_count = 0

    def get_next_task(self, data: dict) -> dict:
        sequence = data.get('sequence', None)
        if sequence is None:
            name = list(sequence.keys())[0]
            task = sequence[name]
            task["name"] = name
            return task # get first and only task
        name = list(sequence.keys())[self.task_count]
        task = sequence[name]
        task["name"] = name
        return task
        
    def parse(self, config_file: str) -> List[Task]:
        """Parse WES configuration file and return list of Task objects."""
        tasks = []
        with open(config_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {} 
            task = self.get_next_task(data)
            tasks.append(self.process_task(task))
        return tasks

    def process_task(self, task_data: dict) -> Task:
        """Convert task data from WES format to Task object."""
        name = task_data.get('name', 'Unnamed Task')
        git_url = task_data.get('git_url')
        path = task_data.get('path', '.')
        command = task_data.get('command', '')
        ssh_config = task_data.get('ssh', '')
        pre = task_data.get('pre', '')
        post = task_data.get('post', '')

        return Task(name=name, git_url=git_url, path=path, ssh_config=ssh_config, command=command)


def main():
    """Main entry point."""
    # Load environment variables from .env file
    load_dotenv()
    
    config_file = sys.argv[1] if len(sys.argv) > 1 else "tasks.wes"
    
    wes = WESParser()
    tasks = wes.parse(config_file)
    
    for task in tasks:
        print(f"\nProcessing sequence: {task.name} ({task.git_url})")
        task.ssh_rcp()


if __name__ == "__main__":
    main()
