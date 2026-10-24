---
name: plant-survey
description: Plant survey with the arm camera - replay the taught survey arm motion (15-30 s) while the Orbbec Gemini camera records a 20 s video of the plants, saved as an artifact. Checks the survey motion, the arm and the camera first, and guides the operator to teach the motion or choose the camera device when missing. Use when asked to survey, scan, inspect or film plants or crops with the arm.
---

# Plant survey

The arm sweeps the Orbbec Gemini camera over the plants along a motion the operator taught by
hand; the camera records a video of the sweep.

```bash
./robot survey check                      # read-only: survey motion, arm, camera (+ test frame)
./robot survey run [--rate 1.0] [--seconds 20]   # replay the motion + record the video
./robot camera devices                    # read-only: V4L2 capture devices (to choose the camera)
./robot camera set-source --camera orbbec_gemini --source v4l2:<path>   # needs approval
```

- The survey motion is the trajectory `survey` (`survey.trajectory` in `robot.yaml`), recorded with
  the `arm-trajectory` skill. It should last 15-30 s.
- `survey run` replays it with `traj play` (same checks, limits and settle sequence) and records
  `--seconds` of video (default 20, max 20) from the survey camera (`survey.camera`, default
  `orbbec_gemini`). The video starts when the replay starts, after any settle phase. It is saved
  as `artifacts/videos/<time>_survey_orbbec_gemini.mp4` and shown in the UI (`VIDEO:` line).
- `survey run` refuses before anything moves if the motion is missing or invalid or the camera
  gives no frame.

## Workflow

Work through the steps in order. Before every step that needs the operator, tell them exactly what
to do in a short numbered list.

1. **Check.** Run `./robot survey check` and read every line.
2. **Survey motion missing** (`survey motion: MISSING`): tell the operator there is no survey motion
   yet and that they need to teach one. Then follow the `arm-trajectory` skill, section A (Record),
   with `./robot traj record --name survey --seconds 20` (15-30 s; use their length if they give
   one). In the briefing add: move the arm slowly along the plant row so the camera on the arm sees
   every plant, and finish in a safe pose. Finish step A4 (leave teach mode), then run
   `./robot survey check` again.
3. **Arm not ready**: in teach mode, ask the operator to short-press the teach button (A4 of
   `arm-trajectory`). On a fault, stop and use `robot-troubleshooting`. Do not try to clear faults
   to get the survey going.
4. **Camera not set up** (`NOT SET UP`, with a numbered list of V4L2 devices): show the operator
   the list and ask which device is the Gemini colour stream. Point out the `Orbbec` entries
   marked `colour`; a Gemini also has depth/IR nodes, which are not suitable. **End your turn and
   wait for their choice.** Then run
   `./robot camera set-source --camera orbbec_gemini --source v4l2:<chosen path>` (it takes a test
   frame first and is refused if the device gives none) and run `./robot survey check` again. If
   the camera **failed**, report the error; use `./robot camera devices` and ask the operator
   before switching to another device.
5. **Workspace.** When the check says `ready: yes`, check the space around the arm:
   `./robot camera look --camera realsense_d455 --prompt "Is the space around the arm clear of
   people and obstacles?"`.
6. **Start.** Brief the operator and issue `./robot survey run` in the same reply - the approval
   prompt is the permission step:
   > Next, after you approve:
   > 1. Keep hands and objects clear of the arm.
   > 2. If the arm is not in CAN command mode, it is first emergency-stopped and sinks slowly until
   >    joints 2, 3 and 5 rest, then re-enables (the video starts after this).
   > 3. The arm replays the survey motion (about N s) while the Gemini records 20 s of video.
   > 4. To stop at any time, press **E-STOP**.
7. **Report.** From the output: motion name and length, video file, frame count and fps, and the
   final arm status. Mention that the video is shown in the chat. You cannot watch the video - do
   not describe its content. Offer to describe the current view
   (`./robot camera look --camera orbbec_gemini --prompt "Describe plant health, leaf colour,
   pests or damage, and ripe fruit."`) or to repeat the survey (`--rate 0.5` for a slower sweep).

## Safety rules

1. `survey run` and `camera set-source` need operator approval. Say in one sentence what will
   happen, then issue the command.
2. Never run the survey without `./robot survey check` and the workspace check in the same turn.
3. Never edit trajectory CSV files or `robot.yaml` to get around a refusal, and never choose a
   camera device for the operator.
4. If playback times out or fails, run `./robot arm status`, report it and ask how to proceed - do
   not retry automatically. If anything looks wrong, run `./robot arm stop` (or `./robot estop`).
5. Output marked `[SIM]` is simulated: the survey motion is synthetic (no teach mode, so skip the
   operator steps of step 2), and the video is a simulated clip unless the camera is a real V4L2
   device. Say so.
