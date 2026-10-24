"""Build and save maps with the B2's SLAM (unitree_slam) or a ROS 2 SLAM launch."""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config
from .common import (ToolError, Unavailable, header, image_line, kv, pointcloud_line, run,
                     sim_tag)

# unitree_slam QtCommand.command values (unitree_slam_example/*.cpp)
QT_START_MAPPING = 3
QT_END_MAPPING = 4


def _cfg() -> dict[str, Any]:
    return config.load()["mapping"]


def _state_path() -> Path:
    return config.artifacts("run") / "mapping.json"


def _read_state() -> dict[str, Any]:
    path = _state_path()
    return json.loads(path.read_text()) if path.exists() else {}


def _write_state(state: dict[str, Any] | None) -> None:
    path = _state_path()
    if state is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(json.dumps(state, indent=2))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _valid_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", name):
        raise ToolError("map name may only contain letters, digits, '-' and '_'")
    return name


# ---------- unitree_slam backend ----------

def _qt_command(command: int) -> None:
    from . import ros

    ucfg = _cfg()["unitree"]
    Msg = ros.message_type(ucfg["command_type"])
    msg = Msg()
    values = {"command": command, "attribute": 0, "seq": int(time.time()) % 100000,
              "floor_index": 0, "pcdmap_index": 0}
    for key, value in values.items():
        for field in (key, f"{key}_"):
            if hasattr(msg, field):
                setattr(msg, field, type(getattr(msg, field))(value))
                break
    with ros.session("map_cmd") as r:
        matched = r.publish(ucfg["command_topic"], msg, repeat=2, period=0.2)
    if matched == 0:
        raise Unavailable(f"no subscriber on {ucfg['command_topic']}; is the B2 SLAM service "
                          "running?")


def _qt_notice(timeout: float = 2.0) -> str | None:
    from . import ros

    with ros.session("map_notice") as r:
        msg = r.wait_for(_cfg()["unitree"]["notice_topic"], "std_msgs/msg/String", timeout)
    return msg.data if msg is not None else None


# ---------- helpers ----------

