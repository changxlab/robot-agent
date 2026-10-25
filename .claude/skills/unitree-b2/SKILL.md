---
name: unitree-b2
description: 'Research and explain Unitree B2 specifications, capability limits, SDK2 development, ROS 2 and DDS integration, and the official Navigation Solution: mapping, localization, navigation and troubleshooting. Use for B2 parameters, payload, endurance, firmware compatibility, developer APIs or navigation planning. Distinguish official ratings from unknown limits and local robot safety policy. Not for B2-W; delegate physical operations to existing robot operation skills.'
---

# Unitree B2: evidence-grounded development and navigation

## Purpose and boundaries

Use this skill for the four-legged **B2**, not the wheeled B2-W, Go2 or H1.
It provides a dated research baseline, not certification of the installed robot.
Never treat a published maximum, SDK method or example as permission to operate.
Do not modify the operator project, configure networks, launch motion software,
change services or move hardware as part of a documentation lookup.

This bundle is standalone. It is not automatically installed or discovered.
To install later, the operator can copy this whole `unitree-b2` directory into
a supported skill root, retaining the references. Do not install or overwrite
an existing skill without an explicit request. In this robot-agent deployment,
the application loader uses `.claude/skills/<name>/SKILL.md`; IDE skill discovery
and application skill discovery are separate mechanisms.

## Procedure

1. Establish the question: physical capability, software development, navigation
   lifecycle, integration troubleshooting, or an actual robot operation.
2. Establish variant and configuration before giving an operational answer:
   B2 versus B2-W, serial/revision, installed firmware, SDK/ROS message versions,
   navigation package/license, compute and sensor options, payload and arm pose.
   If these are unknown, mark the answer conditional; never invent their values.
3. Load the appropriate reference:
   - [Specifications and unknown limits](./references/specifications.md).
   - [Development interfaces and compatibility](./references/development.md).
   - [Official Navigation Solution](./references/navigation.md).
   - [This deployment's wrapper and safety policy](./references/local-integration.md).
   - [Unknown-limit questions and acceptance gates](./references/acceptance-checklist.md).
   - [Sources, research date and coverage](./references/sources.md).
4. Attach a primary-source URL and evidence status to each significant claim:
   **official published rating**, **official documented interface**,
   **local policy**, **inference**, or **unknown/unverified**.
   Preserve inequalities, units, optional equipment and test conditions.
   Distinguish a source's revision date from the date it was checked.
5. For "latest", recheck official product/support pages and the relevant official
   repository commit/release. Record the actual retrieved revision. If documents
   are inaccessible, say so; do not infer their contents from titles or snippets.
   A repository's newest commit does not prove installed firmware compatibility.
6. For integration, identify the existing interface and lifecycle first. Prefer
   read-only inspection; do not mix SDK2 ownership, ROS motion publishers and
   navigation controllers. Return unsupported surfaces as integration work,
   not as invented executable commands.
7. Report the answer, evidence, applicability conditions and remaining unknowns.
   If a safety-relevant bound is undocumented, recommend obtaining it from
   Unitree for the robot's serial/revision rather than experimenting on hardware.

## Actual robot operations

Load the matching installed operation skill **before** any `./robot` command:

| Intent | Required skill |
|---|---|
| Health/pre-motion checks | `robot-status` |
| Stand, walk, turn, base stop, emergency stop | `b2-locomotion` |
| Mapping and saving maps | `robot-mapping` |
| Scene/path inspection | `robot-camera` |
| Diagnose faults | `robot-troubleshooting`, then `robot-logs` as needed |
| Mounted arm/gripper | `piper-arm` |

Read-only checks can run immediately. Before movement, check real status and
surroundings and account for the mounted arm, payload, clearances and people.
State in one sentence what an approved motion will do, then invoke the wrapper;
the UI approval is the permission step. Do not seek a second chat permission.
Use small bounded steps, then verify state and camera results. Do not retry a
declined command or bypass the wrapper with SDK calls, ROS publishers or launches.
Report `[SIM]` data as simulation, never as hardware evidence.

If the operator says stop or the situation becomes unsafe, load the appropriate
operation skill if not already loaded and issue `./robot estop` immediately.
Software stop is not a safety-rated hardware emergency-stop circuit.
Never use damping as a generic emergency stop: it can collapse the robot.
Recovery-stand is disabled for this arm-equipped installation.

## Non-negotiable interpretation rules

- A speed rating is not a default command speed, guaranteed stopping distance
  or clearance requirement.
- Payload ratings do not define allowed center of mass, arm extension, dynamic
  moments, combined slope/payload/speed performance or tip-over stability.
- Endurance figures with different loads/conditions are not interchangeable.
- IP protection is not permission to immerse, pressure-wash, charge wet or expose
  unprotected payload electronics.
- SDK examples for another robot do not establish B2 support.
- A ROS 2 topic name or message definition alone does not establish a stable
  navigation protocol, compatible firmware or safe active-controller ownership.
- No verified CLI for localization, waypoint following or autonomous navigation
  exists in this deployment. Do not invent `./robot nav ...`.
