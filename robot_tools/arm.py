"""Control of the robot's single AgileX Piper arm through piper_sdk (CAN interface)."""

from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import config
from .common import ToolError, Unavailable, header, kv, sim_tag

# Official Piper joint limits in degrees, from piper_sdk C_PiperInterface_V2.JointCtrl.
# The limits actually enforced are arm.joint_limits_deg in robot.yaml (see joint_limits()).
OFFICIAL_JOINT_LIMITS_DEG = [(-150, 150), (0, 180), (-170, 0), (-100, 100), (-70, 70), (-120, 120)]
GRIPPER_MAX_MM = 70.0
ARRIVE_TOLERANCE_DEG = 1.5
# Rest pose required before the arm is re-enabled after leaving teach mode (AgiLex
# playTrajectory_new.py): |J2| and |J3| below 10 deg, J5 between 12 and 45 deg.
REST_J23_MAX_DEG = 10.0
REST_J5_RANGE_DEG = (12.0, 45.0)
CAN_MODE_TIMEOUT_S = 5.0

ARM_STATUS = {
    0x00: "normal", 0x01: "emergency stop", 0x02: "no IK solution", 0x03: "singularity",
    0x04: "target angle over limit", 0x05: "joint communication error",
    0x06: "joint brake not released", 0x07: "collision detected", 0x08: "overspeed in teach mode",
    0x09: "joint status error", 0x0A: "other error", 0x0B: "teach record", 0x0C: "teach execute",
    0x0D: "teach pause", 0x0E: "main controller over temperature",
    0x0F: "release resistor over temperature",
}
CTRL_MODE = {0x00: "standby", 0x01: "CAN command", 0x02: "teach", 0x03: "ethernet",
             0x04: "wifi", 0x07: "offline trajectory"}


def _val(x: Any) -> Any:
    return getattr(x, "value", x)


def _at_rest(joints: list[float]) -> bool:
    return (abs(joints[1]) < REST_J23_MAX_DEG and abs(joints[2]) < REST_J23_MAX_DEG
            and REST_J5_RANGE_DEG[0] < joints[4] < REST_J5_RANGE_DEG[1])


def joint_limits() -> list[tuple[float, float]]:
    """Joint limits (deg) of the arm as mounted on the robot: arm.joint_limits_deg in robot.yaml.

    They can only narrow the official Piper limits, never widen them.
    """
    raw = config.load()["arm"].get("joint_limits_deg") or OFFICIAL_JOINT_LIMITS_DEG
    try:
        pairs = [(float(lo), float(hi)) for lo, hi in raw]
    except (TypeError, ValueError) as exc:
        raise ToolError("arm.joint_limits_deg in robot.yaml must be 6 [min, max] pairs") from exc
    if len(pairs) != 6:
        raise ToolError("arm.joint_limits_deg in robot.yaml must be 6 [min, max] pairs")
    limits = []
    for i, ((lo, hi), (off_lo, off_hi)) in enumerate(zip(pairs, OFFICIAL_JOINT_LIMITS_DEG), 1):
        lo, hi = max(lo, off_lo), min(hi, off_hi)
        if lo >= hi:
            raise ToolError(f"arm.joint_limits_deg in robot.yaml: joint {i} range is empty")
        limits.append((lo, hi))
    return limits


def validate_joints(deg: list[float]) -> list[float]:
    if len(deg) != 6:
        raise ToolError("exactly 6 joint angles (degrees) are required")
    for i, (value, (lo, hi)) in enumerate(zip(deg, joint_limits()), start=1):
        if not lo <= value <= hi:
            raise ToolError(f"joint {i} = {value} deg is outside the safe range [{lo:g}, {hi:g}] "
                            "for the arm as mounted on the robot (arm.joint_limits_deg)")
    return deg


def check_step(current: list[float], target: list[float]) -> None:
    """Refuse a move that changes any joint by more than arm.max_step_deg."""
    max_step = float(config.load()["arm"]["max_step_deg"])
    deltas = [t - c for c, t in zip(current, target)]
    worst = max(range(6), key=lambda i: abs(deltas[i]))
    if abs(deltas[worst]) > max_step:
        step = [round(c + max(-max_step, min(max_step, d)), 1) for c, d in zip(current, deltas)]
        raise ToolError(
            f"joint {worst + 1} would move {abs(deltas[worst]):.1f} deg; at most {max_step:g} deg "
            f"per command (arm.max_step_deg). Move in steps, e.g. first to "
            f"{' '.join(f'{v:g}' for v in step)}, or replay a taught trajectory (`./robot traj`)")


