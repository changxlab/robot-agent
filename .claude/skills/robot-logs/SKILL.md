---
name: robot-logs
description: Read and search robot logs - ROS 2 node logs, the system journal, kernel messages (USB, CAN, camera and driver faults), the SLAM mapping process log and the agent server log. Use when investigating errors, crashes, disconnects or unexpected robot behaviour.
---

# Robot logs

```bash
./robot logs                                   # all sources, warnings and errors, last 30 minutes
./robot logs --source kernel --since 2h        # USB / CAN / driver faults
./robot logs --source ros --level error        # ROS node errors only
./robot logs --source system --grep "orbbec|realsense"
./robot logs --unit piper-can.service --since 2h  # one robot service
./robot logs --source mapping --level all      # full SLAM process output
./robot logs --since 10m --grep "can0|can1"    # one subsystem
```

Options:

- `--source ros|system|kernel|mapping|agent|all`
- `--since 30s|15m|2h|1d` (time window)
- `--level error|warning|all` (default `warning`)
- `--unit NAME` (one systemd service; implies `--source system`)
- `--grep REGEX` (case-insensitive)
- `--lines N` (max lines per source, default 40)

Robot services on PC4 (exact names - hyphen and underscore are not interchangeable): `piper.service`,
`piper-can.service` (arm CAN link), `dogoo_can0_activate.service`, `icamera.service`,
`dog_survey.service`, `vcopy.service`. Arm record/playback over MQTT logs to
`~/Agilex-College/piper/recordAndPlayMQTT/logs/play.log` (included in `--source ros`).

Plain read-only commands such as `journalctl --no-pager -n 50 -u <unit>`, `tail -n 100 <file>`,
`grep`, `ros2 node list` and `ros2 topic echo <topic> --once` are also allowed.

## Recognising common robot faults

| Log pattern | Likely meaning |
|---|---|
| `usb ...: device not accepting address`, `error -71`, `device descriptor read` | USB device (camera or USB-CAN adapter) failing to enumerate: cable, hub power, or port |
| `can0: ... bus-off`, `ERROR-PASSIVE`, `No buffer space available` | CAN bus problem: arm power, termination, bitrate, or interface not activated |
| `uvcvideo ... Failed to ...`, `VIDIOC_` errors | camera stream failure |
| `[ERROR] ... rmw_cyclonedds` / `failed to find a free participant index` | DDS network/interface misconfiguration |
| `Traceback`, `exception`, `process has died` | a ROS node crashed; read the lines above it |

Quote the exact log lines (with timestamps) that support a conclusion, and separate what the logs
prove from what you infer.
