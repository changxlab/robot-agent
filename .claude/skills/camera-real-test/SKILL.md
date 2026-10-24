---
name: camera-real-test
description: Dev-bench test of REAL mode with cameras only - on a development machine without the B2, arm or ROS drivers, map a plain USB webcam (icSpring WebCamera, USB 32e6:9221) onto a robot camera and check real capture, look (vision description) and video recording end to end. Use when asked to test real mode, test the cameras on the dev machine, or check the USB webcam. Never moves hardware.
---

# Real-mode camera test (dev bench)

This test exercises the real-hardware camera path of `./robot camera` on a development machine.
Only cameras are tested: the B2 base, Piper arm, mapping and ROS drivers are absent here, so
**do not run `./robot arm`, `./robot base`, `./robot traj`, `./robot map` or `./robot survey run`**
during this test. If the operator asks for them, say this is a camera-only bench.

The test camera is a USB webcam: **icSpring WebCamera, USB ID `32e6:9221`**. In
`./robot camera devices` it appears with vendor `(32e6)` and name `WebCamera`, with a stable path
like `v4l2:/dev/v4l/by-id/usb-icSpring_WebCamera_<serial>-video-index0` (colour: MJPG,YUYV). The
machine may also have a laptop `Integrated Camera` - never use that one for this test.

The webcam is mapped onto the `orbbec_gemini` camera slot (the operator-selectable RGB camera,
empty in `robot.yaml`), so the test goes through the same code path as the real Gemini.

## Steps

Run them in order and stop at the first step that fails (then go to "Troubleshooting").

1. **Mode is REAL.** `./robot camera list` - the first header must be `## Configured cameras`.
   If it is `## [SIM] Configured cameras`, stop: tell the operator to switch to REAL with the
   SIM / REAL toggle in the top bar, then continue. You cannot switch the mode yourself. (A
   `v4l2:` camera returns real frames even in SIM, so a capture in SIM mode does not test real
   mode.)
2. **Webcam is detected.** `./robot camera devices` - find the colour node with vendor `(32e6)` /
   name `WebCamera`. Use its `/dev/v4l/by-id/...-video-index0` path. If it is missing, go to
   "Troubleshooting". If there is more than one candidate, show them and ask the operator.
3. **Map the webcam onto `orbbec_gemini`** (skip if `camera list` already shows `orbbec_gemini`
   with that source). Say in one sentence that this saves the webcam as the `orbbec_gemini`
   source, then run (needs operator approval):
   `./robot camera set-source --camera orbbec_gemini --source v4l2:/dev/v4l/by-id/<webcam path>`
   It takes one test frame before saving; it must print `source set to ...` and an `IMAGE:` line.
4. **Still capture.** `./robot camera capture --camera orbbec_gemini` - the line must have no
   `[SIM]` tag and must say `real camera frame` (expected 640x480 or larger). A
   `WARNING: the frame is completely dark` means the lens is covered or there is no light.
5. **Vision description.** `./robot camera look --camera orbbec_gemini --prompt "Describe the
   scene in front of the camera in two sentences."` - it must return a description (this also
   tests the vision model through the gateway). Report what it says; it is the real view of the
   webcam, not a farm scene.
6. **Video clip.** `./robot camera record --camera orbbec_gemini --seconds 5` - it must print a
   `VIDEO:` line and `real camera clip`; note the achieved fps (a webcam usually gives 10 fps,
   the requested rate, unless the light is low).
7. **Other cameras fail cleanly.** `./robot camera capture --camera all` - the webcam frame is
   captured; the other cameras must fail fast with a clear reason, not hang. Expected on the dev
   bench (not faults):
   - `b2_front`, `b2_back`: `ROS message type unitree_api/msg/Request is not installed` or no
     reply from the B2 video service
   - `realsense_d455`: ROS topic timeout, then `video device /dev/video4 does not exist`
     (or a frame from whatever is `/dev/video4` - report it if so)
   - `icamera`: `libiCamera.so not found` or USB device missing

## Report

Lead with PASS or FAIL, then a short table: step, result, key evidence (resolution, fps, the
error line). Quote tool output; never invent results. Say clearly that the frames come from the
dev webcam, not from a robot camera.

Finish by telling the operator that the mapping stays saved in
`artifacts/run/camera_sources.json` (it also makes the webcam the plant-survey camera). To undo
it, they can ask you to run `./robot camera set-source --camera orbbec_gemini --clear` (needs
approval). Do not clear it unless asked.

## Troubleshooting

- **Webcam not in `camera devices`:** check `lsusb` for `32e6:9221` and
  `./robot logs --source kernel --since 30m --grep "usb|uvc"` for a disconnect; ask the operator
  to re-plug it (prefer a USB port directly on the PC).
- **`could not open ... (in use by another process?)`:** another program (browser, video call,
  `cheese`) holds the webcam - ask the operator to close it. Do not kill processes yourself.
- **Permission denied:** the user needs access to `/dev/video*` (the `video` group or a seat ACL);
  give the operator the command (`sudo usermod -aG video $USER`, then log in again) - do not run
  sudo.
- **`look` fails but `capture` works:** the camera is fine; the vision model or gateway is not
  reachable - report the error from `look`.
- **`set-source` declined by the operator:** do not retry; ask how they want to proceed.
