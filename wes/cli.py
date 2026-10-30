#!/usr/bin/env python3
from __future__ import annotations

import argparse
import signal
import time


def _launch(args: argparse.Namespace) -> None:
    from wes.engine import Engine

    engine = Engine()
    engine.start_jobs(task_file=args.config)


def _sync(args: argparse.Namespace) -> None:
    from wes.engine import Engine

    engine = Engine()
    engine.add_user(args.ssh)
    print(f"Starting sync for {args.ssh}...")
    engine.background_scan()

    def _shutdown(signum, frame):
        engine.run = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while engine.run:
            time.sleep(1)
    except KeyboardInterrupt:
        engine.run = False
    finally:
        print("\nShutting down...")
        engine.stop()


def _ls(args: argparse.Namespace) -> None:
    from wes.jobs.scanner import JobScanner

    for job in JobScanner(args.ssh).scan():
        print(job.namespace, job.job_name)


class WesParser:

    def __init__(self):
        self.parser = argparse.ArgumentParser(prog="wes")
        self.sub = self.parser.add_subparsers(dest="command")
        self.callbacks = {}

    def add_sub(self, command: str, help: str, callback, arguments: list):
        sub_parser = self.sub.add_parser(command, help=help)
        for argument in arguments or []:
            kwargs = {"help": argument["help"]}
            if argument.get("required"):
                kwargs["required"] = True
            sub_parser.add_argument(argument["argument"], **kwargs)
        self.callbacks[command] = callback

    def parse(self):
        args, remaining = self.parser.parse_known_args()

        callback = self.callbacks.get(args.command)
        if callback:
            callback(args)
        elif remaining and remaining[0].endswith(".wes"):
            args.config = remaining[0]
            _launch(args)
        else:
            self.parser.print_help()


def main() -> None:

    parser = WesParser()

    parser.add_sub(
        "dispatch",
        help="Dispatches tasks from a .wes config file and exit",
        callback=_launch,
        arguments=[
            {
                "argument": "config",
                "help": "Path to .wes config file",
            },
        ],
    )

    parser.add_sub(
        "sync",
        help="One time sync job status for an SSH config",
        callback=_sync,
        arguments=[
            {
                "argument": "--ssh",
                "help": "SSH config name",
                "required": True,
            },
        ],
    )

    parser.add_sub(
        "ls",
        help="List dirs SSH config",
        callback=_ls,
        arguments=[
            {
                "argument": "--ssh",
                "help": "SSH config name",
                "required": True,
            },
        ],
    )

    parser.parse()
