#!/usr/bin/env python3
from __future__ import annotations

import argparse
import signal
import time


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "web.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="wes")
    sub = parser.add_subparsers(dest="command")

    launch_p = sub.add_parser("launch", help="Launch tasks from a .wes config file and exit")
    launch_p.add_argument("config", help="Path to .wes config file")

    sync_p = sub.add_parser("sync", help="Continuously sync job status for an SSH config")
    sync_p.add_argument("--ssh", required=True, help="SSH config name")

    serve_p = sub.add_parser("serve", help="Start the web interface")
    serve_p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    serve_p.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    serve_p.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    args, remaining = parser.parse_known_args()

    if args.command == "serve":
        _serve(args)
    elif args.command == "launch":
        _launch(args)
    elif args.command == "sync":
        _sync(args)
    elif remaining and remaining[0].endswith(".wes"):
        args.config = remaining[0]
        _launch(args)
    else:
        parser.print_help()
