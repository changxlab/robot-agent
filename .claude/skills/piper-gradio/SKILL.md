---
name: piper-gradio
description: Teach-and-replay session for the Piper arm with AgiLex's Gradio recorder and player logic (record.py / play.py, built into `./robot piper`) - check that the B2 is standing still, the arm and the Orbbec Gemini view, have the operator enter teach mode, start the recording on their word, save the CSV once the arm is back and still, then offer to replay it. Works the same in SIM mode. Use when the operator asks for the Gradio version, piper-gradio or `./robot piper`, wants to record and replay in one session, or needs its options - record poll interval, without the gripper, a pause between replay loops.
---

# Piper arm trajectory with the Gradio recorder/player

`./robot piper` uses the recording and replay logic of AgiLex's Gradio apps `record.py` and
`play.py` (from `~/Agilex-College/piper/recordAndPlayTraj`). That logic is ported into this
project, with the web UI removed, as `robot_tools/piper_record.py` (`Recorder`) and
`robot_tools/piper_play.py` (`Player`). They behave exactly like the originals - a test runs both
against the same fake arm and compares every command and recorded row. The tool adds the CAN
port from `robot.yaml`, the shared arm lock, joint-limit checks, speed/rate/loop caps and a time
limit on every phase. Never run the AgiLex `record.py`/`play.py` directly or start their Gradio
pages (ports 17860/17861); that would bypass these limits.

```bash
./robot piper list                               # read-only: saved trajectories
./robot piper show [--name NAME]                 # read-only: points, duration, start/end pose
./robot piper record [--name NAME] [--seconds 20] [--stop-when-still 3] [--teach-wait 30]
                     [--start-delay 3] [--poll 0.02] [--no-gripper]
./robot arm teach-button                         # SIM only: simulate a press of the teach button
./robot piper play [--name NAME] [--speed 20] [--rate 1.0] [--times 1] [--interval 1.0]
                   [--settle-wait 60] [--no-gripper]
```

- Trajectories are shared with `./robot traj` (`arm-trajectory` skill): the CSV format is the same
  and both save to `artifacts/trajectories/NAME.csv`, so either tool can replay the other's
  recordings. Without `--name`, `record` uses a timestamp name (`piper-YYYYmmdd-HHMMSS`) and
  `show`/`play` use the most recent trajectory. The recorder also keeps a timestamped session
  copy in `artifacts/trajectories/sessions/`; it is not listed or played.
- `record`: waits up to `--teach-wait` s (5-120) for teach mode (immediately if the arm is
  already in it), then `--start-delay` s (0-30) so the operator can get a grip, then records.
  Recording **ends by itself once the arm has moved and is back and still** for
  `--stop-when-still` s (default 3, 1-10), or after `--seconds` at most (1-120); with
  `--stop-when-still 0` it always records `--seconds`. It polls the joints every `--poll` s
  (0.005-0.1, default 0.02) and stores only changes, so the still end is not stored. The gripper
  opening is recorded unless `--no-gripper` is given. The CSV is saved when recording ends.
- `play`: `--speed` is the joint speed percent, capped by `arm.max_speed` (default
  `arm.default_speed`). `--rate` is the time scale, 0.1-1.0 (1.0 = recorded speed). `--times` is
  1-5 loops. `--interval` is the pause in seconds after each loop (0-5); after the last point of
  a loop the player waits this long instead of that point's recorded wait. `--no-gripper`
  replays the joints only.
- `play` refuses to run if the arm is in teach mode, reports a fault or is emergency-stopped in
  CAN command mode (run `./robot arm take-control` first). It also refuses if a point is outside
  `arm.joint_limits_deg` (+3 deg tolerance). Report the joint and row; never edit the limits or
  the CSV.
- If the arm is emergency-stopped during a replay (E-STOP in the UI, `./robot arm stop`,
  `./robot estop`), the tool notices and stops sending points. Playback fails with "the arm was
  emergency-stopped during the replay".
