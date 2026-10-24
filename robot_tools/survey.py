"""Plant survey: replay the taught survey arm motion while recording a video of the plants.

`check` reports whether everything is ready (survey trajectory, arm, survey camera); `run`
replays the trajectory with `traj play` and records a clip from the survey camera that starts
when the replay starts (after the arm has settled, if it had to). Settings: `survey` in
robot.yaml.
"""

from __future__ import annotations

import argparse
import threading
import time

from . import arm, camera, config, trajectory
from .common import ToolError, display_path, header, kv, sim_tag, video_line


def _cfg() -> dict:
    return config.load()["survey"]


def _names(args) -> tuple[str, str]:
    cfg = _cfg()
    return args.name or str(cfg["trajectory"]), args.camera or str(cfg["camera"])


def _motion(name: str) -> dict:
    """Summary of the survey trajectory; raises ToolError if it is missing or invalid."""
    path = trajectory.resolve(name)
    points = trajectory.load_points(path)
    trajectory.validate(points, path.name)
    return {**trajectory.summary(points), "path": path,
            "simulated": trajectory.is_simulated(path)}


def check(args) -> int:
    name, cam = _names(args)
    lo, hi = _cfg()["motion_seconds"]
    problems, steps = [], []
    header("Plant survey readiness")

    try:
        m = _motion(name)
        note = " (simulated recording)" if m["simulated"] else ""
        kv("survey motion", f"OK - {name}: {m['points']} points, {m['duration_s']} s{note}")
        if not lo <= m["duration_s"] <= hi:
            kv("motion length", f"WARNING - {m['duration_s']} s is outside the usual {lo}-{hi} s")
    except ToolError as exc:
        problems.append("survey motion")
        kv("survey motion", f"MISSING - {exc}")
        steps.append(f"teach the survey motion: ./robot traj record --name {name} --seconds 20 "
                     f"(the operator moves the arm by hand for {lo}-{hi} s)")

    snap = arm.snapshot_safe()
    if not snap["available"]:
        problems.append("arm")
        kv("arm", f"UNAVAILABLE - {snap['error']}")
    else:
        state = f"status {snap['arm_status']}, control mode {snap['ctrl_mode']}"
        if snap["ctrl_mode"] == arm.CTRL_MODE[0x02]:
            problems.append("arm")
            kv("arm", f"NOT READY - {state}")
            steps.append("the operator must short-press the teach button to leave teach mode")
        elif snap["arm_status"] in trajectory.BLOCKING_STATUS or snap["errors"]:
            problems.append("arm")
            kv("arm", f"FAULT - {state}; {', '.join(snap['errors']) or 'no joint errors'}")
            steps.append("diagnose the arm fault first (robot-troubleshooting)")
        else:
            kv("arm", f"OK - {state}")
            if snap["ctrl_mode"] != arm.CTRL_MODE[0x01] and not config.is_sim():
                kv("note", "the replay first emergency-stops the arm until joints 2, 3 and 5 rest "
                           "(it sinks slowly), then re-enables it; the video starts after that")

    cams = config.cameras()
    source = cams.get(cam, "")
    if cam not in cams:
        problems.append("camera")
        kv(f"camera {cam}", f"UNKNOWN - configured: {', '.join(cams)}")
    elif not source:
        problems.append("camera")
        kv(f"camera {cam}", "NOT SET UP - no source yet. V4L2 capture devices on this computer:")
        camera.print_v4l2_devices(indent="    ")
        steps.append(f"ask the operator which device is the {cam} colour stream, then: "
                     f"./robot camera set-source --camera {cam} --source v4l2:<path>")
    else:
        try:
            path, info, _ = camera.capture(cam, source, args.timeout, config.camera_fallback(cam))
            rel = display_path(path)
            kv(f"camera {cam}", f"OK - {source}: test frame {info} -> {rel}")
            print(f"IMAGE: {rel}")
        except ToolError as exc:
            problems.append("camera")
            kv(f"camera {cam}", f"FAILED - {source}: {exc}")
            steps.append(f"check the camera (robot-camera skill); `./robot camera devices` lists "
                         f"V4L2 devices if {cam} needs another source")

    kv("ready", "yes" if not problems else f"no - fix: {', '.join(problems)}")
    for i, step in enumerate(steps, start=1):
        print(f"  next {i}: {step}")
    return 0


