---
name: robot-briefing
description: Full status check and short briefing for the R&D scientist on the TCM farm in Wuxi - B2 posture (standing, lying, moving), battery and temperatures (alert below 20 % or above 60 C), what the B2 front and rear cameras see, whether the key devices are live (Piper arm, RealSense D455, Orbbec Gemini, iCamera), logs and service status when something is wrong, and today's weather in Wuxi. Use for a status check of the B2 and its devices, a start-of-day or before-work check, or "how is the robot and what is around it".
---

# Robot briefing

A read-only check of the robot and its surroundings, ending in a short briefing. Everything here
runs without approval and nothing moves. Work through the steps in order; do not narrate each
command - collect the facts, then report once.

## Context

- The robot works on a **traditional Chinese medicine (TCM) herb farm in Wuxi, Jiangsu, China**
  (`site` in `robot.yaml`). The operator is an **R&D scientist**: be precise and brief, give
  numbers with units, and separate facts from suggestions.
- Alert thresholds (`status` in `robot.yaml`): **B2 battery below 20 %**, **any B2 leg motor or
  Piper arm motor/driver above 60 C**. `./robot status` lists them as issues.

## Steps

1. **Health.** `./robot status`. From it take:
   - B2: `mode`, `posture` (`standing still`, `moving`, `lie down`, `damping`, `sit`, ...),
     error code, battery %, voltage, max motor temperature, lost motors.
   - Arm: health, status, control mode, motor/driver temperatures, faults.
   - Cameras: `ok`, `ok (in use: ...)`, `missing`, `not configured`.
   - Robot services: anything not `active` (`not installed` means the unit does not exist).
   - The issues list at the top - every issue is an alert for the briefing.
2. **Surroundings.** `./robot camera look --camera b2_front --prompt "Describe the surroundings:
   people, obstacles, crop or herb rows, the ground, and anything unusual."` and the same with
   `--camera b2_back`.
3. **Key devices live?** A device is live only if it delivers data now:
   - Piper arm - from step 1 (available, status `normal`, no faults).
   - `./robot camera capture --camera realsense_d455`, then `orbbec_gemini`, then `icamera` - a
     captured frame means live. `not set up` (Gemini without a chosen device) is "not
     configured", not down. iCamera `in use` by `icamera.service` means the service holds it -
     report it as busy, not down. A completely dark frame is a warning (lens covered, no light).
4. **If something is wrong** (an issue in step 1, a device down, a service not active) - look
   for the cause, at most 3 log reads (`robot-logs` skill):
   - `./robot logs --since 1h --level error`
   - the related service: `./robot logs --unit piper-can.service` (arm CAN),
     `--unit icamera.service`, `--unit dogoo_can0_activate.service`, ...
   - USB/CAN/camera drivers: `./robot logs --source kernel --since 1h --grep "usb|uvc|can"`

   Quote the decisive line. For a deeper diagnosis offer the `robot-troubleshooting` skill; do
   not fix anything in this skill.
5. **Weather.** `./robot weather`. If it fails (no internet), say the weather is unavailable.

## Briefing

Lead with the verdict and alerts, then one line per area. Keep it under about 12 lines.

```
**Robot: OK** (or **⚠ N alerts**) - Tue 27 Oct, 09:12, Wuxi
⚠ <alert>: <number vs threshold> - <what it means / what to do>
- B2: standing still, battery 82 % (54.9 V), motors max 41 C, no faults
- Around: front - ...; rear - ...
- Devices: arm ✓ normal (CAN command) · D455 ✓ · Gemini ✓ · iCamera ✗ down - <reason>
- Findings: <log evidence, only if something is wrong>
- Weather: overcast, 14-21 C, humidity 85 %, rain 0 % (sunrise 06:10, sunset 17:14)
<one or two sentences for the scientist>
```

- Alerts first: battery below 20 %, temperatures above 60 C, B2 error codes or lost motors, arm
  faults, devices down. With no alerts say so plainly.
- B2 moving or not standing is not a fault, but say it: arm work and the plant survey need the
  B2 standing still.
- The closing sentences are your own: relate the actual weather numbers to the day's field work
  on the herb farm - e.g. high humidity or recent rain and fungal disease pressure on the herbs,
  dry sunny hours that suit drying harvested roots or flowers, rain or strong wind as a reason to
  protect the cameras and arm, heat for the B2 battery and motors, light for camera exposure.
  Keep it practical and friendly; never present a guess as a measurement.

## Rules

1. Read-only: never move the robot, change settings or restart services in this skill. Offer the
   matching skill instead (`b2-locomotion`, `robot-troubleshooting`, ...).
2. Report only what the tools returned; never invent readings or describe images you have not
   looked at.
3. Output marked `[SIM]` is simulated - say so. The weather is real in both modes.
