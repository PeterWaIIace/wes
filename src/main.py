#!/usr/bin/env python3
import subprocess
import sys
import time
from enum import Enum
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .parser import WESParser
from .tasks import Task
from .states import State

def main():
    """Main entry point."""
    load_dotenv()

    config_file = sys.argv[1] if len(sys.argv) > 1 else "tasks.wes"

    wes = WESParser()
    tasks = wes.parse(config_file)

    for task in tasks:
        print(f"\nProcessing sequence: {task.name}")
        task.execute()
        while task.status == State.RUNNING:
            time.sleep(10)
            task.execute()


if __name__ == "__main__":
    main()
