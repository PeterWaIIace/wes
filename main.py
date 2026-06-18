#!/usr/bin/env python3
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.parser import WESParser
from src.states import State


def main():
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
