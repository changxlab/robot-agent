"""Overall robot health: compute, network/CAN, ROS graph, base, arm, cameras, mapping."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any

from . import arm, base, config, mapping
from .common import ToolError, emit_json, header, kv, run


def system_info() -> dict[str, Any]:
    info: dict[str, Any] = {"hostname": socket.gethostname()}
    try:
        info["load"] = [round(v, 2) for v in os.getloadavg()]
    except OSError:
        pass
    meminfo = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            meminfo[key] = int(value.split()[0])
        info["memory_used_pct"] = round(100 * (1 - meminfo["MemAvailable"] / meminfo["MemTotal"]))
    except (OSError, KeyError, ValueError):
        pass
    st = os.statvfs("/")
    info["disk_used_pct"] = round(100 * (1 - st.f_bavail / st.f_blocks))
    temps = []
    for zone in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            temps.append(int(zone.read_text()) / 1000)
        except (OSError, ValueError):
            pass
    if temps:
        info["cpu_temp_c"] = round(max(temps), 1)
    code, out = run(["nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,"
                     "memory.used,memory.total", "--format=csv,noheader,nounits"], timeout=5)
    if code == 0 and out:
        name, temp, util, used, total = [v.strip() for v in out.splitlines()[0].split(",")]
        info["gpu"] = f"{name}: {temp} C, {util}% util, {used}/{total} MiB"
    return info


def network_info() -> dict[str, Any]:
    code, out = run(["ip", "-br", "addr"], timeout=5)
    ifaces = {}
    for line in out.splitlines() if code == 0 else []:
        parts = line.split()
        if parts and parts[0] != "lo":
            ifaces[parts[0]] = {"state": parts[1], "addresses": parts[2:]}
    robot_net = [n for n, i in ifaces.items()
                 if any(a.startswith("192.168.123.") for a in i["addresses"])]
    port = config.arm_port()
    operstate = Path(f"/sys/class/net/{port}/operstate")
    can = {port: operstate.read_text().strip() if operstate.exists() else "missing"}
    return {"interfaces": ifaces, "robot_network": robot_net, "can": can,
            "dds_interface": config.load()["ros"]["dds_interface"]}


def service_info() -> dict[str, str]:
    """State of the robot's systemd services, e.g. 'active (running)' or 'not installed'."""
    result = {}
    for unit in config.load().get("services", []):
        code, out = run(["systemctl", "show", "--no-pager", "-p", "LoadState,ActiveState,SubState",
                         unit], timeout=5)
        if code != 0:
            result[unit] = f"unknown ({out.strip()[:80]})"
            continue
        props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        if props.get("LoadState") == "not-found":
            result[unit] = "not installed"
        else:
            result[unit] = f"{props.get('ActiveState', '?')} ({props.get('SubState', '?')})"
    return result


def ros_info() -> dict[str, Any]:
    from . import ros

    cfg = config.load()
    with ros.session("status") as r:
        topics = r.topics(discovery=2.0)
        nodes = r.nodes()
    expected = {
        "base state": cfg["base"]["sport_state_topic"],
        "base low state": cfg["base"]["low_state_topic"],
        "base sport api": cfg["base"]["sport_request_topic"],
        "lidar": cfg["mapping"]["cloud_topic"],
    }
    for name, source in config.cameras().items():
        kind, _, target = source.partition(":")
        if kind == "ros":
            expected[f"camera {name}"] = target
        elif kind == "unitree":
            expected[f"camera {name}"] = f"/api/{target}/response"
    return {
        "nodes": len(nodes), "topics": len(topics),
        "expected_topics": {label: topic in topics for label, topic in expected.items()},
        "monitor_topics": {f"{label} ({topic})": topic in topics
                           for label, topic in cfg.get("monitor_topics", {}).items()},
        "rmw": os.environ.get("RMW_IMPLEMENTATION", "default"),
    }


def camera_info(ros_topics: dict[str, bool] | None) -> dict[str, str]:
    result = {}
    for name, source in config.cameras().items():
        kind, _, target = source.partition(":")
        if not source:
            result[name] = "not configured"
            continue
        if kind == "v4l2":
            ok = target.isdigit() or Path(target).exists()
        elif config.is_sim():
            ok = True
        elif kind == "icamera":
            from . import icamera

            ok = icamera.usb_node() is not None
            busy = icamera.busy_reason() if ok else None
            if busy:
                result[name] = f"ok (in use: {busy})"
                continue
        else:
            ok = bool(ros_topics and ros_topics.get(f"camera {name}"))
        result[name] = "ok" if ok else "missing"
    return result


