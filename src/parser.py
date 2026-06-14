#!/usr/bin/env python3
import subprocess
import sys
import time
from enum import Enum
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .tasks import Task
from .states import State

class WESParser:
    def parse(self, config_file: str) -> list[Task]:
        """Parse WES configuration file and return list of Task objects."""
        with open(config_file, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        sequence = data.get("sequence", None)
        if sequence is None:
            return []
        if isinstance(sequence, list):
            tasks_data = []
            for item in sequence:
                for name, task_data in item.items():
                    task_data["name"] = name
                    tasks_data.append(task_data)
        elif isinstance(sequence, dict):
            tasks_data = []
            for name, task_data in sequence.items():
                task_data["name"] = name
                tasks_data.append(task_data)
        else:
            return []
        return [self.process_task(t) for t in tasks_data]

    def process_task(self, task_data: dict) -> Task:
        """Convert task data from WES format to Task object."""
        name = task_data.get("name", "Unnamed Task")
        git_url = task_data.get("git_url")
        path = task_data.get("path", ".")
        ssh_config = task_data.get("ssh", "")
        job = task_data.get("job", "")
        run = task_data.get("run", [])
        post = task_data.get("post", "")
        artifacts = task_data.get("artifacts", [])
        cleanup = task_data.get("cleanup", False)

        return Task(
            name=name,
            git_url=git_url,
            path=path,
            ssh_config=ssh_config,
            cleanup=cleanup,
            run=run,
            job=job,
            post=post,
            artifacts=artifacts,
        )

