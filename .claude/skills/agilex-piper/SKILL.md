---
name: agilex-piper
description: 'Research and explain AgileX PiPER/Piper arm specifications, payload and workspace limits, firmware and SDK compatibility, CAN protocol units, ROS 2/MoveIt integration, gripper behavior, teaching and trajectory playback. Use for Piper capability, development, calibration or integration questions. Distinguish hardware variants, vendor ratings, unknown limits and stricter mounted-arm policy. Actual robot control belongs to piper-arm and arm-trajectory skills.'
---

# AgileX Piper: evidence-grounded arm development

## Scope

Use for Piper research, software integration and capability questions, not as
an alternative motion driver. Establish the exact arm/gripper/hardware revision
before applying a specification. A Python interface named V2 does not by itself
identify a hardware generation. Never substitute another Piper variant's limits.

This standalone bundle is not installed in the project. It can be copied later,
by the operator, into a supported skill root while retaining its references.
Do not replace the existing `piper-arm` operation skill.

## Workflow

1. Identify the requested result: specification answer, firmware/SDK compatibility,
   CAN/ROS integration, trajectory explanation, troubleshooting or actual motion.
2. Establish arm model/revision, firmware, SDK commit/version, gripper/tool,
   mounting orientation, payload mass/center of mass, active control mode and CAN
   interface. Unknown configuration means conditional answers, not guessed values.
3. Read the relevant reference:
   - [Specifications, units and missing limits](./references/specifications.md).
   - [SDK, CAN and ROS development](./references/development.md).
   - [ROS generations, kinematics and MoveIt](./references/ros-and-moveit.md).
   - [This robot's wrapper and mounted limits](./references/local-integration.md).
   - [Safety questions and acceptance gates](./references/acceptance-checklist.md).
   - [Official sources and research coverage](./references/sources.md).
4. Label important claims as **published manufacturer rating**, **verified source
   interface**, **local implementation/policy**, **inference**, or **unknown**.
   Cite the source URL and revision; preserve units, tolerances and conditions.
5. For "latest", refresh official documentation and branch/release history.
   Compare those versions to the installed firmware. Newest source does not mean
   compatible firmware or a verified supported hardware combination.
6. For engineering, establish controller ownership, units, frames, freshness,
   error/status interpretation and failure behavior before proposing an adapter.
   Start with offline tests and read-only inspection, not motion examples.
7. Return the answer with evidence, applicability and unresolved limits. Obtain
   serial/revision-specific vendor confirmation for missing safety-critical values.

## Actual operation routing

Load the matching operation skill before using its `./robot` commands:

| Intent | Skill |
|---|---|
| Whole robot readiness / mobile-base stability | `robot-status` |
| Arm/gripper status, enable, small moves, recovery, stop | `piper-arm` |
| Teach, record, show or replay a motion | `arm-trajectory` |
| Survey plants while recording camera video | `plant-survey` |
| Check arm workspace and held objects | `robot-camera` |
| Fault diagnosis and logs | `robot-troubleshooting`, `robot-logs` |
| Base posture or movement | `b2-locomotion` |

The mounted Piper can hit the B2 body or fixtures well inside its vendor joint
limits. Prefer taught motions for more than small adjustments. A valid joint
target or CSV file does not prove collision-free interpolation.

Check real status and the camera before motion; account for base posture,
stability, arm swept volume, tool, cables, payload and people. Use small bounded
steps and verify status/camera afterward. State the intended approved action in
one sentence, then call the wrapper: the UI approval is the permission step.
Do not ask for duplicate chat permission. Do not retry a declined action.

Never send raw CAN frames, run example motion scripts or publish ROS commands
to bypass the wrapper. Never loosen limits or alter firmware, zero calibration,
services, CAN configuration or project files to get around a refusal.

If asked to stop or anything is unsafe, follow the installed operation skill
and issue the appropriate stop immediately; `./robot estop` targets the arm and
base. **The Piper software stop may let the arm sink; motor disable can let it
drop.** Neither is a guaranteed gravity-holding brake or safety-rated stop.
Do not automatically resume or clear faults after a stop.
Report all `[SIM]` outputs as simulation, not hardware verification.

## Interpretation rules

- Payload ratings require tool/gripper mass and center-of-mass accounting; reach,
  maximum load and maximum speed are not proven simultaneous safe conditions.
- Repeatability is not absolute accuracy, calibration quality or collision margin.
- Speed percentage is not degrees/s, rad/s or TCP m/s.
- Gripper opening is not finger-tip force; actuator torque does not directly
  specify object-contact force. **N m and N/m are different dimensions.**
- Gripper position, joint angle and Cartesian pose may use different units at
  the CAN, SDK, ROS and wrapper layers. Convert each boundary explicitly.
- Enable, command accepted and target reached are separate observations.
- Teach-mode gravity behavior is not guaranteed passive collision protection.
- A joint limit is not a self/body/environment collision detector.
