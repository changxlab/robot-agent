"""Record and replay continuous Piper arm trajectories.

Runs AgiLex's recordTrajectory_new.py / playTrajectory_new.py (see b2_commands.md, section 7)
with their tunable parameters set by this tool (duration, timeouts, speed caps, CSV path), the
interactive Enter prompts answered automatically and a hard time limit on every run. The scripts
on disk are never modified.

CSV format (one row per recorded change, same as the scripts):
    wait_s, j1_rad, j2_rad, j3_rad, j4_rad, j5_rad, j6_rad[, gripper_m]
"""

from __future__ import annotations

import csv
import math
import os
import re
import select
import signal
import subprocess
import sys
import time
from datetime import datetime
from functools import wraps
from pathlib import Path

from . import config
from .arm import (CTRL_MODE, GRIPPER_MAX_MM, clamp_speed, joint_limits, motion_lock, open_arm,
                  print_snapshot)
from .common import ToolError, header, kv, sim_tag

RECORD_SCRIPT = "recordTrajectory_new.py"
PLAY_SCRIPT = "playTrajectory_new.py"
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
LIMIT_TOLERANCE_DEG = 3.0
MAX_RECORD_S = 120.0
MAX_PLAY_TIMES = 5
# Arm states in which a replay must not start (an emergency stop is cleared by the script).
BLOCKING_STATUS = {"joint communication error", "joint brake not released", "collision detected",
                   "joint status error", "main controller over temperature",
                   "release resistor over temperature"}


# ----- trajectory files -----

def real_dir() -> Path:
    return config.artifacts("trajectories")


def sim_dir() -> Path:
    return config.artifacts("sim/trajectories")


def traj_dir() -> Path:
    """Where new recordings go. Synthetic SIM recordings are kept apart from real ones so they
    can never be replayed on the real arm."""
    return sim_dir() if config.is_sim() else real_dir()


def search_dirs() -> list[Path]:
    """Trajectories that can be played: SIM sees its own and the real recordings."""
    return [sim_dir(), real_dir()] if config.is_sim() else [real_dir()]


def is_simulated(path: Path) -> bool:
    return path.parent == sim_dir()


def all_files() -> list[Path]:
    """Saved trajectories, oldest first; a SIM recording hides a real one of the same name."""
    files: dict[str, Path] = {}
    for d in reversed(search_dirs()):
        files.update({p.stem: p for p in d.glob("*.csv")})
    return sorted(files.values(), key=lambda p: p.stat().st_mtime)


def script_dir() -> Path:
    return Path(os.path.expanduser(str(config.load()["arm"]["trajectory_dir"])))


def _check_name(name: str) -> str:
    if not NAME_RE.fullmatch(name):
        raise ToolError("trajectory name must be 1-64 letters, digits, '-' or '_'")
    return name


def resolve(name: str | None) -> Path:
    """Path of a saved trajectory; the most recent one when no name is given."""
    if name:
        for d in search_dirs():
            path = d / f"{_check_name(name)}.csv"
            if path.exists():
                return path
        raise ToolError(f"no trajectory named {name!r}; run `./robot traj list`")
    files = all_files()
    if not files:
        raise ToolError("no trajectories recorded yet; run `./robot traj record` first")
    return files[-1]


def load_points(path: Path) -> list[list[float]]:
    try:
        with path.open(encoding="utf-8") as f:
            rows = [r for r in csv.reader(f) if r]
        points = [[float(v) for v in r] for r in rows]
    except (OSError, ValueError) as exc:
        raise ToolError(f"cannot read trajectory {path.name}: {exc}") from exc
    if not points:
        raise ToolError(f"trajectory {path.name} is empty")
    for n, p in enumerate(points, start=1):
        if len(p) not in (7, 8):
            raise ToolError(f"{path.name} row {n}: expected 7 or 8 values, got {len(p)}")
        if p[0] < 0 or not all(math.isfinite(v) for v in p):
            raise ToolError(f"{path.name} row {n}: invalid values")
    return points


def deg(point: list[float]) -> list[float]:
    return [math.degrees(v) for v in point[1:7]]


