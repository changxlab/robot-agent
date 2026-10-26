"""Robot configuration: robot.yaml merged with environment overrides."""

from __future__ import annotations

import copy
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("ROBOT_CONFIG", PROJECT_DIR / "robot.yaml"))
ARTIFACTS_DIR = Path(os.environ.get("ROBOT_ARTIFACTS", PROJECT_DIR / "artifacts"))
# Runtime mode chosen in the web UI. Precedence: ROBOT_MODE_LOCK > ROBOT_MODE > this file >
# robot.yaml. ROBOT_MODE_LOCK pins the mode for a deployment (e.g. a sim-only container).
MODE_FILE = ARTIFACTS_DIR / "run" / "mode"
MODES = ("real", "sim")

DEFAULTS: dict[str, Any] = {
    "mode": "real",
    "ros": {
        "setup_files": ["/opt/ros/humble/setup.bash"],
        "rmw_implementation": "rmw_cyclonedds_cpp",
        "dds_interface": "",
        "domain_id": 0,
    },
    "base": {
        "sport_request_topic": "/api/sport/request",
        "sport_state_topic": "/sportmodestate",
        "low_state_topic": "/lowstate",
        "nav_cmd_topic": "/cmd_vel_nav",
        "max_vx": 0.5,
        "max_vy": 0.3,
        "max_vyaw": 0.6,
        "max_duration": 3.0,
        "min_battery_pct": 15,
        "allow_recovery_stand": False,
        "require_standing_for_arm": True,
        "stand_min_height_m": 0.0,
    },
    "arm": {"can_port": "can0", "default_speed": 20, "max_speed": 50,
            "home_deg": [0, 0, 0, 0, 0, 0],
            "joint_limits_deg": [[-150, 150], [0, 180], [-170, 0], [-100, 100], [-70, 70],
                                 [-120, 120]],
            "max_step_deg": 30,
            "trajectory_dir": "~/Agilex-College/piper/recordAndPlayTraj"},
    "cameras": {},
    "mapping": {
        "backend": "command",
        "unitree": {
            "command_topic": "/qt_command",
            "command_type": "unitree_interfaces/msg/QtCommand",
            "notice_topic": "/qt_notice",
        },
        "start_cmd": "ros2 launch slam_toolbox online_async_launch.py",
        "map_topic": "/map",
        "save_cmd": "ros2 run nav2_map_server map_saver_cli -t /map -f {path}",
        "cloud_topic": "/rslidar_points",
    },
    "logs": {"paths": ["~/.ros/log"], "journal_units": []},
    "survey": {"trajectory": "survey", "camera": "orbbec_gemini", "video_seconds": 20,
               "video_fps": 10, "photos": 8, "motion_seconds": [15, 30]},
    "status": {"alert_battery_pct": 20, "alert_temp_c": 60},
    "site": {"name": "Wuxi, Jiangsu, China", "latitude": 31.49, "longitude": 120.31,
             "timezone": "Asia/Shanghai", "description": ""},
    "monitor_topics": {},
    "services": [],
}

def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    data: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        data = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    cfg = _merge(DEFAULTS, data)
    override = _mode_override()
    if override:
        cfg["mode"] = override

    env = os.environ
    if env.get("ROBOT_MODE"):
        cfg["mode"] = env["ROBOT_MODE"]
    if env.get("ROBOT_ROS_SETUP"):
        cfg["ros"]["setup_files"] = [p for p in env["ROBOT_ROS_SETUP"].split(":") if p]
    if env.get("ROBOT_DDS_INTERFACE"):
        cfg["ros"]["dds_interface"] = env["ROBOT_DDS_INTERFACE"]
    if env.get("ROBOT_MAP_START_CMD"):
        cfg["mapping"]["start_cmd"] = env["ROBOT_MAP_START_CMD"]
    if locked_mode():
        cfg["mode"] = locked_mode()

    cfg["mode"] = str(cfg["mode"]).lower()
    if cfg["mode"] not in MODES:
        raise ValueError(f"mode must be 'real' or 'sim', got {cfg['mode']!r}")
    return cfg


def locked_mode() -> str | None:
    """Mode pinned by ROBOT_MODE_LOCK; it cannot be changed at runtime (None = not locked)."""
    return os.environ.get("ROBOT_MODE_LOCK", "").strip().lower() or None


def _mode_override() -> str | None:
    try:
        return MODE_FILE.read_text().strip().lower() or None
    except OSError:
        return None


def set_mode(mode: str | None) -> None:
    """Persist the runtime mode override (None removes it, so robot.yaml applies again)."""
    if mode is None:
        MODE_FILE.unlink(missing_ok=True)
    else:
        mode = str(mode).lower()
        if mode not in MODES:
            raise ValueError(f"mode must be 'real' or 'sim', got {mode!r}")
        MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = MODE_FILE.with_suffix(".tmp")
        tmp.write_text(mode + "\n")
        tmp.replace(MODE_FILE)
    load.cache_clear()


def is_sim() -> bool:
    return load()["mode"] == "sim"


def arm_port() -> str:
    return str(load()["arm"]["can_port"])


def cameras() -> dict[str, str]:
    """Camera name -> source; the source is "" for a camera that is not set up yet.

    Sources chosen by the operator with `./robot camera set-source` (artifacts/run/
    camera_sources.json) override robot.yaml.
    """
    sources = {name: str((spec or {}).get("source") or "")
               for name, spec in load()["cameras"].items() if spec is None or isinstance(spec, dict)}
    for name, source in camera_source_overrides().items():
        if name in sources:
            sources[name] = source
    return sources


def camera_sources_file() -> Path:
    return ARTIFACTS_DIR / "run" / "camera_sources.json"


def camera_source_overrides() -> dict[str, str]:
    import json

    try:
        data = json.loads(camera_sources_file().read_text())
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def set_camera_source(name: str, source: str | None) -> None:
    """Save (or with None remove) the operator's source for camera ``name``."""
    import json

    data = camera_source_overrides()
    if source is None:
        data.pop(name, None)
    else:
        data[name] = source
    path = camera_sources_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def camera_fallback(name: str) -> str:
    """Source tried when the camera's main source is unavailable ("" = none)."""
    spec = load()["cameras"].get(name) or {}
    return str(spec.get("fallback") or "") if isinstance(spec, dict) else ""


def artifacts(sub: str) -> Path:
    path = ARTIFACTS_DIR / sub
    path.mkdir(parents=True, exist_ok=True)
    return path
