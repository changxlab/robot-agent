"""Shared helpers for robot tools: output formatting, subprocesses, errors."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from typing import Any

from . import config

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_UNAVAILABLE = 3


class ToolError(Exception):
    """A failure the agent should see as a clear one-line message."""

    def __init__(self, message: str, code: int = EXIT_ERROR):
        super().__init__(message)
        self.code = code


class Unavailable(ToolError):
    """Hardware, driver, or ROS interface is not reachable."""

    def __init__(self, message: str):
        super().__init__(message, EXIT_UNAVAILABLE)


def sim_tag() -> str:
    return "[SIM] " if config.is_sim() else ""


def header(title: str, real: bool = False) -> None:
    """Section header; tagged [SIM] in simulation mode unless the data is real."""
    print(f"\n## {'' if real else sim_tag()}{title}")


def kv(key: str, value: Any) -> None:
    print(f"  {key}: {value}")


def emit_json(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


def image_line(path: str) -> None:
    """Announce an image file. The web UI renders lines in this exact format."""
    print(f"IMAGE: {path}")


def video_line(path: str) -> None:
    """Announce an mp4/webm video under artifacts/; the web UI plays it inline."""
    print(f"VIDEO: {path}")


def pointcloud_line(path: str) -> None:
    """Announce a .pcd/.ply point cloud under artifacts/; the web UI shows it in a 3D viewer."""
    print(f"POINTCLOUD: {path}")


def run(cmd: list[str], timeout: float = 10.0) -> tuple[int, str]:
    """Run a command and return (exit code, combined output); never raises."""
    if not shutil.which(cmd[0]):
        return 127, f"{cmd[0]}: command not found"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout:.0f}s: {' '.join(cmd)}"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def fail(message: str, code: int = EXIT_ERROR) -> int:
    print(f"error: {message}", file=sys.stderr)
    return code


def clamp(value: float, limit: float) -> float:
    return max(-abs(limit), min(abs(limit), value))


def display_path(path) -> str:
    """``path`` relative to the project when it is inside it (as the web UI expects)."""
    try:
        return str(path.relative_to(config.PROJECT_DIR))
    except ValueError:
        return str(path)
