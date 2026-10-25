from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from roadlog.settings import DASHBOARD_PORT, ROUTER_PORT, SERVICE_PORTS


def serve(app, port: int) -> None:
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


def run_device(args: argparse.Namespace) -> None:
    from roadlog.twin.device import main

    main()


def run_router(args: argparse.Namespace) -> None:
    from roadlog.router import create_app

    serve(create_app(), args.port or ROUTER_PORT)


def run_service(args: argparse.Namespace) -> None:
    from importlib import import_module

    module = import_module(f"roadlog.services.{args.name}")
    serve(module.create_app(), args.port or SERVICE_PORTS[args.name])


def run_dashboard(args: argparse.Namespace) -> None:
    from roadlog.dashboard.app import create_app

    serve(create_app(), args.port or DASHBOARD_PORT)


def run_record(args: argparse.Namespace) -> None:
    from roadlog.recorder import record

    record(args.seconds, args.out)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="road-log", description="Run a part of the road-log fleet.")
    commands = root.add_subparsers(dest="command", required=True, metavar="command")
    commands.add_parser("device", help="run one simulated tachograph").set_defaults(run=run_device)
    router = commands.add_parser("router", help="route MQTT messages to the services")
    router.set_defaults(run=run_router)
    service = commands.add_parser("service", help="run one microservice")
    service.add_argument("name", choices=sorted(SERVICE_PORTS))
    service.set_defaults(run=run_service)
    dashboard = commands.add_parser("dashboard", help="serve the live fleet dashboard")
    dashboard.set_defaults(run=run_dashboard)
    recorder = commands.add_parser("record", help="record live fleet traffic for replay")
    recorder.add_argument("--seconds", type=float, default=900)
    recorder.add_argument("--out", type=Path, default=Path("recording.json"))
    recorder.set_defaults(run=run_record)
    for command in (router, service, dashboard):
        command.add_argument("--port", type=int)
    return root


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = parser().parse_args(argv)
    args.run(args)