def require_ready(snap: dict[str, Any]) -> None:
    """Refuse commanded motion unless the arm is healthy, idle and in CAN command mode."""
    if snap["ctrl_mode"] == CTRL_MODE[0x02]:
        raise ToolError("the arm is in teach mode; the operator must short-press the teach button "
                        "to leave it, then run `./robot arm take-control`")
    if snap["arm_status"] != ARM_STATUS[0x00] or snap["errors"]:
        raise ToolError(f"the arm is not ready ({snap['arm_status']}; "
                        f"{', '.join(snap['errors']) or 'no joint errors'}); not moving")
    if snap["moving"]:
        raise ToolError("the arm is still moving; wait and check `./robot arm status`")
    if snap["ctrl_mode"] != CTRL_MODE[0x01]:
        raise ToolError(f"the arm is in {snap['ctrl_mode']} mode, not CAN command mode. Run "
                        "`./robot arm take-control` first (needed after power-on and after "
                        "teach mode)")


def clamp_speed(speed: int | None) -> int:
    settings = config.load()["arm"]
    speed = int(speed or settings["default_speed"])
    return max(1, min(speed, int(settings["max_speed"])))


@contextmanager
def motion_lock(what: str) -> Iterator[None]:
    """Only one arm-driving command at a time (arm moves, traj record/play). Stop never waits."""
    path = config.artifacts("run") / "arm.lock"
    with open(path, "a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.seek(0)
            holder = f.read().strip() or "another arm command"
            raise ToolError(f"the arm is busy ({holder}); wait for it to finish or run "
                            "`./robot arm stop`") from None
        f.seek(0)
        f.truncate()
        f.write(f"{what} (pid {os.getpid()})")
        f.flush()
        try:
            yield
        finally:
            f.seek(0)
            f.truncate()
            fcntl.flock(f, fcntl.LOCK_UN)


class PiperArm:
    def __init__(self):
        self.port = config.arm_port()
        if not Path(f"/sys/class/net/{self.port}").exists():
            raise Unavailable(
                f"CAN interface {self.port} for the arm does not exist. Check the USB-CAN "
                "adapter and piper-can.service, or have the operator activate it "
                f"(cd ~/piper_sdk/piper_sdk && bash can_activate.sh {self.port} 1000000)."
            )
        try:
            from piper_sdk import C_PiperInterface_V2
        except ImportError as exc:
            raise Unavailable(f"piper_sdk is not installed: {exc}") from exc
        self.p = C_PiperInterface_V2(self.port)
        self.p.ConnectPort()
        end = time.monotonic() + 1.5
        while self.p.GetCanFps() <= 0 and time.monotonic() < end:
            time.sleep(0.05)
        if self.p.GetCanFps() <= 0:
            self.close()
            raise Unavailable(
                f"no CAN frames from the arm on {self.port}; check arm power and wiring"
            )

    def close(self) -> None:
        try:
            self.p.DisconnectPort()
        except Exception:
            pass

    def joints_deg(self) -> list[float]:
        js = self.p.GetArmJointMsgs().joint_state
        return [round(getattr(js, f"joint_{i}") / 1000.0, 2) for i in range(1, 7)]

    def snapshot(self) -> dict[str, Any]:
        st = self.p.GetArmStatus().arm_status
        err = st.err_status
        errors = [f"joint {i} angle limit" for i in range(1, 7)
                  if getattr(err, f"joint_{i}_angle_limit", False)]
        errors += [f"joint {i} communication" for i in range(1, 7)
                   if getattr(err, f"communication_status_joint_{i}", False)]
        low = self.p.GetArmLowSpdInfoMsgs()
        motors = []
        for i in range(1, 7):
            m = getattr(low, f"motor_{i}")
            flags = [k for k, v in vars(m.foc_status).items() if v is True and not k.startswith("_")]
            motors.append({"joint": i, "motor_temp_c": m.motor_temp, "driver_temp_c": m.foc_temp,
                           "voltage_v": round(m.vol / 10.0, 1), "faults": flags})
        gripper = self.p.GetArmGripperMsgs().gripper_state
        arm_status = _val(st.arm_status)
        return {
            "can_port": self.port,
            "can_fps": round(self.p.GetCanFps(), 1),
            "enabled": list(self.p.GetArmEnableStatus()),
            "ctrl_mode": CTRL_MODE.get(_val(st.ctrl_mode), str(st.ctrl_mode)),
            "arm_status": ARM_STATUS.get(arm_status, str(st.arm_status)),
            "healthy": arm_status == 0x00 and not errors,
            "moving": _val(st.motion_status) == 0x01,
            "errors": errors,
            "joints_deg": self.joints_deg(),
            "gripper_mm": round(gripper.grippers_angle / 1000.0, 1),
            "motors": motors,
        }

    def enable(self, timeout: float = 5.0) -> None:
        end = time.monotonic() + timeout
        while not self.p.EnablePiper():
            if time.monotonic() > end:
                raise ToolError(f"the arm did not enable within {timeout:.0f}s")
            time.sleep(0.05)

    def disable(self) -> None:
        end = time.monotonic() + 5.0
        while self.p.DisablePiper() and time.monotonic() < end:
            time.sleep(0.05)

    def _send_joints(self, deg: list[float], speed: int, duration: float = 0.3) -> None:
        target = [round(d * 1000) for d in deg]
        end_send = time.monotonic() + duration
        while time.monotonic() < end_send:
            self.p.MotionCtrl_2(0x01, 0x01, speed, 0x00)  # CAN control, MOVE J
            self.p.JointCtrl(*target)
            time.sleep(0.02)

    def hold(self, speed: int) -> list[float]:
        """Stop where the arm is by commanding its current joint angles (no emergency stop)."""
        current = self.joints_deg()
        self._send_joints(current, speed)
        return current

    def move_joints(self, deg: list[float], speed: int, timeout: float = 20.0) -> list[float]:
        validate_joints(deg)
        self.enable()
        try:
            self._send_joints(deg, speed)
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                current = self.joints_deg()
                if all(abs(c - d) <= ARRIVE_TOLERANCE_DEG for c, d in zip(current, deg)):
                    return current
                status = _val(self.p.GetArmStatus().arm_status.arm_status)
                if status not in (0x00,):
                    raise ToolError(f"the arm reported: {ARM_STATUS.get(status, status)}")
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.hold(speed)
            raise
        held = self.hold(speed)
        raise ToolError(f"the arm did not reach the target within {timeout:.0f}s; it was halted "
                        f"at {', '.join(f'{v:.1f}' for v in held)} deg")

    def take_control(self, speed: int, settle_timeout: float) -> None:
        """Switch to CAN command mode the way AgiLex playTrajectory_new.py does.

        Outside CAN command mode (after power-on or teach mode) the arm is emergency-stopped,
        so it sinks slowly, until joints 2, 3 and 5 are at rest; then the stop is cleared.
        """
        st = self.p.GetArmStatus().arm_status
        if _val(st.ctrl_mode) == 0x02:
            raise ToolError("the arm is in teach mode; the operator must short-press the teach "
                            "button to leave it first")
        if _val(st.ctrl_mode) != 0x01 or _val(st.arm_status) == 0x01:
            self.p.EmergencyStop(0x01)
            time.sleep(1.0)
            end = time.monotonic() + settle_timeout
            while not _at_rest(self.joints_deg()):
                if time.monotonic() > end:
                    raise ToolError(
                        f"joints 2, 3 and 5 did not settle at rest within {settle_timeout:.0f}s "
                        f"(now {', '.join(f'{v:.1f}' for v in self.joints_deg())} deg; need "
                        f"|J2|,|J3| < {REST_J23_MAX_DEG:g} and J5 {REST_J5_RANGE_DEG[0]:g}.."
                        f"{REST_J5_RANGE_DEG[1]:g}). The arm stays emergency-stopped; the "
                        "operator can guide those joints to rest by hand and retry")
                time.sleep(0.05)
            self.p.EmergencyStop(0x02)
            time.sleep(1.0)
        end = time.monotonic() + CAN_MODE_TIMEOUT_S
        while _val(self.p.GetArmStatus().arm_status.ctrl_mode) != 0x01:
            if time.monotonic() > end:
                raise ToolError("the arm did not switch to CAN command mode; check that it has "
                                "left teach mode")
            self.p.MotionCtrl_2(0x01, 0x01, speed, 0x00)
            time.sleep(0.01)
        self.enable()

    def gripper(self, mm: float, effort: float) -> None:
        self.enable()
        self.p.GripperCtrl(round(mm * 1000), round(effort * 1000), 0x01, 0)
        time.sleep(1.0)

    def estop(self) -> None:
        self.p.EmergencyStop(0x01)

    def resume(self) -> None:
        joints = self.joints_deg()
        if not _at_rest(joints):
            raise ToolError(
                f"joints 2, 3 and 5 are not at rest ({', '.join(f'{v:.1f}' for v in joints)} deg); "
                "clearing the emergency stop now could let the arm drop. Run "
                "`./robot arm take-control`, which waits for the rest pose first")
        self.p.EmergencyStop(0x02)


class SimArm:
    """Simulated arm with state persisted between CLI calls."""

    def __init__(self):
        self.port = config.arm_port()
        self.path = config.artifacts("sim") / "arm.json"
        self.state = {"enabled": False, "estop": False, "joints_deg": [0.0] * 6, "gripper_mm": 0.0}
        if self.path.exists():
            self.state.update(json.loads(self.path.read_text()))

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.state))

    def close(self) -> None:
        self._save()

    def joints_deg(self) -> list[float]:
        return list(self.state["joints_deg"])

    def snapshot(self) -> dict[str, Any]:
        return {
            "can_port": self.port, "can_fps": 200.0,
            "enabled": [self.state["enabled"]] * 6,
            "ctrl_mode": "CAN command" if self.state["enabled"] else "standby",
            "arm_status": "emergency stop" if self.state["estop"] else "normal",
            "healthy": not self.state["estop"], "moving": False, "errors": [],
            "joints_deg": self.joints_deg(), "gripper_mm": self.state["gripper_mm"],
            "motors": [{"joint": i, "motor_temp_c": 32, "driver_temp_c": 35, "voltage_v": 24.1,
                        "faults": []} for i in range(1, 7)],
        }

    def enable(self) -> None:
        if self.state["estop"]:
            raise ToolError("the arm is emergency-stopped; run `./robot arm resume` first")
        self.state["enabled"] = True

    def disable(self) -> None:
        self.state["enabled"] = False

    def move_joints(self, deg: list[float], speed: int) -> list[float]:
        validate_joints(deg)
        self.enable()
        self.state["joints_deg"] = [float(d) for d in deg]
        return self.joints_deg()

    def take_control(self, speed: int, settle_timeout: float) -> None:
        self.state["estop"] = False
        self.enable()

    def gripper(self, mm: float, effort: float) -> None:
        self.enable()
        self.state["gripper_mm"] = mm

    def estop(self) -> None:
        self.state["estop"] = True

    def resume(self) -> None:
        self.state["estop"] = False