def validate(points: list[list[float]], name: str) -> None:
    """Refuse trajectories outside the mounted arm's joint limits and the gripper range."""
    limits = joint_limits()
    for n, p in enumerate(points, start=1):
        for j, (value, (lo, hi)) in enumerate(zip(deg(p), limits), start=1):
            if not lo - LIMIT_TOLERANCE_DEG <= value <= hi + LIMIT_TOLERANCE_DEG:
                raise ToolError(f"{name} row {n}: joint {j} = {value:.1f} deg is outside the "
                                f"safe range [{lo:g}, {hi:g}] (arm.joint_limits_deg); it will "
                                "not be played")
        if len(p) == 8 and not -0.002 <= p[7] <= GRIPPER_MAX_MM / 1000 + 0.002:
            raise ToolError(f"{name} row {n}: gripper {p[7] * 1000:.1f} mm is out of range")


def summary(points: list[list[float]]) -> dict:
    joints = [deg(p) for p in points]
    grip = [p[7] * 1000 for p in points if len(p) == 8]
    return {
        "points": len(points),
        "duration_s": round(sum(p[0] for p in points), 2),
        "start_deg": joints[0],
        "end_deg": joints[-1],
        "range_deg": [(min(j[i] for j in joints), max(j[i] for j in joints)) for i in range(6)],
        "gripper_mm": (min(grip), max(grip)) if grip else None,
    }


def _fmt(values: list[float]) -> str:
    return ", ".join(f"{v:.1f}" for v in values)


def print_summary(path: Path, points: list[list[float]]) -> None:
    s = summary(points)
    header(f"Trajectory {path.stem}" + (" (simulated recording)" if is_simulated(path) else ""),
           real=not is_simulated(path))
    kv("file", path.relative_to(config.PROJECT_DIR) if path.is_relative_to(config.PROJECT_DIR)
       else path)
    kv("points", s["points"])
    kv("duration (s)", s["duration_s"])
    kv("start joints (deg)", _fmt(s["start_deg"]))
    kv("end joints (deg)", _fmt(s["end_deg"]))
    kv("joint ranges (deg)", "; ".join(f"j{i} {lo:.1f}..{hi:.1f}"
                                         for i, (lo, hi) in enumerate(s["range_deg"], start=1)))
    if s["gripper_mm"]:
        kv("gripper (mm)", f"{s['gripper_mm'][0]:.1f}..{s['gripper_mm'][1]:.1f}")


# ----- running the vendor scripts -----

def patched_source(script: Path, params: dict[str, str]) -> str:
    """The script's source with its top-level tunables set to ``params`` (Python literals)."""
    if not script.exists():
        raise ToolError(f"{script} not found; set arm.trajectory_dir in robot.yaml")
    src = script.read_text(encoding="utf-8")
    for name, value in params.items():
        pattern = re.compile(rf"^([ \t]*){re.escape(name)}[ \t]*=.*$", re.M)
        src, count = pattern.subn(lambda m: f"{m.group(1)}{name} = {value}", src, count=1)
        if count != 1:
            raise ToolError(f"{script.name} has no parameter {name!r}; the script changed - "
                            "check robot_tools/trajectory.py against it")
    if "__file__" in src:
        raise ToolError(f"{script.name} uses __file__ outside the parameters; not supported")
    return src


