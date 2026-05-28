#!/usr/bin/env python3
import json
import sys
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse


class Task:
    def __init__(self, git_url: str, path: str, command: str):
        self.git_url = git_url
        self.path = path
        self.command = command


def read_config(config_file: str) -> List[Task]:
    """Read task configuration from JSON file."""
    try:
        with open(config_file, 'r') as f:
            data = json.load(f)
        
        tasks = []
        for task_data in data.get('tasks', []):
            task = Task(
                git_url=task_data['git_url'],
                path=task_data['path'],
                command=task_data['command']
            )
            tasks.append(task)
        return tasks
    except Exception as e:
        print(f"Error reading config: {e}")
        sys.exit(1)


def extract_repo_name(url: str) -> str:
    """Extract repository name from git URL."""
    name = url.split('/')[-1]
    if name.endswith('.git'):
        name = name[:-4]
    return name


def inject_credentials(git_url: str) -> str:
    """Inject git credentials into HTTPS URL if available in .env."""
    username = os.getenv('GIT_USERNAME')
    password = os.getenv('GIT_PASSWORD')
    
    if not username or not password:
        return git_url
    
    # Parse the URL
    parsed = urlparse(git_url)
    
    # Inject credentials
    netloc = f"{username}:{password}@{parsed.netloc}"
    
    # Reconstruct URL with credentials
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def execute_task(task: Task) -> None:
    """Execute a single task: clone repo, run command, clean up."""
    repo_name = extract_repo_name(task.git_url)
    repo_path = f"/tmp/{repo_name}"
    
    try:
        # Clean up if repo already exists
        if os.path.exists(repo_path):
            print(f"Removing existing directory: {repo_path}")
            shutil.rmtree(repo_path)
        
        # Prepare git URL with credentials if using HTTPS
        git_url = task.git_url
        if git_url.startswith("https://"):
            git_url = inject_credentials(git_url)
        
        # Clone the repository
        print(f"Cloning repository from: {task.git_url}")
        result = subprocess.run(
            ["git", "clone", git_url, repo_path],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise Exception(f"Failed to clone repository: {result.stderr}")
        
        # Build the work directory path
        work_dir = os.path.join(repo_path, task.path)
        
        if not os.path.exists(work_dir):
            raise Exception(f"Path {task.path} does not exist in repository")
        
        # Execute the command
        print(f"Executing command in {work_dir}: {task.command}")
        result = subprocess.run(
            task.command,
            shell=True,
            cwd=work_dir,
            capture_output=True,
            text=True
        )
        
        print("STDOUT:")
        print(result.stdout)
        
        if result.stderr:
            print("STDERR:")
            print(result.stderr)
        
        if result.returncode != 0:
            print(f"Command failed with status: {result.returncode}")
        
        # Clean up the repository
        print(f"Cleaning up repository: {repo_path}")
        shutil.rmtree(repo_path)
        
    except Exception as e:
        print(f"Error executing task: {e}")
        # Try to clean up even if error occurred
        if os.path.exists(repo_path):
            shutil.rmtree(repo_path)


def main():
    """Main entry point."""
    # Load environment variables from .env file
    load_dotenv()
    
    config_file = sys.argv[1] if len(sys.argv) > 1 else "tasks.json"
    
    tasks = read_config(config_file)
    
    for task in tasks:
        print(f"\nProcessing task: {task.git_url}")
        execute_task(task)


if __name__ == "__main__":
    main()
