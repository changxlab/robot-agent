---
name: piper-arm
description: Read status of and control the robot's AgileX Piper arm - enable/disable motors, take control (CAN mode), small joint moves, go home, open/close the gripper, emergency-stop and resume. Use for any arm or gripper request.
---

# AgileX Piper arm

The robot has a single Piper arm (CAN port `arm.can_port` in `robot.yaml`, default `can0`).
The commands take no arm name.

**Prefer taught motions.** The arm is mounted on the robot body, so its reachable range is much
smaller than the official Piper range and a commanded joint move can hit the body or the mount.
The safest way to move the arm is to teach the motion by hand and replay it (`arm-trajectory`
skill, `./robot traj`). Use `move-joints` only for small adjustments or when the operator asks
for a specific joint pose.

```bash
./robot arm status                         # read-only
./robot arm take-control [--settle-wait 60] # switch to CAN command mode (see below)
./robot arm move-joints --deg J1 J2 J3 J4 J5 J6 [--speed 20]
./robot arm home                           # joints to arm.home_deg
./robot arm gripper --mm 40                # opening 0-70 mm, --effort 0-5 N/m (default 1)
./robot arm enable
./robot arm disable                        # releases motors - the arm drops if unsupported
./robot arm stop                           # emergency stop (always allowed)
./robot arm resume                         # clear emergency stop (only at rest; prefer take-control)
```

## Limits enforced by the tool

- **Joint limits** for the arm as mounted: `arm.joint_limits_deg` in `robot.yaml` (narrower
  than the official Piper limits). Read the current values in that file; never suggest a target
  outside them and never edit them to get around a refusal - only the operator changes them.
- **Step limit:** `move-joints` and `home` refuse to change any joint by more than
  `arm.max_step_deg` (default 30 deg) from the current pose. The error suggests an intermediate
  target; move there first, check, then continue. `home` from far away needs several steps.
- **Speed:** a percentage capped by `arm.max_speed`; default `arm.default_speed`.
- **Ready check:** `move-joints`, `home` and `gripper` refuse unless the arm is in **CAN command**
  mode, status `normal`, no joint errors and not moving.
- **One command at a time:** arm commands and `traj record/play` share a lock; a second one is
  refused with "the arm is busy". `arm stop` and `./robot estop` never wait for the lock.
- `move-joints` waits until the target is reached. If it is not reached within 20 s, the arm is
  halted where it is (it holds that pose) and the command fails.

## Control mode and take-control

`./robot arm status` shows the **control mode**:

- `CAN command` - ready for `move-joints`, `home`, `gripper`.
- `teach` - the operator is moving the arm by hand. Do not command the arm. Ask the operator to
  short-press the teach button to leave teach mode (see `arm-trajectory` step A4).
- `standby` (after power-on or after leaving teach mode) or `emergency stop` status - run
  `./robot arm take-control`. Explain before issuing it: the arm is emergency-stopped and **sinks
  slowly** until joints 2 and 3 are near 0 deg and joint 5 is between 12 and 45 deg (it already
  is when the arm rests folded); it is then re-enabled in CAN command mode. If it stops short,
  the command fails after `--settle-wait` s and the operator must guide those joints to rest by
  hand. `traj play` does the same sequence itself, so it is not needed before a replay.
  After an E-STOP the operator can also recover the arm with the **↺ Recover arm** button next
  to E-STOP in the web UI, which runs the same command.

## Safety rules

1. Every motion command is shown to the operator for approval before it runs. Explain in one sentence
   what the arm will do and why, then issue the command - the approval prompt is the permission step,
   so do not ask in chat or stop to wait.
2. Run `./robot arm status` first. Move only when health is OK, status is `normal` and the control
   mode is `CAN command`; otherwise follow "Control mode and take-control" above.
3. Prefer a taught trajectory (`arm-trajectory`) for any motion that is more than a small
   adjustment. Move in steps within `arm.max_step_deg` at the default speed unless the operator
   asks otherwise.
4. Check the workspace with a camera before and after moves (`robot-camera` skill,
   `./robot camera look --camera realsense_d455 --prompt "Is the space around the arm clear?"`).
5. If anything looks wrong, run `./robot arm stop` immediately and report. Note that the Piper
   emergency stop does not lock the joints: the arm sinks slowly, so someone may need to support it.
6. Never send raw CAN frames (`cansend`) or write scripts that drive the arm; they bypass these limits.
7. If a command is refused by the tool, report why; do not work around it. If it is denied by the
   operator, do not retry it; ask what they want instead.