def run(args) -> int:
    name, cam = _names(args)
    cfg = _cfg()
    seconds = float(args.seconds or cfg["video_seconds"])
    if not 1 <= seconds <= camera.MAX_RECORD_S:
        raise ToolError(f"--seconds must be between 1 and {camera.MAX_RECORD_S:.0f}")
    fps = float(args.fps or cfg["video_fps"])
    m = _motion(name)
    source = config.cameras().get(cam)
    if source is None:
        raise ToolError(f"unknown camera {cam!r}")
    if not source:
        raise ToolError(f"camera {cam!r} is not set up; run `./robot survey check` and set its "
                        "source first")
    # Fail before anything moves if the camera cannot deliver a frame.
    camera.grab(cam, source, args.timeout)

    started, stop = threading.Event(), threading.Event()
    result: dict = {}

    def record() -> None:
        try:
            result["clip"] = camera.record(
                cam, source, seconds, fps, args.timeout, config.camera_fallback(cam),
                start_event=started, stop_event=stop, start_wait=args.settle_wait + 60,
                label=f"survey_{cam}")
        except BaseException as exc:  # reported after the replay
            result["error"] = exc

    recorder = threading.Thread(target=record, name="survey-video", daemon=True)
    recorder.start()
    print(f"{sim_tag()}plant survey: replaying {name} ({m['duration_s']} s) and recording "
          f"{seconds:.0f} s of video from {cam}, starting with the replay")
    begin: dict = {}

    def on_start() -> None:
        begin["t"] = time.monotonic()
        started.set()

    play_args = argparse.Namespace(name=name, speed=args.speed, rate=args.rate, times=1,
                                   settle_wait=args.settle_wait)
    try:
        trajectory.play(play_args, on_start=on_start)
    except BaseException:
        stop.set()
        started.set()
        recorder.join(timeout=60)
        raise
    recorder.join()
    if "error" in result:
        raise ToolError(f"the survey motion was replayed, but the video failed: {result['error']}")
    path, info, synthetic = result["clip"]
    rel = display_path(path)
    print(f"{'[SIM] ' if synthetic else ''}camera '{cam}': recorded {info} -> {rel}")
    video_line(str(rel))
    print(f"{sim_tag()}plant survey complete: motion {name} ({m['duration_s']} s at rate "
          f"{args.rate}), video {rel}")
    return 0


ACTIONS = {"check": check, "run": run}


def register(sub) -> None:
    p = sub.add_parser("survey", help="plant survey: replay the survey arm motion and record "
                                      "a video")
    p.add_argument("action", choices=list(ACTIONS))
    p.add_argument("--name", help="survey trajectory (default survey.trajectory in robot.yaml)")
    p.add_argument("--camera", help="survey camera (default survey.camera in robot.yaml)")
    p.add_argument("--seconds", type=float,
                   help=f"video length in s (default survey.video_seconds, max "
                        f"{camera.MAX_RECORD_S:.0f})")
    p.add_argument("--fps", type=float, help="video frame rate (default survey.video_fps)")
    p.add_argument("--speed", type=int, help="joint speed percent (capped by arm.max_speed)")
    p.add_argument("--rate", type=float, default=1.0, help="replay time scale 0.1-1.0")
    p.add_argument("--settle-wait", type=float, default=60.0,
                   help="s allowed for the arm to settle before the replay")
    p.add_argument("--timeout", type=float, default=5.0, help="camera frame timeout in s")
    p.set_defaults(func=lambda args: ACTIONS[args.action](args))
