"""Print shell exports for the ./robot wrapper (ROS setup files, DDS settings)."""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from . import config

CYCLONE_URI = (
    "<CycloneDDS><Domain><General><Interfaces>"
    '<NetworkInterface name="{iface}" priority="default" multicast="default"/>'
    "</Interfaces></General></Domain></CycloneDDS>"
)


def main() -> None:
    cfg = config.load()
    ros = cfg["ros"]
    exports: dict[str, str] = {"ROBOT_MODE": cfg["mode"]}

    setup = [str(Path(p).expanduser()) for p in ros.get("setup_files", [])]
    exports["ROBOT_ROS_SETUP_RESOLVED"] = ":".join(setup)

    rmw = ros.get("rmw_implementation") or ""
    rmw_lib = Path("/opt/ros/humble/lib") / f"lib{rmw}.so"
    if rmw and "RMW_IMPLEMENTATION" not in os.environ and rmw_lib.exists():
        exports["RMW_IMPLEMENTATION"] = rmw

    iface = ros.get("dds_interface") or ""
    # Pinning CycloneDDS to a missing interface would prevent every ROS node from starting.
    if iface and "CYCLONEDDS_URI" not in os.environ and Path(f"/sys/class/net/{iface}").exists():
        exports["CYCLONEDDS_URI"] = CYCLONE_URI.format(iface=iface)

    if "ROS_DOMAIN_ID" not in os.environ:
        exports["ROS_DOMAIN_ID"] = str(ros.get("domain_id", 0))

    for key, value in exports.items():
        print(f"export {key}={shlex.quote(value)}")


if __name__ == "__main__":
    main()
