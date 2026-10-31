#!/usr/bin/env python3
from __future__ import annotations
from wes.engine import Engine
from wes.jobs.scanner import JobScanner
from wes.jobs.job import SshItem

import argparse
import signal
import time

class WES:

    def __init__(self, ssh : str | None = None):
        self.ssh = ssh # if none then lazy init

    def set_ssh(self, ssh):
        self.ssh = ssh

    def dispatch(self, config) -> None:
        engine = Engine()
        engine.start_jobs(task_file=config)

    def pull(self, pull_dir) -> list:
        SshItem(pull_dir, pull_dir, self.ssh).sync()

    def sync(self) -> None:
        engine = Engine()
        engine.add_user(self.ssh)
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

    def ls(self, lsdir=None, recursive=False, depth=None) -> list:
        return JobScanner(self.ssh).list_dir(lsdir, recursive=recursive, depth=depth)

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
            if "action" in argument:
                kwargs["action"] = argument["action"]
            sub_parser.add_argument(argument["argument"], **kwargs)
        self.callbacks[command] = callback

    def parse(self):
        args, remaining = self.parser.parse_known_args()

        callback = self.callbacks.get(args.command)
        if callback:
            result = callback(args)
            print(result)
        elif remaining and remaining[0].endswith(".wes"):
            WES().dispatch(remaining[0])
        else:
            self.parser.print_help()


def main() -> None:

    wes = WES()
    parser = WesParser()

    parser.add_sub(
        "dispatch",
        help="Dispatches tasks from a .wes config file and exit",
        callback=lambda args: wes.dispatch(args.config),
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
        callback= lambda args : [wes.set_ssh(args.ssh), wes.sync()][1],
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
        help="List entries at a remote path",
        callback=lambda args: [wes.set_ssh(args.ssh), wes.ls(lsdir=args.path, recursive=args.recursive, depth=args.depth)][1],
        arguments=[
            {
                "argument": "--ssh",
                "help": "SSH config name",
                "required": True,
            },
            {
                "argument": "--path",
                "help": "Path where command should be executed",
            },
            {
                "argument": "--depth",
                "help": "Max depth for recursive listing (default: unlimited)",
            },
            {
                "argument": "--recursive",
                "help": "List directories recursively",
                "action": "store_true",
            },
        ],
    )

    parser.add_sub(
        "pull",
        help="Pull a directory from the remote to the same local path",
        callback=lambda args: [wes.set_ssh(args.ssh), wes.pull(args.path)][1],
        arguments=[
            {
                "argument": "--ssh",
                "help": "SSH config name",
                "required": True,
            },
            {
                "argument": "--path",
                "help": "Remote directory to pull",
                "required": True,
            },
        ],
    )

    parser.parse()
