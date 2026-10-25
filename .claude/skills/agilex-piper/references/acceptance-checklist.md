# Piper safety questions and engineering acceptance

This is a documentation checklist, not an instruction to find limits by
experimentation. Publicly undocumented is not the same as unknown to AgileX.
Ask for the manual corresponding to the arm's serial, controller and firmware.

## Required inventory

- Exact arm, controller, gripper and firmware revisions; SDK commit/package.
- CAN adapter/interface, bus bitrate, termination, wiring, power and grounding.
- Mounting orientation, base stiffness, tool mass, payload mass and centers of
  mass; camera brackets, cable routing, grasped-object swept volume.
- Joint zeros/calibration, limits, URDF/tool transform, controller mode/owner.
- Mobile-base pose/support state, dynamic stability and exclusion zone.
- Physical/software stop scope, gravity behavior and recovery procedure.

## Questions not answered by a headline payload/reach rating

| Quantity | Evidence needed |
|---|---|
| Allowed payload | Tool-inclusive mass, lever arm, orientation, dynamic moment and duty cycle |
| Repeatability/accuracy | Test method, load, speed, calibration, thermal and mounting conditions |
| Maximum safe velocity | Per-joint/TCP constraints and payload/configuration dependence |
| Acceleration/jerk | Controller limits, interpolation and trajectory timing guarantees |
| Joint torque/current | Continuous/peak distinction, thermal derating, firmware scaling |
| Gripper effort | Actuator torque versus tip force, jaw geometry and object-dependent contact |
| Joint limits | Mechanical versus firmware/software limits; zero/reference/unit consistency |
| Stop performance | Latency, residual motion, gravity descent, power-loss behavior and reset |
| CAN loss/watchdog | Timeout, queued/stale commands, reconnect policy and multi-host arbitration |
| Controller switch | Acknowledged active mode, ownership transfer and outstanding commands |
| Teach mode | Gravity compensation, supported load and behavior on enable/power loss |
| Collision protection | Actual sensing/thresholds/blind spots, false negatives and safe recovery |
| Mounted workspace | Self/B2/tool/environment collisions and base tip-over margins |
| Electrical limits | Supply tolerance, surge/current budget, connectors, fuse and hot-plug rules |
| Environment | Temperature, ingress, humidity, dust and cooling restrictions |
| Calibration | Conditions, supported tools and whether offsets/limits persist across updates |
| Trajectory persistence | File schema/version/units, timing, loop discontinuities and tool state |

## Acceptance gates

1. Match documentation, hardware, firmware, SDK and ROS packages; source
   signatures alone do not prove firmware behavior.
2. Confirm units at each boundary. Keep degrees, radians, millidegrees,
   meters, mm, micrometers, N, N m and N/m distinct.
3. Verify state freshness, enable flags, control mode, errors and target-reached
   semantics before interpreting a command acknowledgement as completion.
4. Establish a single controller owner; do not run wrapper, ROS driver, GUI,
   recording/playback scripts and raw SDK control concurrently.
5. Use offline schema/conversion/trajectory checks first. Never run motion
   examples merely to test CAN connectivity.
6. Require a site-approved staged hardware validation procedure, operator
   supervision, physical stop access and provision for gravity-induced descent.
7. Preserve mounted limits and use the installed operation skills. Missing
   wrapper functionality is engineering work, not a reason to bypass it.
8. Record actual observations and failed cases; simulation success is not
   evidence of real payload handling, collision avoidance or safe stopping.

If a safety-critical value cannot be established, leave it explicitly
unverified and do not enable the affected capability on that assumption.
