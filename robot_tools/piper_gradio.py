"""`./robot piper`: record and replay Piper arm trajectories with AgiLex's Gradio recorder logic.

The recording and replay logic of AgiLex's Gradio ``record.py`` / ``play.py``
(``Agilex-College/piper/recordAndPlayTraj``) lives, without its web UI, in ``piper_record.py``
(``Recorder``: wait for teach mode, threaded recorder storing only changes, session copy in
``<trajectories>/sessions/``) and ``piper_play.py`` (``Player``: settle at rest, CAN mode, enable,
replay with loops, a pause after each loop, speed multiplier and gripper).

This module adds what the web UI did not have: the B2 must be standing still, the CAN port from
``robot.yaml``, the shared arm lock, joint-limit checks, speed/rate/loop caps, a time limit on
every phase, and a watchdog that stops the replay when the arm is emergency-stopped.

Trajectories are shared with `./robot traj` (same CSV format, ``artifacts/trajectories/``):
    wait_s, j1_rad, j2_rad, j3_rad, j4_rad, j5_rad, j6_rad[, gripper_m]
"""

from __future__ import annotations

import math
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Iterator

from . import base, config, trajectory
from .arm import (ARM_STATUS, CTRL_MODE, _val, clamp_speed, joint_limits, motion_lock, open_arm,
                  print_snapshot)
from .common import ToolError, Unavailable, sim_tag
from .piper_play import Player
from .piper_record import Recorder, connect, read_pose

MAX_RECORD_S = trajectory.MAX_RECORD_S
MAX_LOOPS = trajectory.MAX_PLAY_TIMES
MAX_INTERVAL_S = 5.0
POLL_RANGE_S = (0.005, 0.1)
# Auto-stop of a recording: the arm moved more than MOVED_DEG from its start pose, then no joint
# changed by more than STILL_DEG for --stop-when-still seconds.
MOVED_DEG = 2.0
STILL_DEG = 0.5
CAN_MODE_TIMEOUT_S = 5.0
CAN_FRAMES_WAIT_S = 1.5
# Per-point log lines of the recorder/player; they are counted instead of printed.
POINT_LINE = re.compile(r"^(Point \d+ wait=|Cycle \d+ point \d+/)")


# ----- arm link and log -----

class RunLog:
    """Log for ``Recorder``/``Player``: prints messages, counts per-point lines, keeps errors."""

    def __init__(self):
        self.points = 0
        self.errors: list[str] = []

    def __call__(self, status: str, message: str) -> None:
        if POINT_LINE.match(message):
            self.points += 1
            return
        if status == "error":
            self.errors.append(message)
        print(f"  {status}: {message}")

    def last_error(self, default: str) -> str:
        return self.errors[-1] if self.errors else default


@contextmanager
def arm_link() -> Iterator[Any]:
    """The arm's piper_sdk interface on the CAN port from robot.yaml, closed afterwards."""
    port = config.arm_port()
    if not Path(f"/sys/class/net/{port}").exists():
        raise Unavailable(f"CAN interface {port} for the arm does not exist; check the USB-CAN "
                          "adapter and piper-can.service")
    try:
        piper = connect(port)
    except ImportError as exc:
        raise Unavailable(f"piper_sdk is not installed: {exc}") from exc
    try:
        end = time.monotonic() + CAN_FRAMES_WAIT_S
        while piper.GetCanFps() <= 0 and time.monotonic() < end:
            time.sleep(0.05)
        if piper.GetCanFps() <= 0:
            raise Unavailable(f"no CAN frames from the arm on {port}; check arm power and wiring")
        yield piper
    finally:
        try:
            piper.DisconnectPort()
        except Exception:
            pass


def _locked(fn):
    """Hold the shared arm lock (arm, traj and piper commands) for the whole run."""
    @wraps(fn)
    def run(args, **kwargs) -> int:
        with motion_lock(f"piper {fn.__name__}"):
            return fn(args, **kwargs)
    return run


def _check_range(value: float, lo: float, hi: float, option: str, unit: str = "") -> None:
    if not lo <= value <= hi:
        raise ToolError(f"{option} must be between {lo:g} and {hi:g}{unit}")


# ----- record -----

def _joints_deg(piper: Any) -> list[float]:
    return [math.degrees(v) for v in read_pose(piper, False)]