def open_arm():
    return SimArm() if config.is_sim() else PiperArm()


def print_snapshot(s: dict[str, Any]) -> None:
    header(f"Piper arm ({s['can_port']})")
    kv("health", "OK" if s["healthy"] else "PROBLEM")
    kv("status", s["arm_status"])
    kv("control mode", s["ctrl_mode"])
    kv("enabled joints", f"{sum(bool(e) for e in s['enabled'])}/6")
    kv("moving", s["moving"])
    kv("joints (deg)", ", ".join(f"{v:.1f}" for v in s["joints_deg"]))
    kv("gripper (mm)", s["gripper_mm"])
    kv("CAN rate (Hz)", s["can_fps"])
    temps = ", ".join(f"j{m['joint']} {m['motor_temp_c']}/{m['driver_temp_c']}C" for m in s["motors"])
    kv("motor/driver temp", temps)
    faults = [f"joint {m['joint']}: {', '.join(m['faults'])}" for m in s["motors"] if m["faults"]]
    kv("errors", "; ".join(s["errors"] + faults) or "none")


def snapshot_safe() -> dict[str, Any]:
    try:
        arm = open_arm()
    except ToolError as exc:
        return {"available": False, "can_port": config.arm_port(), "error": str(exc)}
    try:
        return {"available": True, **arm.snapshot()}
    finally:
        arm.close()


