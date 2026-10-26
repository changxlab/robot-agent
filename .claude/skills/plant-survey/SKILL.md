---
name: plant-survey
description: Plant survey for the R&D researcher - check that the B2 is standing still, look around with the front and rear cameras, check the arm, the Orbbec Gemini view and the survey motion (trajectory CSV), ask the operator to start, then replay the taught survey arm motion (15-30 s) while the Gemini takes 6-10 photos spread over the motion and records a 20 s video, and report success or failure with the number of photos and the video. Guides the operator to teach the motion or choose the camera device when missing. Use when asked to survey, scan, inspect, photograph or film plants or crops with the arm.
---

# Plant survey

The arm sweeps the Orbbec Gemini camera over the plants along a motion the operator taught by
hand. During the sweep the Gemini takes still photos spread evenly over the whole motion and
records a video from the start of the motion. This is the researcher's main data collection.

```bash
./robot survey check                      # read-only: B2 posture, survey motion, arm, camera (+ test frame)
./robot survey run [--photos 8] [--rate 1.0] [--seconds 20]   # replay the motion + photos + video
./robot camera devices                    # read-only: V4L2 capture devices (to choose the camera)
./robot camera set-source --camera orbbec_gemini --source v4l2:<path>   # needs approval
```

- The survey motion is the trajectory `survey` (`survey.trajectory` in `robot.yaml`), a CSV in
  `artifacts/trajectories/survey.csv` taught by hand with `./robot traj record --name survey`
  (`arm-trajectory` skill) or `./robot piper record --name survey` (`piper-gradio` skill). It
  should last 15-30 s.
- `survey run` replays it with `traj play` (same checks, limits and settle sequence). From the
  start of the replay the survey camera (`survey.camera`, default `orbbec_gemini`):
  - takes `--photos` stills (default `survey.photos` = 8, 0-10) at evenly spaced times over the
    **whole** motion (motion length / rate), saved as
    `artifacts/captures/<time>_survey_orbbec_gemini_NN.jpg` and shown in the UI (`IMAGE:` lines);
  - records `--seconds` of video (default 20, max 20), saved as
    `artifacts/videos/<time>_survey_orbbec_gemini.mp4` (`VIDEO:` line). A 30 s motion is covered
    by the photos; the video covers the first 20 s.
- `survey run` refuses **before anything moves** if the B2 is not standing still (lying down,
  damped, sitting, walking or turning, or its state cannot be read), the motion is missing or
  outside the joint limits, or the camera gives no frame.

## Workflow

Steps 1-5 are read-only; run them straight away and keep notes short. Before every step that
needs the operator, tell them exactly what to do in a short numbered list.

1. **B2 base.** `./robot base state`. The `posture` line must be `standing still`. Lying down,
   damped or sitting: say the survey needs the B2 standing and offer `./robot base stand-up`
   (`b2-locomotion` skill; say what happens, then issue it - approval prompt), then re-check.
   Moving: wait and re-check; do not stop or move the B2 unless the operator asks. Report a
   non-zero error code, battery below 20 % or motors above 60 C.
2. **Surroundings.** `./robot camera look --camera b2_front --prompt "Describe the surroundings:
   people, obstacles, the crop rows and the ground."` and the same with `--camera b2_back`. Note
   anyone close to the robot.
3. **Arm.** `./robot arm status`. Teach mode: the operator must short-press the teach button
   (step A4 of `arm-trajectory`). A fault: stop and use `robot-troubleshooting`; never clear
   faults to get the survey going.
4. **Gemini view.** `./robot camera look --camera orbbec_gemini --prompt "This camera is on the
   robot arm. Which plants are in view? Is the space around the arm clear of people and
   obstacles?"`. If the camera is not set up, go to step 5 - it lists the devices.
5. **Survey motion and readiness.** `./robot survey check` and read every line:
   - `survey motion: MISSING` - there is no survey motion yet; the operator must teach one.
     Follow the `arm-trajectory` skill, section A (or `piper-gradio` if they ask for it) with
     `--name survey --seconds 20` (15-30 s; use their length if they give one). In the briefing
     add: move the arm slowly along the plant row so the camera sees every plant, and finish in
     a safe pose. After the operator has left teach mode, run `./robot survey check` again.
   - `motion length: WARNING` - mention it; the operator decides whether to re-teach.
   - Camera `NOT SET UP` (with a numbered list of V4L2 devices): show the list and ask which
     device is the Gemini colour stream. Point out the `Orbbec` entries marked `colour`; depth/IR
     nodes are not suitable. **End your turn and wait for their choice.** Then run
     `./robot camera set-source --camera orbbec_gemini --source v4l2:<chosen path>` and run the
     check again. Camera `FAILED`: report the error, use `./robot camera devices` and ask the
     operator before switching devices.
6. **Ask to start (wait for the operator).** When the check says `ready: yes`, give a short
   readiness report:
   > Survey ready - B2 standing still, battery B %; surroundings: ...; arm: normal; Gemini sees: ...
   > Plan: replay `survey` (D s) while the Gemini takes N photos over the motion and records a
   > 20 s video.
   > **Start the survey?**

   **End your turn.** This checkpoint is part of the survey workflow. If anything is not ready,
   list what must be fixed instead of asking.
7. **Run.** When the operator confirms, brief them and issue `./robot survey run` (add
   `--photos N` or `--rate` only when they ask) in the same reply - the approval prompt follows:
   > Next, after you approve:
   > 1. Keep hands and objects clear of the arm.
   > 2. If the arm is not in CAN command mode, it is first emergency-stopped and sinks slowly
   >    until joints 2, 3 and 5 rest, then re-enables (photos and video start after this).
   > 3. The arm replays the survey motion (about D s) while the Gemini takes N photos and
   >    records 20 s of video.
   > 4. To stop at any time, press **E-STOP**.
8. **Summary.** Report in a few lines, from the output only:
   - **Result:** succeeded, or failed - with the reason from the error.
   - **Motion:** name, length, rate.
   - **Photos:** captured count of requested (`photos: X of N captured`); they are shown in the
     chat.
   - **Video:** file name, length, frame count and fps; or why it failed.
   - **Arm:** final status and control mode.

   You cannot see the saved photos or the video - do not describe their content. Offer to
   describe the current view (`./robot camera look --camera orbbec_gemini --prompt "Describe
   plant health, leaf colour, pests or damage, and flowers or fruit."`) or to repeat the survey
   (`--rate 0.5` for a slower sweep).

## Safety rules

1. `survey run`, `base stand-up` and `camera set-source` need operator approval. Say in one
   sentence what will happen, then issue the command.
2. Never run the survey without the checks of steps 1-5 and the operator's go in step 6.
3. Never edit trajectory CSV files or `robot.yaml` to get around a refusal (including
   `base.require_standing_for_arm`), and never choose a camera device for the operator.
4. If the survey fails or times out, run `./robot arm status`, report it and ask how to proceed -
   do not retry automatically. If anything looks wrong, run `./robot arm stop` (or
   `./robot estop`).
5. Output marked `[SIM]` is simulated: the survey motion is synthetic (no teach mode, so skip the
   operator steps of step 5), and the photos and video are simulated unless the camera is a real
   V4L2 device. Say so.