class StillWatch:
    """Decides when a hand-guided motion is over: the arm has moved away from where it started
    (more than ``MOVED_DEG``) and then stayed within ``STILL_DEG`` for ``still_s`` seconds."""

    def __init__(self, start_deg: list[float], still_s: float, now: float):
        self.start = start_deg
        self.ref = start_deg
        self.still_s = still_s
        self.still_since = now
        self.moved = False

    def update(self, pose_deg: list[float], now: float) -> bool:
        if max(abs(a - b) for a, b in zip(pose_deg, self.ref)) > STILL_DEG:
            self.ref = pose_deg
            self.still_since = now
        if max(abs(a - b) for a, b in zip(pose_deg, self.start)) > MOVED_DEG:
            self.moved = True
        return self.moved and now - self.still_since >= self.still_s


def _wait_recording(recorder: Recorder, piper: Any, seconds: float, still_s: float) -> str:
    """Wait until the recording ends: "still" (motion over), "duration" or "timeout"."""
    thread = recorder.thread
    deadline = time.monotonic() + seconds + 10
    watch = StillWatch(_joints_deg(piper), still_s, time.monotonic()) if still_s else None
    while thread.is_alive():
        if time.monotonic() > deadline:
            recorder.stop()
            thread.join(5)
            return "timeout"
        thread.join(0.1)
        if watch is not None and thread.is_alive() and \
                watch.update(_joints_deg(piper), time.monotonic()):
            recorder.stop()
            thread.join(5)
            return "still"
    return "duration"


def _sim_record(args, name: str, path: Path, seconds: float) -> int:
    """Simulated teach-mode recording: the operator guides the arm out and back, then holds it
    still. Needs the simulated teach mode (`./robot arm teach-button`), like the real arm."""
    arm = open_arm()
    try:
        snap = arm.snapshot()
    finally:
        arm.close()
    if snap["ctrl_mode"] != CTRL_MODE[0x02]:
        raise ToolError("teach mode was not detected - the operator must press the teach button "
                        "first (in SIM: `./robot arm teach-button` once the operator says they "
                        "pressed it)")
    still_s = float(args.stop_when_still)
    print(f"{sim_tag()}recording {name}: teach mode active; recording starts in "
          f"{args.start_delay:.0f}s. The simulated operator guides the arm out and back, then "
          "holds it still")
    start = snap["joints_deg"]
    limits = joint_limits()
    idle = min(1.0, seconds / 4)
    motion = max(1.0, min(12.0, seconds - idle - still_s)) if still_s \
        else max(1.0, seconds - idle - 1.0)
    dt = float(args.poll)
    grip = [] if args.no_gripper else [snap["gripper_mm"] / 1000]
    rows, t = [], 0.0
    while t < motion:
        t = min(motion, t + dt)
        w = math.sin(math.pi * t / motion) ** 2  # out and back to the start pose
        pose = list(start)
        pose[0] = start[0] + 25 * w
        pose[1] = start[1] + 15 * w
        pose = [max(lo, min(hi, v)) for v, (lo, hi) in zip(pose, limits)]
        wait = idle + dt if not rows else dt
        rows.append([wait] + [math.radians(v) for v in pose] + grip)
    path.write_text("".join(",".join(map(str, r)) + "\n" for r in rows))
    if still_s:
        ended = idle + motion + still_s
        print(f"{sim_tag()}recording ended: the arm was back and still for {still_s:g}s "
              f"(after {ended:.1f}s of at most {seconds:.0f}s)")
    else:
        print(f"{sim_tag()}recording ended after the full {seconds:.0f}s")
    print(f"  points recorded: {len(rows)}")
    trajectory.print_summary(path, trajectory.load_points(path))
    print("next: the arm is still in teach mode - the operator presses the teach button again "
          "to leave it (in SIM: `./robot arm teach-button`), then the trajectory can be played "
          f"with `./robot piper play --name {name}`")
    return 0