def _map_preview(pgm: Path) -> Path | None:
    try:
        import cv2
    except ImportError:
        return None
    img = cv2.imread(str(pgm), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    png = pgm.with_suffix(".png")
    cv2.imwrite(str(png), img)
    return png


def _sim_map(name: str) -> tuple[Path, Path]:
    """Occupancy map and point-cloud map of the simulated farm; returns (png, pcd)."""
    import cv2

    from . import farm_sim

    x, y, _, _ = farm_sim.robot_pose()
    img = farm_sim.occupancy_map((x, y))
    maps = config.artifacts("maps")
    cv2.imwrite(str(maps / f"{name}.pgm"), img)
    (maps / f"{name}.yaml").write_text(
        f"image: {name}.pgm\nresolution: {farm_sim.MAP_RES}\n"
        f"origin: [{farm_sim.MAP_ORIGIN}, {farm_sim.MAP_ORIGIN}, 0.0]\n"
        "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n"
    )
    png = maps / f"{name}.png"
    cv2.imwrite(str(png), img)
    pcd = maps / f"{name}.pcd"
    farm_sim.write_pcd(pcd, *farm_sim.farm_cloud())
    return png, pcd


def _cloud_to_arrays(msg) -> tuple[Any, Any]:
    """sensor_msgs/PointCloud2 -> (xyz Nx3 float32, intensity N float32 or None), NaNs dropped."""
    import numpy as np

    types = {1: "i1", 2: "u1", 3: "i2", 4: "u2", 5: "i4", 6: "u4", 7: "f4", 8: "f8"}
    endian = ">" if msg.is_bigendian else "<"
    fields = {f.name: (f.offset, endian + types[f.datatype]) for f in msg.fields
              if f.datatype in types and f.name in ("x", "y", "z", "intensity")}
    if not all(k in fields for k in ("x", "y", "z")):
        raise ToolError("point cloud has no x/y/z fields")
    dtype = np.dtype({"names": list(fields), "formats": [f for _, f in fields.values()],
                      "offsets": [o for o, _ in fields.values()], "itemsize": msg.point_step})
    count = msg.width * msg.height
    rec = np.frombuffer(bytes(msg.data), dtype=dtype, count=count)
    xyz = np.column_stack([rec["x"], rec["y"], rec["z"]]).astype(np.float32)
    ok = np.isfinite(xyz).all(axis=1)
    inten = rec["intensity"].astype(np.float32)[ok] if "intensity" in fields else None
    return xyz[ok], inten


def _scan_path(name: str | None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return config.artifacts("pointclouds") / f"{_valid_name(name) if name else stamp + '_scan'}.pcd"


def scan(name: str | None = None) -> int:
    """Save one lidar sweep as a PCD point cloud (robot frame)."""
    from . import farm_sim

    path = _scan_path(name)
    if config.is_sim():
        x, y, yaw, _ = farm_sim.robot_pose()
        xyz, bgr, inten = farm_sim.lidar_scan(x, y, yaw)
        n = farm_sim.write_pcd(path, xyz, bgr, inten)
        print(f"[SIM] lidar scan of the simulated farm from x={x:.2f} y={y:.2f} "
              f"yaw={math.degrees(yaw):.0f} deg: {n} points (robot frame, 15 m range)")
    else:
        from . import ros

        topic = _cfg()["cloud_topic"]
        with ros.session("map_scan") as r:
            msg = r.wait_for(topic, "sensor_msgs/msg/PointCloud2", 3.0)
        if msg is None:
            raise Unavailable(f"no point cloud on {topic} within 3 s; is the lidar driver running?")
        xyz, inten = _cloud_to_arrays(msg)
        if not len(xyz):
            raise ToolError(f"the cloud on {topic} contains no valid points")
        n = farm_sim.write_pcd(path, xyz, None, inten)
        print(f"lidar scan from {topic} (frame {msg.header.frame_id}): {n} points")
    pointcloud_line(str(path.relative_to(config.PROJECT_DIR)))
    return 0


# ---------- actions ----------

def start() -> int:
    state = _read_state()
    if state and (state.get("backend") == "unitree" or _alive(state.get("pid", -1))):
        print(f"{sim_tag()}mapping is already running (started {state.get('started')})")
        return 0
    backend = "sim" if config.is_sim() else _cfg()["backend"]
    new_state: dict[str, Any] = {"backend": backend, "started": datetime.now().isoformat()}
    if backend == "sim":
        print("[SIM] mapping started")
    elif backend == "unitree":
        _qt_command(QT_START_MAPPING)
        print("B2 SLAM: start-mapping command sent (unitree_slam, command 3)")
    else:
        log_path = config.artifacts("logs") / "mapping.log"
        cmd = _cfg()["start_cmd"]
        with open(log_path, "a") as log:
            log.write(f"\n=== {datetime.now().isoformat()} starting: {cmd}\n")
            log.flush()
            proc = subprocess.Popen(shlex.split(cmd), stdout=log, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
        time.sleep(3.0)
        if proc.poll() is not None:
            raise ToolError(f"mapping process exited with code {proc.returncode}; see "
                            "`./robot logs --source mapping --level all`")
        new_state.update({"pid": proc.pid, "cmd": cmd})
        print(f"SLAM started (pid {proc.pid}): {cmd}")
    _write_state(new_state)
    print("Walk the robot slowly through the area, then run `./robot map save --name <name>`.")
    return 0


def status() -> int:
    state = _read_state()
    header("Mapping")
    if not state:
        kv("running", "no")
    else:
        kv("backend", state["backend"])
        kv("started", state["started"])
        if "pid" in state:
            kv("process", f"pid {state['pid']} {'alive' if _alive(state['pid']) else 'EXITED'}")
    if config.is_sim():
        return 0
    try:
        from . import ros

        cfg = _cfg()
        with ros.session("map_status") as r:
            cloud = r.wait_for(cfg["cloud_topic"], "sensor_msgs/msg/PointCloud2", 2.0)
            grid = r.wait_for(cfg["map_topic"], "nav_msgs/msg/OccupancyGrid", 2.0)
        kv("lidar cloud", f"{cfg['cloud_topic']} OK ({cloud.width * cloud.height} points)"
           if cloud else f"{cfg['cloud_topic']} no data")
        if grid:
            info = grid.info
            kv("map", f"{info.width}x{info.height} cells at {info.resolution:.3f} m "
                      f"({info.width * info.resolution:.1f} x {info.height * info.resolution:.1f} m)")
        else:
            kv("map", f"no {cfg['map_topic']} data")
        if state.get("backend") == "unitree":
            kv("last SLAM notice", _qt_notice() or "none received")
    except Unavailable as exc:
        kv("ROS", f"unavailable - {exc}")
    return 0


def save(name: str) -> int:
    name = _valid_name(name)
    state = _read_state()
    backend = "sim" if config.is_sim() else (state.get("backend") or _cfg()["backend"])
    if backend == "sim":
        png, pcd = _sim_map(name)
        print(f"[SIM] map '{name}' of the simulated farm saved (occupancy grid + point cloud)")
        image_line(str(png.relative_to(config.PROJECT_DIR)))
        pointcloud_line(str(pcd.relative_to(config.PROJECT_DIR)))
        return 0
    if backend == "unitree":
        _qt_command(QT_END_MAPPING)
        _write_state(None)
        notice = _qt_notice(5.0)
        print("B2 SLAM: end-mapping command sent; the point-cloud map is saved on the robot by "
              "unitree_slam (command 4).")
        print(f"SLAM notice: {notice or 'none received'}")
        return 0
    maps = config.artifacts("maps")
    target = maps / name
    cmd = _cfg()["save_cmd"].format(path=str(target))
    code, out = run(shlex.split(cmd), timeout=60)
    print(out[-2000:])
    if code != 0:
        raise ToolError(f"map save failed (exit {code})")
    png = _map_preview(target.with_suffix(".pgm"))
    print(f"map '{name}' saved to {target.relative_to(config.PROJECT_DIR)}.yaml/.pgm")
    if png:
        image_line(str(png.relative_to(config.PROJECT_DIR)))
    cloud = target.with_suffix(".pcd")
    if cloud.is_file():
        pointcloud_line(str(cloud.relative_to(config.PROJECT_DIR)))
    return 0


def stop() -> int:
    state = _read_state()
    if not state:
        print(f"{sim_tag()}mapping is not running")
        return 0
    if state["backend"] == "unitree":
        print("B2 SLAM keeps running until mapping is ended; use `./robot map save --name <name>` "
              "to end mapping and save the map.")
        return 0
    pid = state.get("pid")
    if pid and _alive(pid):
        os.killpg(pid, signal.SIGINT)
        for _ in range(50):
            if not _alive(pid):
                break
            time.sleep(0.1)
        if _alive(pid):
            os.killpg(pid, signal.SIGKILL)
    _write_state(None)
    print(f"{sim_tag()}mapping stopped")
    return 0


def list_maps() -> int:
    header("Saved maps (artifacts/maps)")
    maps = sorted(config.artifacts("maps").glob("*.yaml"))
    for m in maps:
        extra = "  (+ point cloud .pcd)" if m.with_suffix(".pcd").is_file() else ""
        kv(m.stem, datetime.fromtimestamp(m.stat().st_mtime).isoformat(timespec="seconds") + extra)
    if not maps:
        print("  none")
    return 0


def cmd(args) -> int:
    if args.action == "start":
        return start()
    if args.action == "status":
        return status()
    if args.action == "save":
        if not args.name:
            raise ToolError("save requires --name")
        return save(args.name)
    if args.action == "stop":
        return stop()
    if args.action == "scan":
        return scan(args.name)
    return list_maps()


def register(sub) -> None:
    p = sub.add_parser("map", help="SLAM mapping")
    p.add_argument("action", choices=["start", "status", "save", "stop", "list", "scan"])
    p.add_argument("--name", help="map name for save; optional file name for scan")
    p.set_defaults(func=cmd)