def run_script(src: str, cwd: Path, limit_s: float, enter_delay: float = 0.0,
               on_enter=None) -> tuple[str, bool]:
    """Run patched script source; answer its "step 2" Enter prompt after ``enter_delay`` s.

    ``on_enter`` is called just before Enter is sent (the start of recording or playback).
    Returns (output, timed_out). On timeout the script gets Ctrl+C, then is killed.
    """
    proc = subprocess.Popen([sys.executable, "-u", "-c", src], cwd=cwd, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = b""
    sent_enter = False
    enter_at: float | None = None
    deadline = time.monotonic() + limit_s
    timed_out = False
    try:
        while True:
            now = time.monotonic()
            if now > deadline:
                timed_out = True
                proc.send_signal(signal.SIGINT)
                try:
                    proc.wait(3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
            if not sent_enter and enter_at is None and b"step 2" in out:
                enter_at = now + enter_delay
            if enter_at is not None and not sent_enter and now >= enter_at:
                sent_enter = True
                if on_enter is not None:
                    on_enter()
                try:
                    proc.stdin.write(b"\n")
                    proc.stdin.flush()
                except BrokenPipeError:
                    pass
            ready, _, _ = select.select([proc.stdout], [], [], 0.05)
            if ready:
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                out += chunk
        proc.wait(5)
        out += proc.stdout.read() or b""
    finally:
        if proc.poll() is None:
            proc.kill()
    # input() prompts have no newline, so following INFO lines would run on.
    text = out.decode("utf-8", "replace").replace("INFO:", "\nINFO:")
    return "\n".join(line for line in text.splitlines() if line.strip()), timed_out


def script_messages(output: str, skip: str) -> list[str]:
    """Script lines worth showing; per-point INFO lines (matching ``skip``) are dropped."""
    return [line for line in output.splitlines() if skip not in line]


def _script_error(output: str) -> str | None:
    lines = output.splitlines()
    if any(line.startswith("Traceback") for line in lines):
        return lines[-1]
    return next((line for line in lines if line.startswith("ERROR")), None)


# ----- commands -----

def _locked(fn):
    """Hold the arm lock for the whole run so no other arm command can interleave."""
    @wraps(fn)
    def run(args, **kwargs) -> int:
        with motion_lock(f"traj {fn.__name__}"):
            return fn(args, **kwargs)
    return run


@_locked
def record(args) -> int:
    name = _check_name(args.name or datetime.now().strftime("traj-%Y%m%d-%H%M%S"))
    path = traj_dir() / f"{name}.csv"
    if path.exists():
        raise ToolError(f"a trajectory named {name!r} already exists; choose another --name")
    seconds = float(args.seconds)
    if not 1 <= seconds <= MAX_RECORD_S:
        raise ToolError(f"--seconds must be between 1 and {MAX_RECORD_S:.0f}")
    if not 5 <= args.teach_wait <= 120:
        raise ToolError("--teach-wait must be between 5 and 120 seconds")
    if not 0 <= args.start_delay <= 30:
        raise ToolError("--start-delay must be between 0 and 30 seconds")

    if config.is_sim():
        arm = open_arm()
        try:
            start = arm.joints_deg()
        finally:
            arm.close()
        steps = max(10, int(seconds * 5))
        lo1, hi1 = joint_limits()[0]
        with path.open("w") as f:
            for i in range(steps):
                j = list(start)
                j[0] = max(lo1, min(hi1, start[0] + 20 * math.sin(2 * math.pi * i / steps)))
                f.write(",".join(str(v) for v in [seconds / steps]
                                 + [math.radians(v) for v in j] + [0.0]) + "\n")
        print(f"{sim_tag()}recorded a synthetic {seconds:.0f}s trajectory: SIM has no teach mode, "
              "so the operator does not press the teach button or move the arm. It is saved "
              "with the SIM data and is never played on the real arm")
        print_summary(path, load_points(path))
        return 0

    src = patched_source(script_dir() / RECORD_SCRIPT, {
        "record_time": repr(seconds), "timeout": repr(float(args.teach_wait)),
        "CSV_path": repr(str(path)),
    })
    print(f"recording {name}: waiting up to {args.teach_wait:.0f}s for the operator to press the "
          f"teach button; recording starts {args.start_delay:.0f}s after teach mode is detected "
          f"and lasts {seconds:.0f}s")
    limit = args.teach_wait + args.start_delay + seconds + 20
    output, timed_out = run_script(src, script_dir(), limit, args.start_delay)
    for line in script_messages(output, "INFO: 等待时间"):
        print(f"  script: {line}")
    if timed_out:
        raise ToolError(f"recording did not finish within {limit:.0f}s and was stopped")
    error = _script_error(output)
    if error:
        path.unlink(missing_ok=True)
        if "示教模式检测超时" in error:
            raise ToolError(f"teach mode was not detected within {args.teach_wait:.0f}s - the "
                            "operator must short-press the arm's teach button after approving")
        raise ToolError(f"recording failed: {error}")
    if not path.exists() or not path.read_text().strip():
        path.unlink(missing_ok=True)
        raise ToolError("no motion was recorded - the arm was not moved while recording")
    print_summary(path, load_points(path))
    print("next: the arm is still in teach mode - the operator must short-press the teach "
          "button again to exit it before the trajectory can be played")
    return 0


@_locked
def play(args, on_start=None) -> int:
    """Replay a trajectory; ``on_start`` is called when the replay itself begins."""
    path = resolve(args.name)
    points = load_points(path)
    validate(points, path.name)
    speed = clamp_speed(args.speed)
    if not 0.1 <= args.rate <= 1.0:
        raise ToolError("--rate must be between 0.1 and 1.0 (1.0 = recorded speed)")
    if not 1 <= args.times <= MAX_PLAY_TIMES:
        raise ToolError(f"--times must be between 1 and {MAX_PLAY_TIMES}")
    if not 10 <= args.settle_wait <= 180:
        raise ToolError("--settle-wait must be between 10 and 180 seconds")
    s = summary(points)

    arm = open_arm()
    try:
        snap = arm.snapshot()
        if snap["ctrl_mode"] == CTRL_MODE[0x02]:
            raise ToolError("the arm is still in teach mode; the operator must short-press the "
                            "teach button to exit it, then retry")
        if snap["arm_status"] in BLOCKING_STATUS or snap["errors"]:
            raise ToolError(f"the arm reports a fault ({snap['arm_status']}; "
                            f"{', '.join(snap['errors']) or 'no joint errors'}); not playing")
        jump = max(abs(c - t) for c, t in zip(snap["joints_deg"], s["start_deg"]))
        print(f"{sim_tag()}playing {path.stem}: {s['points']} points, {s['duration_s']}s "
              f"x{args.times} at rate {args.rate}, joint speed {speed}%")
        print(f"  current joints (deg): {_fmt(snap['joints_deg'])}")
        print(f"  start joints (deg)  : {_fmt(s['start_deg'])}  (largest jump {jump:.1f} deg)")
        if config.is_sim():
            if on_start is not None:
                on_start()
            end = [max(lo, min(hi, v)) for v, (lo, hi) in zip(s["end_deg"], joint_limits())]
            arm.move_joints(end, speed)
            print(f"{sim_tag()}trajectory played; arm left at the last point")
            print_snapshot(arm.snapshot())
            return 0
        settle = snap["ctrl_mode"] != CTRL_MODE[0x01]
    finally:
        arm.close()

    if settle:
        print("  arm is not in CAN command mode: the script first emergency-stops it and waits "
              "for joints 2, 3 and 5 to settle at rest before re-enabling")
    src = patched_source(script_dir() / PLAY_SCRIPT, {
        "play_times": str(args.times), "move_spd_rate_ctrl": str(speed),
        "play_speed": repr(float(args.rate)), "CSV_path": repr(str(path)),
    })
    limit = (args.settle_wait if settle else 0) + 20 \
        + args.times * (s["duration_s"] / args.rate + 1.0)
    output, timed_out = run_script(src, script_dir(), limit, on_enter=on_start)
    lines = script_messages(output, "次播放")
    played = len(output.splitlines()) - len(lines)
    for line in lines:
        print(f"  script: {line}")
    print(f"  points sent: {played}")
    if timed_out:
        hint = (" - it was most likely still waiting for joints 2, 3 and 5 to settle at rest; "
                "the arm stays emergency-stopped. Guide those joints to their rest position or "
                "run `./robot arm resume`" if settle and played == 0 else "")
        raise ToolError(f"playback did not finish within {limit:.0f}s and was stopped{hint}")
    error = _script_error(output)
    if error:
        raise ToolError(f"playback failed: {error}")
    arm = open_arm()
    try:
        print_snapshot(arm.snapshot())
    finally:
        arm.close()
    return 0


def show(args) -> int:
    path = resolve(args.name)
    print_summary(path, load_points(path))
    return 0


def list_(args) -> int:
    header("Recorded arm trajectories", real=True)
    files = all_files()
    if not files:
        print("  none - record one with `./robot traj record`")
    for p in files:
        try:
            s = summary(load_points(p))
            info = f"{s['points']} points, {s['duration_s']}s"
        except ToolError as exc:
            info = f"unreadable: {exc}"
        when = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"  {p.stem}  ({when}, {info}{', simulated' if is_simulated(p) else ''})")
    return 0


ACTIONS = {"list": list_, "show": show, "record": record, "play": play}


def register(sub) -> None:
    p = sub.add_parser("traj", help="record and replay Piper arm trajectories (teach mode)")
    p.add_argument("action", choices=list(ACTIONS))
    p.add_argument("--name", help="trajectory name (default: new timestamp / most recent)")
    p.add_argument("--seconds", type=float, default=15.0,
                   help=f"record: recording length in s (1-{MAX_RECORD_S:.0f})")
    p.add_argument("--teach-wait", type=float, default=30.0,
                   help="record: s to wait for the teach button (5-120)")
    p.add_argument("--start-delay", type=float, default=3.0,
                   help="record: s between teach mode and the start of recording (0-30)")
    p.add_argument("--speed", type=int, help="play: joint speed percent (capped by arm.max_speed)")
    p.add_argument("--rate", type=float, default=1.0, help="play: time scale 0.1-1.0")
    p.add_argument("--times", type=int, default=1, help=f"play: repetitions (1-{MAX_PLAY_TIMES})")
    p.add_argument("--settle-wait", type=float, default=60.0,
                   help="play: s allowed for the arm to settle after leaving teach mode")
    p.set_defaults(func=lambda args: ACTIONS[args.action](args))
