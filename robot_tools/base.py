"""Unitree B2 quadruped: state and high-level sport commands over ROS 2.

Interface (unitree_ros2): requests are unitree_api/msg/Request on /api/sport/request with
header.identity.api_id set to a B2 sport API id (unitree_sdk2 as2/sport/sport_api.hpp).
"""

from __future__ import annotations

import json
import signal
import time
from typing import Any

from . import config
from .common import ToolError, Unavailable, clamp, header, kv, sim_tag

API_ID = {
    "damp": 1001,
    "balance-stand": 1002,
    "stop": 1003,
    "stand-up": 1004,
    "stand-down": 1005,
    "recovery-stand": 1006,
    "move": 1008,
}
# SportModeState.mode values documented by Unitree for its quadrupeds.
MODES = {
    0: "idle", 1: "balance stand", 2: "pose", 3: "locomotion", 5: "lie down", 6: "joint lock",
    7: "damping", 8: "recovery stand", 10: "sit",
}
MOTOR_HOT_C = 70
MOVE_RATE_HZ = 10
RECOVERY_STAND_BLOCKED = (
    "recovery-stand is disabled on this robot: the B2 carries a Piper arm, cameras and other "
    "devices, and the recovery motion (rolling the body over and pushing up) can crush them. "
    "If the robot has fallen, ask the operator to secure or remove the payload and recover the "
    "robot by hand or with the B2 remote. (Enabled only by base.allow_recovery_stand in "
    "robot.yaml.)")


def _cfg() -> dict[str, Any]:
    return config.load()["base"]


# ----- stop requests -----
# `./robot base stop` and `./robot estop` (UI E-STOP) run in their own processes. A running
# `base move` keeps sending Move commands every 1/MOVE_RATE_HZ s, which would override their
# StopMove, so they also leave a timestamp here that the move loop checks before every command.

def _stop_file():
    return config.artifacts("run") / "base_stop"


def request_stop() -> None:
    path = _stop_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(repr(time.time()))
    tmp.replace(path)


def stop_requested_since(t0: float) -> bool:
    try:
        return float(_stop_file().read_text()) >= t0
    except (OSError, ValueError):
        return False


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def read_state(timeout: float = 2.0) -> dict[str, Any]:
    if config.is_sim():
        return SimBase().state()
    from . import ros

    cfg = _cfg()
    with ros.session("b2_state") as r:
        sport = r.wait_for(cfg["sport_state_topic"], "unitree_go/msg/SportModeState", timeout)
        low = r.wait_for(cfg["low_state_topic"], "unitree_go/msg/LowState", timeout)
    if sport is None and low is None:
        raise Unavailable(
            f"no data on {cfg['sport_state_topic']} or {cfg['low_state_topic']}. Check the "
            "Ethernet link to the B2 (192.168.123.x), ros.dds_interface in robot.yaml, and "
            "that unitree_go messages are sourced."
        )
    state: dict[str, Any] = {"reachable": True}
    if sport is not None:
        state.update({
            "mode": MODES.get(sport.mode, f"mode {sport.mode}"),
            "mode_id": int(sport.mode),
            "gait_type": int(sport.gait_type),
            "error_code": int(sport.error_code),
            "body_height_m": round(float(sport.body_height), 3),
            "position_m": [round(float(v), 3) for v in sport.position],
            "velocity_mps": [round(float(v), 3) for v in sport.velocity],
            "yaw_speed": round(float(sport.yaw_speed), 3),
            "rpy_deg": [round(float(v) * 57.2958, 1) for v in sport.imu_state.rpy],
            "obstacle_range_m": [round(float(v), 2) for v in sport.range_obstacle],
        })
    if low is not None:
        temps = [int(m.temperature) for m in low.motor_state[:12]]
        lost = [i for i, m in enumerate(low.motor_state[:12]) if int(m.lost)]
        state.update({
            "battery_pct": int(low.bms_state.soc),
            "battery_current_ma": int(low.bms_state.current),
            "bus_voltage_v": round(float(low.power_v), 2),
            "bus_current_a": round(float(low.power_a), 2),
            "motor_temps_c": temps,
            "max_motor_temp_c": max(temps, default=None),
            "hot_motors": [i for i, t in enumerate(temps) if t >= MOTOR_HOT_C],
            "lost_motors": lost,
            "foot_force": [int(v) for v in low.foot_force],
        })
    return state