def collect() -> dict[str, Any]:
    report: dict[str, Any] = {"mode": config.load()["mode"]}
    report["system"] = system_info()
    report["network"] = network_info()
    report["services"] = service_info()
    ros_topics = None
    if config.is_sim():
        report["ros"] = {"skipped": "simulation mode"}
    else:
        try:
            report["ros"] = ros_info()
            ros_topics = report["ros"]["expected_topics"]
        except ToolError as exc:
            report["ros"] = {"error": str(exc)}
    try:
        report["base"] = base.read_state()
    except ToolError as exc:
        report["base"] = {"reachable": False, "error": str(exc)}
    report["arm"] = arm.snapshot_safe()
    report["cameras"] = camera_info(ros_topics)
    report["mapping"] = mapping._read_state() or {"running": False}
    report["summary"] = summarize(report)
    return report


def summarize(r: dict[str, Any]) -> dict[str, Any]:
    issues = []
    b = r["base"]
    if not b.get("reachable"):
        issues.append("B2 base not reachable")
    else:
        if b.get("error_code"):
            issues.append(f"B2 error code {b['error_code']}")
        if b.get("battery_pct", 100) < 25:
            issues.append(f"B2 battery low ({b['battery_pct']}%)")
        if b.get("hot_motors"):
            issues.append(f"B2 hot motors {b['hot_motors']} (max {b.get('max_motor_temp_c')} C, "
                          f"safe < {base.MOTOR_HOT_C} C)")
        if b.get("lost_motors"):
            issues.append(f"B2 lost motors {b['lost_motors']}")
    a = r["arm"]
    if not a.get("available"):
        issues.append("arm not reachable")
    elif not a.get("healthy"):
        issues.append(f"arm: {a['arm_status']} {', '.join(a['errors'])}".strip())
    for name, state in r["cameras"].items():
        if state == "missing":
            issues.append(f"camera {name} missing")
    sysinfo = r["system"]
    if sysinfo.get("disk_used_pct", 0) > 90:
        issues.append(f"disk {sysinfo['disk_used_pct']}% full")
    return {"ok": not issues, "issues": issues}


def print_report(r: dict[str, Any]) -> None:
    print(f"Robot status ({'SIMULATION' if r['mode'] == 'sim' else 'real hardware'})")
    s = r["summary"]
    print("Overall: OK" if s["ok"] else "Overall: ATTENTION NEEDED")
    for issue in s["issues"]:
        print(f"  - {issue}")

    header("Compute", real=True)
    for key, value in r["system"].items():
        kv(key, value)

    header("Network", real=True)
    net = r["network"]
    kv("robot network (192.168.123.x)", ", ".join(net["robot_network"]) or "not connected")
    kv("DDS interface", net["dds_interface"] or "default")
    kv("CAN", ", ".join(f"{k}={v}" for k, v in net["can"].items()) or "none configured")

    header("Robot services", real=True)
    for unit, state in r["services"].items():
        kv(unit, state)

    header("ROS 2")
    ros_r = r["ros"]
    if "expected_topics" in ros_r:
        kv("nodes / topics", f"{ros_r['nodes']} / {ros_r['topics']}  (rmw: {ros_r['rmw']})")
        for label, ok in ros_r["expected_topics"].items():
            kv(label, "present" if ok else "MISSING")
        for label, ok in ros_r.get("monitor_topics", {}).items():
            kv(label, "publishing" if ok else "not published (only while that system runs)")
    else:
        kv("status", ros_r.get("skipped") or ros_r.get("error"))

    if r["base"].get("reachable"):
        base.print_state(r["base"])
    else:
        header("Unitree B2 base")
        kv("reachable", f"no - {r['base'].get('error')}")

    a = r["arm"]
    if a.get("available"):
        arm.print_snapshot(a)
    else:
        header(f"Piper arm ({a['can_port']})")
        kv("available", f"no - {a['error']}")

    header("Cameras")
    for name, state in r["cameras"].items():
        kv(name, state)

    header("Mapping")
    m = r["mapping"]
    kv("running", f"yes ({m['backend']}, since {m['started']})" if m.get("backend") else "no")


def cmd(args) -> int:
    report = collect()
    if args.json:
        emit_json(report)
    else:
        print_report(report)
    return 0


def register(sub) -> None:
    p = sub.add_parser("status", help="overall robot health report")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd)