- **The B2 must be standing still.** `record` and `play` read the B2 state first and refuse if it
  is lying down, damped, sitting, walking or turning ("refusing arm recording/replay: the B2 is
  ..."), or if its state cannot be read. Stand it up with `./robot base stand-up`
  (`b2-locomotion` skill, needs approval) or wait until it stops. Never change
  `base.require_standing_for_arm` in `robot.yaml` to get around this; only the operator may turn
  it off, on a test bench without the B2.
- `record` and `play` hold the shared arm lock (`arm`, `traj`, `piper`). Other arm commands are
  refused as "busy" until they finish; `./robot arm stop` and `./robot estop` always work.

The operator does the physical steps. The agent cannot press the teach button or move the arm by
hand. Work through the steps below in order. Before every step that needs the operator, tell them
exactly what to do next, in a short numbered list.

## SIM mode

If `./robot arm status` is marked `[SIM]`, the arm is simulated and follows **the same flow**
(steps below), including teach mode. There is no physical teach button, so when the operator says
they pressed it, simulate the press with `./robot arm teach-button` (SIM only; it toggles teach
mode on and off and is refused on the real arm), then confirm with `./robot arm status`. Never
press it on your own - only after the operator says they pressed it. `record` then simulates the
operator guiding the arm out and back and holding it still, so the recording ends by itself; the
CSV goes to `artifacts/sim/trajectories/` and is never played on the real arm. `play` refuses in
teach mode as on the real arm, then moves the simulated arm. The B2 standing check uses the
simulated B2. Report every result as simulated.

## Session: check, teach mode, record, replay

One conversation covers the whole job. Step 1 is read-only and runs straight away; keep the
report short.

### 1. Check

Run, in this order:

1. `./robot base state` - the `posture` line must be `standing still`. If it shows `lie down`,
   `damping`, `sit` or similar, say the arm can only be used while the B2 stands, and offer to
   stand it up: say what will happen, then issue `./robot base stand-up` (approval prompt), and
   re-check. If it is `moving`, wait a few seconds and re-check; never stop or move the B2
   yourself unless the operator asks. Also report a non-zero error code or battery below 20 %.
2. `./robot arm status` - health OK, no faults. If it is already in `teach` mode, say so; in
   step 2 do not ask for the teach button, go on to step 3. A fault: stop and use `robot-troubleshooting`.
3. `./robot camera look --camera orbbec_gemini --prompt "This camera is on the robot arm. What
   is in front of the arm? Are people, plants or obstacles close to it?"` - the Gemini shows the
   space in front of the arm. If it is `not set up`, use `realsense_d455` instead and say so.

### 2. Readiness and teach mode (wait for the operator)

Report readiness in 3-4 lines (B2 posture and battery, arm status and control mode, what is in
front of the arm) and the plan (name, at most N s, gripper on/off). If anything is not ready, say
what must be fixed instead. Otherwise ask the operator to enter teach mode:
> Next:
> 1. Stand at the arm and hold it - it goes limp in teach mode.
> 2. Short-press the **teach button** on the arm base.
> 3. Tell me when the arm is in teach mode.

**End your turn.** When the operator says they pressed it (SIM: run `./robot arm teach-button`
first), run `./robot arm status`: the control mode must be `teach`. If it is not, ask them to
press the button again.

### 3. Start recording (wait for the operator)

Confirm teach mode and ask for the start:
> Teach mode is on. When you say **start**, I'll begin recording (after you approve):
> 1. Recording starts 3 s after approval - get a grip.
> 2. Guide the arm slowly through the motion, then bring it back and hold it still.
> 3. Recording ends by itself about 3 s after the arm is still (at most N s).
> Keep teach mode on until I say so.

**End your turn.** When the operator says start, issue
`./robot piper record --name NAME --seconds N` (20 s default; add `--poll`, `--no-gripper` or
`--stop-when-still` only when asked). The approval prompt follows.

### 4. Saved - leave teach mode and replay (wait for the operator)

Read the result: how recording ended, points recorded, duration, start and end joints. On "teach
mode was not detected", go back to step 2. On "no motion was recorded", the arm was not moved;
offer to retry. Then in one message:
> Saved NAME: P points, D s (`<file>`).
> To replay it: short-press the teach button again to leave teach mode (keep supporting the arm -
> it may sink slowly), then tell me **replay**. You can also ask for a slower replay, repeats or
> no gripper - or say no to finish.

**End your turn.** If the operator says no, finish with a one-line summary (trajectory name, file,
points, duration). If they want the replay (SIM: run `./robot arm teach-button` first when they
say they left teach mode), continue with step 5.

### 5. Replay

1. Re-check: `./robot base state` (standing still), `./robot arm status` (no longer `teach`; if
   it still is, ask the operator to press the teach button again), and
   `./robot camera look --camera orbbec_gemini --prompt "Is the space in front of and around the
   arm clear of people and obstacles?"`.
2. Brief and issue `./robot piper play --name NAME` (with any options the operator asked for):
   > Next, after you approve:
   > 1. Keep hands and objects clear of the arm.
   > 2. The arm is not in CAN command mode yet (always true straight after teach mode), so it is
   >    first emergency-stopped and sinks slowly until joints 2 and 3 are near 0 deg and joint 5
   >    is between 12 and 45 deg. If it stops short, guide those joints there by hand.
   > 3. The arm then re-enables and replays the motion, pausing `--interval` s after each loop.
   > 4. To stop at any time, press **E-STOP** in the UI.
3. Verify: points sent and the final status and joints from the output; then
   `./robot camera look --camera orbbec_gemini --prompt "Describe what the arm camera sees
   now."`. Compare the end pose with the recorded end pose.
4. Summary (2-3 lines): recorded NAME (points, s) - replayed OK / failed (reason), end pose.
   Offer to replay again (`--rate 0.5` slower, `--times 2 --interval 2`) or to record a new one.

## Safety rules

1. Every `record` and `play` is shown to the operator for approval. Say in one sentence what will
   happen, then issue it. The approval prompt is the permission step.
2. Never record or replay without first checking the B2 posture, the arm status and the space in
   front of the arm in this session.
3. Only the operator presses the teach button. In SIM, run `./robot arm teach-button` only right
   after the operator says they pressed it.
4. If the arm is not ready in time or playback times out, the arm may still be emergency-stopped
   (see the error text). Run `./robot arm status`, report it and ask how to proceed. Do not retry
   automatically.
5. If anything looks wrong, run `./robot arm stop` (or `./robot estop`) immediately and report.
6. Use the defaults (`--rate` 1.0 or lower, speed at most 50 %). Never edit the AgiLex apps or the
   CSV files to get around a refusal.
7. Output marked `[SIM]` is simulated: say so, and follow "SIM mode" above.