@_locked
def record(args) -> int:
    name = trajectory._check_name(args.name or datetime.now().strftime("piper-%Y%m%d-%H%M%S"))
    path = trajectory.traj_dir() / f"{name}.csv"
    if path.exists():
        raise ToolError(f"a trajectory named {name!r} already exists; choose another --name")
    seconds = float(args.seconds)
    _check_range(seconds, 1, MAX_RECORD_S, "--seconds", " s")
    _check_range(args.teach_wait, 5, 120, "--teach-wait", " s")
    _check_range(args.start_delay, 0, 30, "--start-delay", " s")
    _check_range(args.poll, *POLL_RANGE_S, "--poll", " s")
    if args.stop_when_still:
        _check_range(args.stop_when_still, 1, 10, "--stop-when-still", " s (0 = off)")
    base.require_standing_still("arm recording")

    if config.is_sim():
        return _sim_record(args, name, path, seconds)

    log = RunLog()
    with arm_link() as piper:
        recorder = Recorder(piper, path.parent / "sessions", log)
        until = (f"until the arm has moved and then stayed still for {args.stop_when_still:g}s "
                 f"(at most {seconds:.0f}s)" if args.stop_when_still else f"for {seconds:.0f}s")
        print(f"recording {name} (Gradio recorder): waiting up to {args.teach_wait:.0f}s for "
              f"teach mode; recording starts {args.start_delay:.0f}s after it is detected and "
              f"lasts {until}")
        if not recorder.wait_teaching_mode(float(args.teach_wait)):
            raise ToolError(f"teach mode was not detected within {args.teach_wait:.0f}s - the "
                            "operator must short-press the arm's teach button")
        time.sleep(args.start_delay)
        recorder.start(str(path), not args.no_gripper, seconds, float(args.poll))
        ended = _wait_recording(recorder, piper, seconds, float(args.stop_when_still))

    if log.errors:
        path.unlink(missing_ok=True)
        raise ToolError(f"recording failed: {log.errors[-1]}")
    if not path.exists() or not path.read_text().strip():
        path.unlink(missing_ok=True)
        if recorder.last_session_path:
            Path(recorder.last_session_path).unlink(missing_ok=True)
        raise ToolError("no motion was recorded - the arm was not moved while recording")
    if ended == "still":
        print(f"recording ended: the arm was back and still for {args.stop_when_still:g}s")
    elif ended == "timeout":
        print("recording did not end on time and was stopped")
    else:
        print(f"recording ended after the full {seconds:.0f}s")
    print(f"  points recorded: {log.points}")
    trajectory.print_summary(path, trajectory.load_points(path))
    print("next: the arm is still in teach mode - the operator must short-press the teach "
          f"button again to exit it, then the trajectory can be played with "
          f"`./robot piper play --name {name}`")
    return 0


# ----- play -----

def _check_playable(snap: dict) -> None:
    if snap["ctrl_mode"] == CTRL_MODE[0x02]:
        raise ToolError("the arm is still in teach mode; the operator must short-press the "
                        "teach button to exit it, then retry")
    if snap["arm_status"] in trajectory.BLOCKING_STATUS or snap["errors"]:
        raise ToolError(f"the arm reports a fault ({snap['arm_status']}; "
                        f"{', '.join(snap['errors']) or 'no joint errors'}); not playing")
    if snap["ctrl_mode"] == CTRL_MODE[0x01] and snap["arm_status"] == ARM_STATUS[0x01]:
        # The player only clears an emergency stop when it switches modes itself.
        raise ToolError("the arm is emergency-stopped; run `./robot arm take-control` first")


def _wait(thread: threading.Thread, done: threading.Event, limit_s: float,
          piper: Any = None) -> str:
    """Wait for ``done`` or the thread to end; returns "done", "ended", "timeout" or "estop".

    With ``piper`` the arm status is watched, so an emergency stop (E-STOP button,
    `./robot arm stop`) ends the wait.
    """
    deadline = time.monotonic() + limit_s
    while not done.is_set() and thread.is_alive():
        if time.monotonic() > deadline:
            return "timeout"
        if piper is not None and _val(piper.GetArmStatus().arm_status.arm_status) == 0x01:
            return "estop"
        thread.join(0.1)
    return "done" if done.is_set() else "ended"


def _replay(piper: Any, path: Path, args, speed: int, duration_s: float, settle: bool) -> None:
    """Initialise the arm and replay ``path`` in a thread, under time limits and the watchdog."""
    gripper = not args.no_gripper
    log = RunLog()
    player = Player(piper, log)
    if not player.load_track(str(path)):
        raise ToolError(f"playback failed: {log.last_error('no track')}")
    ready = threading.Event()
    finished = threading.Event()

    def work() -> None:
        try:
            if player.init_arm(CAN_MODE_TIMEOUT_S, speed, gripper):
                ready.set()
                player.play(args.times, float(args.interval), speed, float(args.rate), gripper)
                finished.set()
        except Exception as exc:
            log.errors.append(f"{type(exc).__name__}: {exc}")

    thread = threading.Thread(target=work, name="piper-play", daemon=True)
    thread.start()
    try:
        init_limit = (args.settle_wait if settle else 0) + CAN_MODE_TIMEOUT_S + 10
        outcome = _wait(thread, ready, init_limit)
        if outcome == "timeout":
            hint = (" - joints 2, 3 and 5 most likely did not settle at rest; the arm stays "
                    "emergency-stopped. Guide those joints to rest or run `./robot arm resume`"
                    if settle else "")
            raise ToolError(f"the arm was not ready within {init_limit:.0f}s; nothing was "
                            f"played{hint}")
        if outcome == "ended":
            raise ToolError(f"the arm could not be initialised: {log.last_error('unknown error')}")
        play_limit = args.times * (duration_s / args.rate + args.interval) + 10
        outcome = _wait(thread, finished, play_limit, piper)
        if outcome != "done":
            player.stop()
            thread.join(2)
        print(f"  points sent: {log.points}")
        if outcome == "estop":
            raise ToolError("the arm was emergency-stopped during the replay; playback stopped")
        if outcome == "timeout":
            raise ToolError(f"playback did not finish within {play_limit:.0f}s and was stopped")
        if log.errors:
            raise ToolError(f"playback failed: {log.errors[-1]}")
    finally:
        if thread.is_alive():
            player.stop()
            thread.join(2)


