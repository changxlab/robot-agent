---
name: robot-status
description: Check the health of the robot - Unitree B2 base (mode, battery, motor temperatures, faults), AgileX Piper arm (enable state, joints, errors), the five cameras, ROS 2 graph, network/CAN links and onboard compute. Use when asked how the robot is doing, before any motion, or as the first step when something seems wrong.
---

# Robot status

Run from the project root:

```bash
./robot status
```

This prints an overall verdict, a list of issues, and one section per subsystem:

| Section | What it shows |
|---|---|
| Compute | load, memory, disk, CPU temperature, GPU |
| Network | 192.168.123.x link to the B2, DDS interface, arm CAN interface state |
| Robot services | state of `piper.service`, `piper-can.service`, `dogoo_can0_activate.service`, `icamera.service`, `dog_survey.service`, `vcopy.service` (`not installed` means the unit does not exist) |
| ROS 2 | node/topic counts; whether the expected B2, lidar (`/rslidar_points`), camera and B2 video service topics exist; whether IMU (`/dog_imu_raw`), RTK (`/fix`), SLAM odometry and Nav2 velocity (`/cmd_vel_nav`) are publishing - those only publish while their system runs, so "not published" is information, not a fault |
| Unitree B2 base | sport mode, posture (`standing still`, `moving`, or why it is not standing, e.g. `lie down`), error code, battery %, voltage, body height, pose, max motor temperature (safe < 70 C; motors at or above it are listed as hot), lost motors |
| Piper arm | health, status, enabled joints, joint angles, gripper opening, motor temperatures, faults |
| Cameras | whether each camera source is present (`b2_front`, `b2_back`, `realsense_d455`, `icamera` - `ok (in use: ...)` means another program holds it); `orbbec_gemini` shows `not configured` until its topic exists - not a fault |
| Mapping | whether a SLAM session is running |

Focused checks (faster):

```bash
./robot base state            # B2 only
./robot arm status            # Piper arm only
./robot camera list           # camera hardware, V4L2 devices, ROS image topics
./robot map status            # SLAM session, lidar and map topics
```

## Interpreting results

- Lines starting with `[SIM]` come from simulation mode, not real hardware. Say so when reporting.
- `not reachable` / `MISSING` means the interface could not be contacted. The message says which link
  to check (Ethernet to the B2, CAN adapter, camera driver). Do not guess at causes beyond it; use the
  `robot-troubleshooting` skill to investigate.
- The issues list alerts on B2 battery below 20 % and on any B2 leg motor or arm motor/driver
  above 60 C (`status.alert_battery_pct` / `status.alert_temp_c` in `robot.yaml`); report these
  to the operator.
- B2 `error code` other than 0, battery below `base.min_battery_pct` (15 %), motor temperature at
  or above 70 C, or any lost motor blocks walking.
- Arm work (`./robot piper`, `./robot survey run`) needs the B2 posture `standing still`.
- An arm `status` other than `normal` (for example `emergency stop`, `collision detected`) blocks arm motion.

For a full briefing with camera views, device checks, logs and the weather, use the
`robot-briefing` skill.

## Reporting

Lead with the overall verdict and the issues, then a short per-subsystem summary. Keep raw numbers that
matter (battery %, temperatures, error codes, joint angles).