class SimBase:
    def __init__(self):
        self.path = config.artifacts("sim") / "base.json"
        self.data = {"mode": 5, "position": [0.0, 0.0, 0.0], "yaw": 0.0}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text()))

    def state(self) -> dict[str, Any]:
        return {
            "reachable": True, "mode": MODES[self.data["mode"]], "mode_id": self.data["mode"],
            "gait_type": 0, "error_code": 0,
            "body_height_m": 0.0 if self.data["mode"] in (5, 7) else 0.55,
            "position_m": self.data["position"], "velocity_mps": [0.0, 0.0, 0.0],
            "yaw_speed": 0.0, "rpy_deg": [0.0, 0.0, round(self.data["yaw"] * 57.2958, 1)],
            "obstacle_range_m": [2.0, 2.0, 2.0, 2.0], "battery_pct": 82,
            "battery_current_ma": -3200, "bus_voltage_v": 56.4, "bus_current_a": 3.2,
            "motor_temps_c": [38] * 12, "max_motor_temp_c": 38, "hot_motors": [], "lost_motors": [],
            "foot_force": [0] * 4,
        }

    def command(self, action: str, params: dict[str, float] | None = None) -> None:
        import math

        modes = {"damp": 7, "balance-stand": 1, "stand-up": 1, "stand-down": 5,
                 "recovery-stand": 1}
        if action in modes:
            self.data["mode"] = modes[action]
        elif action == "move":
            if self.data["mode"] in (5, 7):
                raise ToolError("[SIM] robot is lying down; stand up before walking")
            yaw = self.data["yaw"] + params["vyaw"] * params["duration"]
            dx = params["vx"] * params["duration"]
            dy = params["vy"] * params["duration"]
            self.data["position"][0] += round(dx * math.cos(yaw) - dy * math.sin(yaw), 3)
            self.data["position"][1] += round(dx * math.sin(yaw) + dy * math.cos(yaw), 3)
            self.data["yaw"] = yaw
            self.data["mode"] = 1
        self.path.write_text(json.dumps(self.data))


def _request(api_id: int, parameter: str = ""):
    from . import ros

    Request = ros.message_type("unitree_api/msg/Request")
    req = Request()
    req.header.identity.id = int(time.time() * 1e6) % (2**62)
    req.header.identity.api_id = api_id
    req.parameter = parameter
    return req


def send(action: str, params: dict[str, float] | None = None) -> None:
    if action == "recovery-stand" and not _cfg().get("allow_recovery_stand", False):
        raise ToolError(RECOVERY_STAND_BLOCKED)
    if action == "stop":
        request_stop()  # first, so a running move stops within one command period
    if config.is_sim():
        SimBase().command(action, params)
        return
    from . import ros

    topic = _cfg()["sport_request_topic"]
    if action != "move":
        with ros.session("b2_sport") as r:
            matched = r.publish(topic, _request(API_ID[action]), repeat=3)
        if matched == 0:
            raise Unavailable(f"no subscriber on {topic}; the B2 sport service is not reachable")
        return

    assert params is not None
    payload = json.dumps({"x": params["vx"], "y": params["vy"], "z": params["vyaw"]})
    steps = max(1, round(params["duration"] * MOVE_RATE_HZ))
    started = time.time()
    # SIGTERM (e.g. the agent's command being cancelled) must still reach the StopMove below.
    previous = signal.signal(signal.SIGTERM, _raise_interrupt)
    try:
        with ros.session("b2_sport", signal_handlers=False) as r:
            try:
                matched = r.publish(topic, _request(API_ID["move"], payload), repeat=steps,
                                    period=1.0 / MOVE_RATE_HZ,
                                    stop=lambda: stop_requested_since(started))
            finally:
                r.publish(topic, _request(API_ID["stop"]), repeat=3, wait_subscribers=0.2)
    finally:
        signal.signal(signal.SIGTERM, previous)
    if matched == 0:
        raise Unavailable(f"no subscriber on {topic}; the B2 sport service is not reachable")
    if stop_requested_since(started):
        raise ToolError("the move was interrupted by a stop request (E-STOP or "
                        "`./robot base stop`); StopMove was sent")