@_locked
def play(args) -> int:
    path = trajectory.resolve(args.name)
    points = trajectory.load_points(path)
    trajectory.validate(points, path.name)
    speed = clamp_speed(args.speed)
    _check_range(args.rate, 0.1, 1.0, "--rate", " (1.0 = recorded speed)")
    _check_range(args.times, 1, MAX_LOOPS, "--times")
    _check_range(args.interval, 0, MAX_INTERVAL_S, "--interval", " s")
    _check_range(args.settle_wait, 10, 180, "--settle-wait", " s")
    base.require_standing_still("arm replay")
    s = trajectory.summary(points)

    arm = open_arm()
    try:
        snap = arm.snapshot()
        _check_playable(snap)
        jump = max(abs(c - t) for c, t in zip(snap["joints_deg"], s["start_deg"]))
        print(f"{sim_tag()}playing {path.stem} (Gradio player): {s['points']} points, "
              f"{s['duration_s']}s x{args.times} at rate {args.rate}, joint speed {speed}%, "
              f"{args.interval:g}s after each loop, "
              f"gripper {'off' if args.no_gripper else 'on'}")
        print(f"  current joints (deg): {trajectory._fmt(snap['joints_deg'])}")
        print(f"  start joints (deg)  : {trajectory._fmt(s['start_deg'])}  "
              f"(largest jump {jump:.1f} deg)")
        if config.is_sim():
            end = [max(lo, min(hi, v)) for v, (lo, hi) in zip(s["end_deg"], joint_limits())]
            arm.move_joints(end, speed)
            print(f"{sim_tag()}trajectory played; arm left at the last point")
            print_snapshot(arm.snapshot())
            return 0
        settle = snap["ctrl_mode"] != CTRL_MODE[0x01]
    finally:
        arm.close()

    if settle:
        print("  arm is not in CAN command mode: the player first emergency-stops it and waits "
              "for joints 2, 3 and 5 to settle at rest before re-enabling")
    with arm_link() as piper:
        _replay(piper, path, args, speed, s["duration_s"], settle)

    arm = open_arm()
    try:
        print_snapshot(arm.snapshot())
    finally:
        arm.close()
    return 0


ACTIONS = {"list": trajectory.list_, "show": trajectory.show, "record": record, "play": play}


def register(sub) -> None:
    p = sub.add_parser("piper", help="record and replay Piper arm trajectories with AgiLex's "
                                     "Gradio recorder/player logic (teach mode)")
    p.add_argument("action", choices=list(ACTIONS))
    p.add_argument("--name", help="trajectory name (default: new timestamp / most recent)")
    p.add_argument("--no-gripper", action="store_true",
                   help="record/play: leave out the gripper opening")
    p.add_argument("--seconds", type=float, default=15.0,
                   help=f"record: maximum recording length in s (1-{MAX_RECORD_S:.0f})")
    p.add_argument("--teach-wait", type=float, default=30.0,
                   help="record: s to wait for the teach button (5-120)")
    p.add_argument("--start-delay", type=float, default=3.0,
                   help="record: s between teach mode and the start of recording (0-30)")
    p.add_argument("--stop-when-still", type=float, default=3.0,
                   help="record: end once the arm has moved and then been still this many s "
                        "(1-10; 0 = always record --seconds)")
    p.add_argument("--poll", type=float, default=0.02,
                   help=f"record: poll interval in s ({POLL_RANGE_S[0]}-{POLL_RANGE_S[1]})")
    p.add_argument("--speed", type=int, help="play: joint speed percent (capped by arm.max_speed)")
    p.add_argument("--rate", type=float, default=1.0, help="play: time scale 0.1-1.0")
    p.add_argument("--times", type=int, default=1, help=f"play: loops (1-{MAX_LOOPS})")
    p.add_argument("--interval", type=float, default=1.0,
                   help=f"play: pause after each loop in s (0-{MAX_INTERVAL_S:g})")
    p.add_argument("--settle-wait", type=float, default=60.0,
                   help="play: s allowed for the arm to settle after leaving teach mode")
    p.set_defaults(func=lambda args: ACTIONS[args.action](args))
