---
name: robot-troubleshooting
description: Systematically diagnose robot problems - a subsystem not reachable, faults or error codes, camera or arm disconnects, ROS topics missing, DDS/network issues, failed commands. Use when the operator reports a problem or a status check shows issues.
---

# Robot troubleshooting

Work from evidence. Each step uses read-only commands, which run without approval.

1. **Scope** - `./robot status`. Note every issue and which subsystem it belongs to.
2. **Link layer** for the failing subsystem:
   - B2 base: `ip -br addr` (an interface must have a `192.168.123.x` address), `ping -c 3 <b2 ip>`,
     and `dds_interface` in the status output must match that interface.
   - Arm: `ip -details link show can0` (state UP, bitrate 1000000); `candump -n 20 can0` should show frames.
   - Cameras: `lsusb`, `./robot camera list`, `v4l2-ctl --list-devices`. The B2 front/rear cameras
     go over the B2 network link (check it as for the B2 base), not USB.
3. **ROS graph** - `ros2 node list`, `ros2 topic list`, `ros2 topic info <topic> -v`,
   `ros2 topic hz <topic>` (wrap with `timeout 5`), `ros2 topic echo <topic> --once`.
4. **Logs** - `./robot logs --source kernel --since 1h` for USB/CAN faults,
   `./robot logs --source ros --level error`, and `--grep` for the subsystem name.
5. **Correlate** timestamps between logs and when the problem began.
6. **Conclude** - state the most likely cause, the exact evidence (quoted log lines, values), and
   what you could not verify.

## Fix boundaries

- Fixes that change system state (restarting drivers, bringing up CAN interfaces, launching nodes,
  killing processes) need operator approval. Propose the exact command, explain why, and let the
  operator approve or decline.
- Physical fixes (cables, power, E-stop buttons, battery) must be done by a person; describe them
  clearly.
- `sudo`, reboots and raw hardware commands are blocked for the agent. When they are needed, give the
  operator the command to run themselves.

## Known issue patterns

| Symptom | Check |
|---|---|
| B2 topics missing | Ethernet link and 192.168.123.x address; `ros.dds_interface` in robot.yaml; `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`; unitree_ros2 workspace sourced |
| `unitree_go/msg/... is not installed` | unitree_ros2 `cyclonedds_ws` not built or not in `ros.setup_files` |
| Arm: CAN interface missing | USB-CAN adapter unplugged or not activated: check `systemctl status piper-can.service --no-pager` (it brings up the arm CAN link); manual activation is `cd ~/piper_sdk/piper_sdk && bash can_activate.sh can0 1000000` (needs sudo, operator runs it; never while an arm task is running) |
| Arm: no CAN frames | arm power off, emergency-stop button pressed, or wiring |
| Arm status `emergency stop` | `./robot arm take-control` (needs approval; waits for joints 2, 3, 5 to settle at rest, clears the stop, re-enables in CAN mode) |
| Camera capture times out | driver node not running, or USB errors (`error -71`) in the kernel log |
| iCamera: `not detected` | USB cable or power (`lsusb -d ae86:0001`) |
| iCamera: `in use` / busy | `icamera.service` or `ConsumerMosaicDemo` holds it (`systemctl status icamera.service --no-pager`); stopping it needs operator approval |
| iCamera: `no read/write permission` | the operator grants access to that one USB node with the `setfacl` command from the error |
| RealSense via `/dev/video4` fallback | the realsense2_camera ROS driver is not running; frames still work but there is no ROS topic |
| `base move` refused: navigation active | a Nav2 / inspection / survey run is publishing `/cmd_vel_nav`; the operator must stop it |
| B2 camera: no reply from the video service | B2 network link down, wrong `dds_interface`, or the B2 video service not running |
| Battery low / motors hot | stop motion and report; do not walk |
