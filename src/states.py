#!/usr/bin/env python3
import subprocess
import sys
import time
from enum import Enum
from pathlib import Path

import yaml
from dotenv import load_dotenv


class State(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETING = "COMPLETING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
