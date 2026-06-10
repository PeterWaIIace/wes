#!/usr/bin/env python3
import sys
import os
import shutil
import subprocess
from typing import List
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
    def __init__(self, name: str, git_url: str, path: str, ssh_config : str = "", sbatch: str = "", command: str = ""):
        self.name = name
        self.ssh_config = ssh_config
        self.git_url = git_url
        self.path = path
        self.command = command
        self.sbatch = sbatch

    def ssh_rcp(self):
        result = subprocess.run(
            ['ssh', self.ssh_config, 'uptime'],
            capture_output=True, text=True
        )
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
            return sequence[list(sequence.keys())[0]] # get first and only task
        task = sequence[list(sequence.keys())[self.task_count]]
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