def print_state(s: dict[str, Any]) -> None:
    header("Unitree B2 base")
    kv("mode", s.get("mode", "unknown"))
    kv("error code", s.get("error_code", "n/a"))
    if "battery_pct" in s:
        kv("battery", f"{s['battery_pct']}%  ({s['bus_voltage_v']} V, {s['bus_current_a']} A)")
    kv("body height (m)", s.get("body_height_m", "n/a"))
    kv("position (m)", s.get("position_m", "n/a"))
    kv("velocity (m/s)", s.get("velocity_mps", "n/a"))
    kv("roll/pitch/yaw (deg)", s.get("rpy_deg", "n/a"))
    kv("obstacle range (m)", s.get("obstacle_range_m", "n/a"))
    if "motor_temps_c" in s:
        kv("motor temps (C)", f"max {s.get('max_motor_temp_c', 'n/a')} (safe < {MOTOR_HOT_C}), "
                              f"hot: {s['hot_motors'] or 'none'}")
        kv("lost motors", s["lost_motors"] or "none")


def navigation_activity(listen: float = 1.0) -> tuple[int, bool]:
    """(publishers on the Nav2 velocity topic, whether a command arrived within ``listen`` s)."""
    topic = _cfg().get("nav_cmd_topic")
    if not topic or config.is_sim():
        return 0, False
    from . import ros

    with ros.session("b2_nav_check") as r:
        types = dict(r.topics(discovery=1.0)).get(topic, [])
        publishers = r.node.count_publishers(topic)
        if not publishers or not types:
            return publishers, False
        return publishers, r.wait_for(topic, types[0], listen) is not None


def preflight_navigation() -> None:
    topic = _cfg().get("nav_cmd_topic")
    publishers, active = navigation_activity()
    if active:
        raise ToolError(f"refusing to walk: navigation is sending velocity commands on {topic} "
                        "(a navigation, inspection or survey run is active). Stop that run first "
                        "so manual moves do not fight it.")
    if publishers:
        print(f"note: the navigation stack is up ({publishers} publisher(s) on {topic}) but idle")


def preflight_move(state: dict[str, Any]) -> None:
    problems = []
    if state.get("error_code"):
        problems.append(f"sport error code {state['error_code']}")
    if state.get("battery_pct", 100) < _cfg()["min_battery_pct"]:
        problems.append(f"battery {state['battery_pct']}% is below the minimum")
    if state.get("lost_motors"):
        problems.append(f"lost motors {state['lost_motors']}")
    if state.get("hot_motors"):
        problems.append(f"overheating motors {state['hot_motors']}")
    if state.get("mode_id") in (5, 6, 7):
        problems.append(f"robot is in '{state.get('mode')}' - stand up first")
    if problems:
        raise ToolError("refusing to walk: " + "; ".join(problems))


def cmd(args) -> int:
    if args.action == "state":
        print_state(read_state())
        return 0
    if args.action == "move":
        cfg = _cfg()
        params = {
            "vx": clamp(args.vx, cfg["max_vx"]),
            "vy": clamp(args.vy, cfg["max_vy"]),
            "vyaw": clamp(args.vyaw, cfg["max_vyaw"]),
            "duration": max(0.1, min(args.duration, cfg["max_duration"])),
        }
        requested = (args.vx, args.vy, args.vyaw, args.duration)
        if requested != (params["vx"], params["vy"], params["vyaw"], params["duration"]):
            print(f"note: command clamped to configured limits: {params}")
        preflight_move(read_state())
        preflight_navigation()
        print(f"{sim_tag()}B2: walking vx={params['vx']} vy={params['vy']} "
              f"vyaw={params['vyaw']} for {params['duration']}s, then stop")
        send("move", params)
    else:
        send(args.action)
        print(f"{sim_tag()}B2: sent '{args.action}' (api_id {API_ID[args.action]})")
    if args.action != "damp":
        time.sleep(0 if config.is_sim() else 1.0)
        try:
            print_state(read_state())
        except Unavailable as exc:
            print(f"state unavailable after command: {exc}")
    return 0


def register(sub) -> None:
    p = sub.add_parser("base", help="Unitree B2 quadruped")
    p.add_argument("action", choices=["state", "stand-up", "stand-down", "balance-stand",
                                       "recovery-stand", "move", "stop", "damp"])
    p.add_argument("--vx", type=float, default=0.0, help="forward speed m/s")
    p.add_argument("--vy", type=float, default=0.0, help="left speed m/s")
    p.add_argument("--vyaw", type=float, default=0.0, help="turn rate rad/s (left positive)")
    p.add_argument("--duration", type=float, default=1.0, help="seconds (capped)")
    p.set_defaults(func=cmd)
