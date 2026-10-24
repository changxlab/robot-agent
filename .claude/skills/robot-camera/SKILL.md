---
name: robot-camera
description: See through the robot cameras (B2 front and rear cameras, RealSense D455, Orbbec Gemini RGB, iCamera) - capture still images and get a description of the scene. Use to check the robot's surroundings or path, see what the arm is holding, verify a pose after moving, or diagnose camera problems.
---

# Robot cameras

```bash
./robot camera look --camera b2_front                                   # capture + describe the scene
./robot camera look --camera b2_front --prompt "Is the path ahead clear for 1 m?"
./robot camera capture                    # capture from every set-up camera (no description)
./robot camera capture --camera realsense_d455
./robot camera record --camera b2_front --seconds 5   # short video clip (max 20 s, 15 fps)
./robot camera list                       # configured cameras, USB depth cameras, V4L2 devices, ROS image topics
./robot camera devices                    # V4L2 capture nodes: stable path, vendor, colour/depth formats
./robot camera set-source --camera orbbec_gemini --source v4l2:/dev/v4l/by-id/...   # needs approval
```

The robot has five cameras (names from `robot.yaml`):

| Name | Camera | Source |
|---|---|---|
| `b2_front` | B2 built-in front camera - use it to check the path ahead | `unitree:front_videohub` (B2 video service) |
| `b2_back` | B2 built-in rear camera - check behind before walking backwards | `unitree:back_videohub` |
| `realsense_d455` | Intel RealSense D455, colour stream | `ros:/camera/camera/color/image_raw`; falls back to `/dev/video4` when the ROS driver is not running |
| `orbbec_gemini` | Orbbec Gemini RGB (UVC colour stream) on the arm - the plant survey camera (`plant-survey` skill) | chosen by the operator with `camera set-source`; until then captures report "not set up yet" |
| `icamera` | CCJT iCAMERA multispectral camera (USB `ae86:0001`) | vendor SDK in `~/icamera_demo` |

Sources are `ros:<image topic>`, `v4l2:<device>`, `unitree:<B2 video service>` or
`icamera:<SDK dir>`. `--camera all` (the default) uses every camera that is set up.

**Choosing a source:** `camera devices` lists the V4L2 capture nodes. Show the list to the operator
and let them pick (a Gemini has colour, depth and IR nodes - only a `colour` node works for RGB);
never pick for them. `camera set-source` tests one frame, then saves the choice in
`artifacts/run/camera_sources.json`, which overrides `robot.yaml` (`--clear` removes it).

## Seeing the image

- **Use `look` whenever you need to know what is in the picture.** It captures the frame and returns
  a text description from the vision model; pass `--prompt` with the specific question (obstacles,
  object positions, gripper contents, people nearby). Base conclusions on that description.
- Every capture prints `IMAGE: artifacts/captures/<file>.jpg`. The operator's web UI shows these
  images automatically, so you do not need to describe routine captures in detail.
- `record` prints `VIDEO: artifacts/videos/<file>.mp4`; the UI plays it inline. You cannot watch a
  clip - use `look` for anything you need to describe. On real hardware the frame rate is limited by
  the camera source (the line reports the achieved fps).
- Never describe an image you have not looked at.

## Notes

- The capture line says whether the frame is a `real camera frame` or a `SIMULATED image` (or
  `SIMULATED clip`). In SIM mode every camera shows a crop of a real plant photograph (crop rows,
  vegetable beds, maize; close-ups of tomatoes, lettuce and seedlings for the arm camera) picked and
  framed from the simulated B2 pose, so turning or walking changes the view; the iCamera shows an
  NDVI-like false colour of it. These photos are stand-ins, not the robot's actual view: always say
  the images are simulated and do not report them as what is in front of the robot. A `WARNING: the frame is completely dark` means the lens is covered, the privacy shutter
  is closed, or there is no light - report that rather than guessing at the scene.
- If a ROS camera times out, check that the driver is running (`./robot camera list` shows the image
  topics) and look at `./robot logs --source kernel --grep "usb|uvc"` for USB faults.
- **iCamera:** it is a 9-band multispectral sensor (624-776 nm, 752x480). The image is a vendor
  false-colour conversion of the mosaic, not a true-colour photo, and the current setup shows blur, a
  grid texture and local over-exposure - say so instead of over-interpreting colours or fine detail.
  Only one program can use it: capture is refused while `icamera.service` or `ConsumerMosaicDemo` is
  running. Do not stop that service yourself to take a picture unless the operator asks. If USB
  permission is missing, the error gives the `setfacl` command for the operator to run.
- If a B2 camera (`b2_front`, `b2_back`) gets no reply, the B2 link is down or the video service is not
  running: check the B2 network (`robot-status`) the same way as for the base.
- When verifying arm or base motion, look before and after so the change can be compared.
