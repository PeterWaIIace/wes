#!/usr/bin/env python3
from __future__ import annotations

import argparse


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "web.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def _run(args: argparse.Namespace) -> None:
    from wes.engine import Engine

    engine = Engine()
    engine.start_jobs()


def main() -> None:
    parser = argparse.ArgumentParser(prog="wes")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run a .wes config file")
    run_p.add_argument("config", help="Path to .wes config file")

    serve_p = sub.add_parser("serve", help="Start the web interface")
    serve_p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    serve_p.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    serve_p.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    args, remaining = parser.parse_known_args()

    if args.command == "serve":
        _serve(args)
    elif args.command == "run":
        _run(args)
    elif remaining and remaining[0].endswith(".wes"):
        args.config = remaining[0]
        _run(args)
    else:
        parser.print_help()
