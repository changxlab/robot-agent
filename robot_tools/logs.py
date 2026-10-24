"""Inspect ROS, system, kernel, and robot-tool logs."""

from __future__ import annotations

import re
import time
from pathlib import Path

from . import config
from .common import ToolError, header, run

LEVEL_PATTERNS = {
    "error": re.compile(r"\b(ERROR|FATAL|CRITICAL|Traceback|exception|fail(ed|ure)?)\b", re.I),
    "warning": re.compile(r"\b(WARN(ING)?|ERROR|FATAL|CRITICAL|Traceback|exception|fail(ed|ure)?)\b",
                          re.I),
}
JOURNAL_PRIORITY = {"error": "err", "warning": "warning", "all": "debug"}
SOURCES = ["ros", "system", "kernel", "mapping", "agent"]


def parse_since(value: str) -> float:
    m = re.fullmatch(r"(\d+)\s*([smhd])", value.strip())
    if not m:
        raise ToolError("--since must look like 30s, 15m, 2h or 1d")
    return time.time() - int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def _matches(line: str, level: str, pattern: re.Pattern | None) -> bool:
    if pattern and not pattern.search(line):
        return False
    return level == "all" or bool(LEVEL_PATTERNS[level].search(line))


def _tail_file(path: Path, since: float, level: str, pattern, lines: int) -> list[str]:
    try:
        content = path.read_text(errors="replace").splitlines()
    except OSError as exc:
        return [f"(cannot read {path}: {exc})"]
    hits = [l for l in content if _matches(l, level, pattern)]
    return hits[-lines:]


def ros_logs(since: float, level: str, pattern, lines: int) -> None:
    header("ROS logs", real=True)
    files: list[Path] = []
    for raw in config.load()["logs"].get("paths", []):
        root = Path(raw).expanduser()
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files += [p for p in root.rglob("*") if p.is_file() and p.suffix in (".log", ".txt", "")]
    files = sorted((p for p in files if p.stat().st_mtime >= since),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:12]
    if not files:
        print("  no ROS log files updated in this window")
        return
    shown = 0
    for path in files:
        hits = _tail_file(path, since, level, pattern, lines)
        if hits:
            shown += 1
            print(f"--- {path}")
            print("\n".join(hits))
    if not shown:
        print(f"  {len(files)} recent file(s), no matching {level} lines")


def journal(kind: str, since: float, level: str, pattern, lines: int,
            unit: str | None = None) -> None:
    title = "Kernel log" if kind == "kernel" else (f"Journal: {unit}" if unit else "System journal")
    header(title, real=True)
    cmd = ["journalctl", "--no-pager", "-o", "short-iso", "--since", f"@{int(since)}",
           "-p", JOURNAL_PRIORITY[level], "-n", str(lines * 4)]
    if kind == "kernel":
        cmd.append("-k")
    elif unit:
        cmd += ["-u", unit]
    else:
        for name in config.load()["logs"].get("journal_units", []):
            cmd += ["-u", name]
    code, out = run(cmd, timeout=15)
    if code not in (0, 1) and kind == "kernel":
        code, out = run(["dmesg", "--ctime", "--level=err,warn"], timeout=10)
    if code not in (0, 1):
        print(f"  unavailable: {out}")
        return
    out_lines = [l for l in out.splitlines() if not pattern or pattern.search(l)]
    print("\n".join(out_lines[-lines:]) or "  no matching entries")


def file_log(title: str, path: Path, since: float, level: str, pattern, lines: int) -> None:
    header(title, real=True)
    if not path.exists():
        print(f"  {path.relative_to(config.PROJECT_DIR)} does not exist yet")
        return
    hits = _tail_file(path, since, level, pattern, lines)
    print("\n".join(hits) or f"  no matching {level} lines")


def cmd(args) -> int:
    since = parse_since(args.since)
    pattern = re.compile(args.grep, re.I) if args.grep else None
    if args.unit:
        if not re.fullmatch(r"[\w@.\-]+", args.unit):
            raise ToolError(f"invalid unit name {args.unit!r}")
        sources = ["system"]
    else:
        sources = SOURCES if args.source == "all" else [args.source]
    logs_dir = config.artifacts("logs")
    print(f"Log window: last {args.since}, level >= {args.level}"
          + (f", matching /{args.grep}/" if args.grep else ""))
    for source in sources:
        if source == "ros":
            ros_logs(since, args.level, pattern, args.lines)
        elif source in ("system", "kernel"):
            journal(source, since, args.level, pattern, args.lines, args.unit)
        elif source == "mapping":
            file_log("Mapping process log", logs_dir / "mapping.log", since, args.level, pattern,
                     args.lines)
        elif source == "agent":
            file_log("Robot agent server log", logs_dir / "server.log", since, args.level, pattern,
                     args.lines)
    return 0


def register(sub) -> None:
    p = sub.add_parser("logs", help="inspect robot logs")
    p.add_argument("--source", default="all", choices=SOURCES + ["all"])
    p.add_argument("--since", default="30m", help="time window, e.g. 30s, 15m, 2h, 1d")
    p.add_argument("--level", default="warning", choices=["error", "warning", "all"])
    p.add_argument("--unit", help="one systemd service, e.g. piper.service (implies --source system)")
    p.add_argument("--grep", help="only lines matching this regex (case-insensitive)")
    p.add_argument("--lines", type=int, default=40, help="max lines per source")
    p.set_defaults(func=cmd)
