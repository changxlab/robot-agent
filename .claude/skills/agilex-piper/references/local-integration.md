# Local Piper integration

Inspected 2026-10-25. These values describe this robot-agent implementation,
not manufacturer-certified performance. Reinspect current settings before use.
No hardware was queried or moved for this research.

## Command surface

Load the installed operation skill first. The syntax references below do not
authorize motion:

```bash
./robot arm status
./robot arm take-control --settle-wait 60
./robot arm move-joints --deg J1 J2 J3 J4 J5 J6 --speed 20
./robot arm home
./robot arm gripper --mm 40 --effort 1
./robot arm enable
./robot arm disable
./robot arm stop
./robot arm resume
./robot traj list
./robot traj show --name NAME
./robot traj record --name NAME --seconds 15
./robot traj play --name NAME --speed 20 --rate 1.0 --times 1
./robot estop
```

There is one arm; no arm-name parameter is required.
The real backend uses `piper_sdk.C_PiperInterface_V2` on configured CAN `can0`,
not a ROS motion-topic adapter. SDK interface V2 is not proof of hardware model.
No pinned installed SDK version was established by the local source inspection.

## Mounted joint and motion policy

Current configuration, degrees:

| Joint | Mounted range |
|---|---|
| J1 | -90 to 90 |
| J2 | 0 to 120 |
| J3 | -120 to 0 |
| J4 | -80 to 80 |
| J5 | -65 to 65 |
| J6 | -100 to 100 |

The configuration calls these conservative/placeholder limits. They are not
a measured collision-free envelope. Never expand them or infer all combinations
are safe. The wrapper intersects configured limits with its SDK-side bounds.

- Maximum per-joint change per `move-joints`/`home`: 30 degrees.
- Default speed: 20%; configured maximum: 50%; wrapper minimum: 1%.
- Home target: six zeros. A home request can be refused by the step limit;
  it is not an unconditional safe reset trajectory.
- Ready checks: normal status, CAN command mode, no joint errors, not moving.
- A joint move waits for target completion; after 20 seconds without success,
  the wrapper halts at the current pose and fails rather than claiming success.
- Arm operations and trajectory operations share a lock. Stop bypasses the lock.
- Gripper requested opening: 0-70 mm. The wrapper sends opening and effort
  multiplied by 1000 to the SDK.

### Gripper unit ambiguity

The current CLI/operation documentation labels effort `N/m` with a 0-5 range.
That label is dimensionally distinct from N m torque. Local code's x1000
conversion alone does not establish physical units or fingertip force.
Check the version-matched official SDK/protocol reference before interpreting
the value; do not carry the local label into a hardware force specification.
This knowledge skill does not change the existing wrapper or its labels.

## Take-control and software stop

The wrapper refuses take-control while teaching. If not already ready in CAN
mode, take-control can emergency-stop the arm, wait for a rest configuration,
clear the stop and request CAN command mode.

Local rest gate:

- |J2| <10 degrees.
- |J3| <10 degrees.
- J5 strictly between 12 and 45 degrees.

If the rest gate is not reached within the configured wait, the operation fails
and leaves the arm stopped. It may require the operator's approved hands-on
recovery procedure; do not automatically retry or clear the stop.
`resume` also checks this rest gate. Stop does not lock the joints; the arm can
sink. Disable can release support and allow a drop.
This rest pose is not the same as the all-zero home target.

## Teaching and replay

The wrapper uses vendor `recordTrajectory_new.py` and `playTrajectory_new.py`
under the configured `~/Agilex-College/piper/recordAndPlayTraj` location, with
in-memory source adaptations rather than modifying the vendor scripts.

CSV layout:

```text
wait_s, j1_rad, j2_rad, j3_rad, j4_rad, j5_rad, j6_rad[, gripper_m]
```

Do not confuse this with SDK integer millidegrees/micrometers or the CLI's
degrees/mm. Local validation uses 7 or 8 numeric fields, finite nonnegative
wait, mounted joint bounds with +/-3 degree tolerance, and gripper 0-70 mm
with +/-2 mm tolerance. Validation tolerance is not permission to deliberately
command outside the nominal limits.

- Record duration 1-120 s; teach wait 5-120 s; start delay 0-30 s.
- Motion changes are recorded; no motion is an error, not a useful recording.
- Playback rate 0.1-1.0, repetitions 1-5, speed capped at 50%.
- Playback settle wait 10-180 s.
- Teach mode, blocking faults and joint errors refuse playback. Playback may
  perform its own take-control/settling sequence.
- Trajectory timing validation and joint bounds do not establish collision
  avoidance, bounded acceleration or dynamic stability with an extended arm.

Simulation persists simulated arm state without CAN/SDK use and generates
synthetic trajectories. Simulated recordings are stored separately from real
ones. Runtime/environment mode overrides exist; never infer real readiness
from sample simulation readings.

## Evidence locations

Repository-relative paths for later read-only reinspection:

- `.claude/skills/piper-arm/SKILL.md`: operating workflow and recovery caveats.
- `.claude/skills/arm-trajectory/SKILL.md`: teaching/replay workflow.
- `.claude/skills/plant-survey/SKILL.md`: survey orchestration.
- `robot_tools/arm.py`: bounds, readiness, locking, SDK calls and recovery.
- `robot_tools/trajectory.py`: CSV units, validation and record/play limits.
- `robot_tools/config.py`, `robot.yaml`: current settings and runtime mode.

The numerical policy values here are a snapshot and are subordinate to current
wrapper checks and installed operation skills.