def stop() -> None:
    """Emergency-stop the arm (used by `arm stop` and `./robot estop`)."""
    arm = open_arm()
    try:
        arm.estop()
    finally:
        arm.close()
    print(f"{sim_tag()}arm: emergency stop sent")


def cmd(args) -> int:
    if args.action == "status":
        s = snapshot_safe()
        if s["available"]:
            print_snapshot(s)
        else:
            header(f"Piper arm ({s['can_port']})")
            kv("available", f"no - {s['error']}")
        return 0

    if args.action == "stop":
        try:
            stop()
        except ToolError as exc:
            print(f"arm: could not send stop - {exc}")
            return 1
        return 0

    with motion_lock(f"arm {args.action}"):
        arm = open_arm()
        try:
            _run_action(arm, args)
            print_snapshot(arm.snapshot())
        finally:
            arm.close()
    return 0


def _run_action(arm, args) -> None:
    if args.action == "enable":
        if arm.snapshot()["ctrl_mode"] == CTRL_MODE[0x02]:
            raise ToolError("the arm is in teach mode; the operator must short-press the teach "
                            "button to leave it, then run `./robot arm take-control`")
        arm.enable()
        print(f"{sim_tag()}arm enabled")
    elif args.action == "disable":
        arm.disable()
        print(f"{sim_tag()}arm disabled (motors released)")
    elif args.action == "resume":
        arm.resume()
        print(f"{sim_tag()}arm emergency stop cleared; run `./robot arm take-control` if the "
              "control mode is not CAN command")
    elif args.action == "take-control":
        if not 10 <= args.settle_wait <= 180:
            raise ToolError("--settle-wait must be between 10 and 180 seconds")
        snap = arm.snapshot()
        if snap["ctrl_mode"] == CTRL_MODE[0x02]:
            raise ToolError("the arm is in teach mode; the operator must short-press the teach "
                            "button to leave it first")
        if snap["arm_status"] != ARM_STATUS[0x01] and (
                snap["errors"] or snap["arm_status"] != ARM_STATUS[0x00]):
            raise ToolError(f"the arm reports a fault ({snap['arm_status']}; "
                            f"{', '.join(snap['errors']) or 'no joint errors'}); not taking control")
        if snap["ctrl_mode"] != CTRL_MODE[0x01] or snap["arm_status"] == ARM_STATUS[0x01]:
            print(f"{sim_tag()}arm: {snap['ctrl_mode']} mode, {snap['arm_status']} - "
                  "emergency-stopping it until joints 2, 3 and 5 settle at rest, then switching "
                  "to CAN command mode")
        arm.take_control(clamp_speed(None), args.settle_wait)
        print(f"{sim_tag()}arm: in CAN command mode and enabled")
    elif args.action in ("move-joints", "home"):
        target = args.deg if args.action == "move-joints" else config.load()["arm"]["home_deg"]
        target = validate_joints([float(v) for v in target])
        speed = clamp_speed(getattr(args, "speed", None))
        snap = arm.snapshot()
        require_ready(snap)
        before = snap["joints_deg"]
        check_step(before, target)
        print(f"{sim_tag()}arm: moving at {speed}% speed")
        print(f"  from (deg): {', '.join(f'{v:.1f}' for v in before)}")
        print(f"  to   (deg): {', '.join(f'{v:.1f}' for v in target)}")
        after = arm.move_joints(target, speed)
        print(f"  reached   : {', '.join(f'{v:.1f}' for v in after)}")
    elif args.action == "gripper":
        if not 0 <= args.mm <= GRIPPER_MAX_MM:
            raise ToolError(f"gripper opening must be between 0 and {GRIPPER_MAX_MM:.0f} mm")
        require_ready(arm.snapshot())
        arm.gripper(args.mm, args.effort)
        print(f"{sim_tag()}arm: gripper set to {args.mm} mm (effort {args.effort} N/m)")


def register(sub) -> None:
    p = sub.add_parser("arm", help="the AgileX Piper arm and its gripper")
    p.add_argument("action", choices=["status", "enable", "disable", "take-control",
                                       "move-joints", "home", "gripper", "stop", "resume"])
    p.add_argument("--deg", type=float, nargs=6, metavar="J", help="6 joint angles in degrees")
    p.add_argument("--speed", type=int, help="speed percent (capped by arm.max_speed)")
    p.add_argument("--mm", type=float, help="gripper opening in mm (0-70)")
    p.add_argument("--effort", type=float, default=1.0, help="gripper effort in N/m (0-5)")
    p.add_argument("--settle-wait", type=float, default=60.0,
                   help="take-control: s allowed for joints 2, 3 and 5 to settle at rest")
    p.set_defaults(func=_dispatch)


def _dispatch(args) -> int:
    if args.action == "move-joints" and not args.deg:
        raise ToolError("move-joints requires --deg J1 J2 J3 J4 J5 J6")
    if args.action == "gripper" and args.mm is None:
        raise ToolError("gripper requires --mm")
    if args.action == "gripper" and not 0 <= args.effort <= 5:
        raise ToolError("gripper effort must be between 0 and 5 N/m")
    return cmd(args)
