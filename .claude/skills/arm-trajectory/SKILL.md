---
name: arm-trajectory
description: Record a continuous Piper arm trajectory by hand (teach mode) and play it back - wraps AgiLex recordTrajectory_new.py and playTrajectory_new.py. Use when the operator wants to teach, record, demonstrate, save, list, replay or repeat an arm motion.
---

# Piper arm trajectory: record by hand, then play back

`./robot traj` runs AgiLex's `recordTrajectory_new.py` and `playTrajectory_new.py`
(`~/Agilex-College/piper/recordAndPlayTraj`, `arm.trajectory_dir` in `robot.yaml`). The tool
answers the scripts' Enter prompts, sets their parameters, caps speed, checks joint limits and
puts a time limit on every run. Never run those scripts directly (`python3 ...Trajectory_new.py`).
Their prompts would hang without a keyboard, and they would bypass the limits.

```bash
./robot traj list                               # read-only: saved trajectories
./robot traj show [--name NAME]                 # read-only: points, duration, start/end pose
./robot traj record [--name NAME] [--seconds 15] [--teach-wait 30] [--start-delay 3]
./robot traj play [--name NAME] [--speed 20] [--rate 1.0] [--times 1]
```

- Trajectories are saved as `artifacts/trajectories/NAME.csv`. Without `--name`, `record` uses a
  timestamp name and `show`/`play` use the most recent trajectory.
- `record`: waits `--teach-wait` s (5-120) for the teach button. It then waits `--start-delay` s
  (0-30) so the operator can get a grip, and records for exactly `--seconds` s (1-120). Only
  changes are stored, so a still arm records nothing.
- `play`: `--speed` is the joint speed percent, capped by `arm.max_speed` (default
  `arm.default_speed`). Raise it towards 50 if the replay lags the recording. `--rate` is the
  time scale, 0.1-1.0 (1.0 = recorded speed). `--times` is 1-5 repetitions.
- `play` refuses to run if the arm is in teach mode or reports a fault, or if a point is outside
  the joint limits of the arm as mounted (`arm.joint_limits_deg` in `robot.yaml`, +3 deg
  tolerance). If that happens, report the joint and row; the operator can re-record the motion
  or, if the arm really reaches that angle safely, update the limits themselves.
- Teach-and-replay is the preferred way to move this arm: the operator guides it by hand, so the
  motion stays within what the mounted arm can physically reach. After a successful `play` the
  arm is in CAN command mode, so small `./robot arm move-joints` adjustments (`piper-arm` skill)
  work without `take-control`.
- `record` and `play` hold the arm lock while they run; other arm commands are refused as "busy"
  until they finish. `./robot arm stop` / `./robot estop` always work.

The operator does the physical steps. The agent cannot press the teach button or move the arm by
hand. Work through the steps below in order. Before every step that needs the operator, tell them
exactly what to do next, in a short numbered list.

## SIM mode

If `./robot arm status` is marked `[SIM]`, the robot is simulated. Run the same commands, and
they still need approval, but there are no physical steps:

- **Record:** say it is a simulation and that `record` creates a synthetic motion (joint 1 swings
  about ±20 deg). Do not ask the operator to press the teach button, hold or move the arm, and
  skip step A4 - do not end your turn to wait. Report the summary as a simulated recording.
- **Play:** skip the settle briefing in B2; the camera check returns a simulated image. Report the
  result as simulated.
- SIM recordings are saved apart from real ones (`artifacts/sim/trajectories/`, marked
  "simulated" in `traj list`) and are never played on the real arm. In SIM, real recordings can
  be replayed on the simulated arm.

## A. Record

1. **Check.** Run `./robot arm status`. Continue only if health is OK. If the control mode is
   already `teach`, tell the operator the arm is in teach mode and continue. Recording starts as
   soon as the button state is detected.
2. **Brief the operator, then start.** In the same reply, tell the operator what happens after
   they approve the command, then issue `./robot traj record --name NAME --seconds N`. Use the
   requested length, or 15 s by default.
   > Next, after you approve:
   > 1. Within 30 s, short-press the **teach button** on the arm base. The arm goes limp, so hold it.
   > 2. You have 3 s to get a grip. Then move the arm slowly through the motion for N s.
   >    The gripper is recorded too.
   > 3. Hold the arm still at the end. Do not press the teach button again until I say so.
3. **Report.** Read the summary: points, duration, start and end joints. On "teach mode was not
   detected", tell the operator the button wasn't pressed in time and offer to retry. On "no
   motion was recorded", the arm wasn't moved.
4. **Exit teach mode.** Tell the operator:
   > Next: short-press the teach button again to leave teach mode. The arm will hold its pose or
   > sink slowly, so keep supporting it. Tell me when done.

   Then **end your turn and wait**. This is a physical action, not an approval. When they reply,
   run `./robot arm status` and confirm the control mode is no longer `teach`. Do not issue
   `move-joints`, `home` or `gripper` now - the arm is not in CAN command mode. The next `play`
   takes control itself; otherwise use `./robot arm take-control` (`piper-arm` skill).

## B. Play

1. **Check.** Run `./robot traj show --name NAME` and `./robot arm status`. If the mode is
   `teach`, repeat step A4. Use `./robot camera look --camera realsense_d455 --prompt "Is the
   space around the arm clear of people and obstacles?"` (`robot-camera` skill) to check the
   workspace.
2. **Brief the operator, then start.** Tell the operator what will happen, then issue
   `./robot traj play --name NAME`.
   > Next, after you approve:
   > 1. Keep hands and objects clear of the arm.
   > 2. If the arm isn't in CAN command mode yet (always true straight after teach mode), it is
   >    first emergency-stopped. It sinks slowly until joints 2 and 3 are near 0 deg and joint 5
   >    is between 12 and 45 deg. If it stops short, guide those joints there by hand.
   > 3. The arm then re-enables and moves to the start pose. It pauses for the idle time
   >    recorded before your first movement, then replays the motion.
   > 4. To stop at any time, press **E-STOP** in the UI.
3. **Verify.** Read the final status and joints from the output, and take a camera image. Report
   the points sent and the end pose compared with the recorded end pose.
4. **Next.** Offer to replay it, slower (`--rate 0.5`), repeated (`--times 2`), or to record a
   new one.

## Safety rules

1. Every `record` and `play` is shown to the operator for approval. Say in one sentence what will
   happen, then issue it. The approval prompt is the permission step.
2. Never replay a trajectory without first checking the arm status and the workspace in the same
   turn.
3. If playback times out, the arm may still be emergency-stopped (see the error text). Run
   `./robot arm status`, report it and ask how to proceed. Do not retry automatically.
4. If anything looks wrong, run `./robot arm stop` (or `./robot estop`) immediately and report.
5. Use the defaults (`--rate` 1.0 or lower, speed at most 50 %). Never edit the AgiLex scripts or
   the CSV files to get around a refusal.
6. Output marked `[SIM]` is simulated: there is no teach mode, and a synthetic trajectory is
   recorded. Say so, and follow "SIM mode" above.
