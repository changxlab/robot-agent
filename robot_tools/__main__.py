"""./robot command-line entry point."""

from __future__ import annotations

import argparse
import sys

from . import arm, base, camera, logs, mapping, status, survey, trajectory
from .common import EXIT_ERROR, ToolError, fail, sim_tag


def estop(args) -> int:
    """Stop every actuator. Each subsystem is attempted even if another fails."""
    failures = []
    try:
        base.send("stop")
        print(f"{sim_tag()}B2: stop-move sent")
    except ToolError as exc:
        failures.append("base")
        print(f"B2: could not send stop - {exc}")
    try:
        arm.stop()
    except ToolError as exc:
        failures.append("arm")
        print(f"arm: could not send stop - {exc}")
    return EXIT_ERROR if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="./robot",
        description="Robot tools for the B2 quadruped, Piper arm, cameras, logs and mapping.",
    )
    sub = parser.add_subparsers(dest="tool", required=True)
    status.register(sub)
    logs.register(sub)
    camera.register(sub)
    arm.register(sub)
    trajectory.register(sub)
    survey.register(sub)
    base.register(sub)
    mapping.register(sub)
    p = sub.add_parser("estop", help="stop the base and emergency-stop the arm")
    p.set_defaults(func=estop)
    return parser


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(line_buffering=True)
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ToolError as exc:
        return fail(str(exc), exc.code)
    except KeyboardInterrupt:
        return fail("interrupted", 130)


if __name__ == "__main__":
    sys.exit(main())
