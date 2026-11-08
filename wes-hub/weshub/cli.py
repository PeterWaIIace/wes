from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from weshub.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="wes-hub", description="WES scheduling server")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Start the wes-hub server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8420)
    serve.add_argument("--data-dir", default="./data")
    serve.add_argument("--poll-interval", type=float, default=15.0)
    serve.add_argument("--scheduler-interval", type=float, default=30.0)
    serve.add_argument("--discover-interval", type=float, default=60.0)
    serve.add_argument(
        "--mock", action="store_true", help="Run against a local mock cluster (no ssh/SLURM)"
    )

    disc = sub.add_parser("discover", help="Run job discovery once against a cluster and exit")
    disc.add_argument("--ssh", required=True, help="SSH config name (see ~/.ssh/config)")
    disc.add_argument(
        "--path",
        default="",
        help="Remote dir to search recursively for wes.status files "
        "(non-hidden entries only, no descent past a found status file). "
        "Default: scan for *_config.json under the remote workdir",
    )
    disc.add_argument("--data-dir", default="./data")
    disc.add_argument(
        "--mock", action="store_true", help="Run against a local mock cluster (no ssh/SLURM)"
    )

    args = parser.parse_args()
    if args.command == "discover":
        _discover_once(args)
        return
    if args.command != "serve":
        parser.print_help()
        return

    settings = Settings(
        host=args.host,
        port=args.port,
        data_dir=Path(os.path.abspath(args.data_dir)),
        poll_interval=args.poll_interval,
        scheduler_interval=args.scheduler_interval,
        discover_interval=args.discover_interval,
    )
    settings.ensure_dirs()

    if args.mock:
        from weshub import mock

        mock.setup(settings)
        mock.activate()

    # WES resolves the artifact "results/..." prefix and job script paths
    # against the process CWD, so the server lives inside the data dir.
    os.chdir(settings.data_dir)

    from weshub.app import create_app

    app = create_app(settings)

    if args.mock:
        from weshub import api as api_mod

        pipeline = mock.seed_demo_pipeline(api_mod.get_hub())
        if pipeline:
            print(f"[mock] seeded demo pipeline 'mock-demo' (id={pipeline['id']})")
            print(
                f"    dispatch it from the UI or via:"
                f" curl -X POST localhost:{settings.port}/api/pipelines/{pipeline['id']}/dispatch"
            )

    uvicorn.run(app, host=settings.host, port=settings.port)


def _discover_once(args) -> None:
    settings = Settings(data_dir=Path(os.path.abspath(args.data_dir)))
    settings.ensure_dirs()

    if args.mock:
        from weshub import mock

        mock.setup(settings)
        mock.activate()

    # WES resolves the artifact "results/..." prefix against the process CWD
    os.chdir(settings.data_dir)

    from weshub.manager import Hub

    hub = Hub(settings)
    try:
        adopted = hub.discover(args.ssh, args.path or None)
    finally:
        hub.stop()

    where = f"{args.ssh}:{args.path or '.'}"
    if adopted:
        print(f"adopted {len(adopted)} job(s) from {where}")
        for ns in adopted:
            print(f"  {ns}")
    else:
        print(f"no new jobs found on {where}")


if __name__ == "__main__":
    main()
