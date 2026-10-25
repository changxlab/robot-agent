# Piper SDK and CAN development

Checked 2026-10-25. This is a protocol/version reference, not an alternative
controller. Never send raw frames, SDK motion calls or calibration commands
to bypass the local wrapper.

## Two official SDK surfaces

| Stack | Snapshot | Applicability |
|---|---|---|
| `agilexrobotics/piper_sdk` | `b847e5393a7ce6ff8508d713eca7bdd3a42421b4`, 2026-10-14 | Legacy `C_PiperInterface_V2` and newly added V3; local wrapper uses V2 |
| `agilexrobotics/pyAgxArm` | `d90e234ba8e408cfa964b38aa9120b3131fc9f85`, 2026-10-15 | Unified multi-model API and firmware profiles; not installed/validated here |

The `piper_sdk` snapshot includes **0.7.0a1**, a prerelease. Do not call it the
latest stable installed version. Its versioning policy allows breaking changes
in 0.x minor releases when documented; pin versions and read changelogs.
Repository source revision, PyPI distribution, installed package and firmware
are separate version facts.

Legacy documentation tests Ubuntu 18.04/20.04/22.04 and Python 3.6/3.8/3.10;
`python-can` must be newer than 3.3.4. Unified `pyAgxArm` README advertises
Ubuntu through 24.04, Windows 10/11, macOS and Python through 3.14. Those are
documentation claims, not this deployment's tested support matrix.
Do not generalize legacy Linux SocketCAN setup to every newer backend.

## Firmware compatibility gates

Legacy interface documents distinguish firmware before V1.5-2 from V2-era
control. V3 adds changed message layouts for V1.8-8 and later.
**V2/V3 denotes a protocol/interface generation, not an arm hardware SKU.**

| Firmware boundary | Verified significance |
|---|---|
| V1.5-2 | V2 documentation's MOVE M/MIT and certain pendant configuration baseline |
| V1.5-8 | Maximum-joint-speed raw unit changes by factor ten |
| S-V1.6-3 | Legacy ROS documentation changes J2/J3 frame offsets by 2 degrees and URDF choice |
| V1.7-4 | Legacy SDK documents master-arm home request |
| V1.8-1 | V2 ModeCtrl documents CPV control mode availability |
| V1.8-8 | MOVE M changes from 0x04 to 0x06; MIT torque encoding changes; V3 interface needed for changed protocol |

The unified
[Piper firmware reference](https://github.com/agilexrobotics/pyAgxArm/blob/d90e234ba8e408cfa964b38aa9120b3131fc9f85/docs/piper/firmware_reference.md)
uses this driver-profile mapping:

| Reported firmware | `PiperFW` profile |
|---|---|
| S-V1.8-2 or earlier | `DEFAULT` |
| S-V1.8-3 through S-V1.8-7 | `V183` |
| S-V1.8-8 | `V188` |
| S-V1.8-9 or later | `V189` |

This is the unified driver's documented routing, not a guarantee that every
historical firmware supports every operation. Verify specific feature minima
and do not collapse these two SDKs' compatibility descriptions.
`resolve_firmware_profile()` maps reported software versions; the documented
configuration keyword is literally **`firmeware_version`**.

For PiPER-X, MIT joint 4/5 sign workarounds change at S-V1.8-9, while CPV
position sign workarounds remain. Other CPV velocity sign corrections also
depend on model. Do not duplicate a driver's corrections in the application,
or copy raw signs from another model/firmware.

## CAN transport and units

Legacy CAN docs and constructors use **1,000,000 bit/s** with Linux SocketCAN.
This is a documented setup value, not permission to reconfigure an active bus.
Inspect adapter mapping, termination, bitrate, frame freshness and active
controller ownership. Multiple devices can move under leader-follower modes.

Short protocol inventory from the pinned V2 interface:

| CAN ID | API/role | Units/critical interpretation |
|---|---|---|
| `0x150` | EmergencyStop | 0 invalid, 1 stop, 2 resume |
| `0x151` | ModeCtrl/MotionCtrl_2 | Control source, motion mode, speed percentage and MIT selection are distinct fields |
| `0x152`-`0x154` | EndPoseCtrl | Translation 0.001 mm; orientation 0.001 degree |
| `0x155`-`0x157` | JointCtrl | Joint targets 0.001 degree |
| `0x159` | V2 GripperCtrl | Opening 0.001 mm; torque 0.001 N m; separate enable/error/zero fields |
| `0x15A`-`0x15F` | JointMitCtrl | Per-joint advanced control; V2/V3 layouts differ |
| `0x191` | Master-arm home request | Can move master and/or follower; not a read-only query |
| `0x2A1` | Arm status | Mode, arm state, teaching/motion state, trajectory and errors |
| `0x2A8` | Gripper feedback | V2 opening/torque and driver flags; V3 supports changed gripper representation |
| `0x471` | Motor enable/disable | Legacy motor selection 7 means all; do not transfer to unified API index conventions |
| `0x47D` | Pendant/gripper parameters | Range/friction configuration; not arm-wide gravity compensation |

Keep SDK control targets distinct from high-speed motor feedback: the latter
uses radian/rad/s/current-scaled quantities, not joint-command millidegrees.
Some legacy effort comments spell torque as N/m; this is dimensionally
inconsistent and must not be propagated as a physical unit guarantee.

### Maximum-speed parameter unit change

For `max_joint_spd`/`MotorMaxSpdSet`, official legacy docs state:

- Before V1.5-8: raw unit **0.001 rad/s**.
- V1.5-8 onward: raw unit **0.01 rad/s**.
- 3 rad/s would encode as 3000 versus 300 respectively.
- `0x7FFF` is documented as an invalid/sentinel value.

The example illustrates conversion only; it is not approval for 3 rad/s.
SDK 0.7.0a1 removes default speed-setting arguments to reduce unit mistakes.
Do not write persistent motor parameters without confirmed firmware and an
approved commissioning procedure.

## MIT is not a safe high-level movement shortcut

The legacy V3 changelog explicitly changes MOVE M from **0x04 to 0x06**,
removes the V2 MIT CRC nibble and expands torque-reference encoding from
8 bits to 12 bits. V2 exposes a +/-8 reference range; V3 exposes +/-16.
Those wire/API conversion ranges do not establish continuous physical joint
torque ratings or validated gain/speed settings.

The unified driver additionally applies firmware/model-dependent torque
coefficients: pre-V183 `t_ff` scaling uses b and c; V183 and later use c
before encoding. Its API torque limits are not simply interchangeable with
legacy wire-reference limits. Read its exact coefficient and firmware tables
before any engineering design; do not implement a guessed
`torque = current*k + b` conversion.

Minimum safe send rate, maximum safe bus utilization, stop-on-stale-command
behavior and watchdog reaction were not established by this survey.
Do not assume missing CAN traffic produces a safe torque decay or held pose.
MIT/CPV commissioning requires a separate approved engineering/safety process.

## Status and recovery

Legacy V2 arm-state codes include:

| Code | Meaning in pinned SDK documentation |
|---|---|
| 0x00 / 0x01 | Normal / emergency stop |
| 0x02 / 0x03 | No inverse-kinematics solution / singularity |
| 0x04 / 0x05 | Target-angle limit / joint communication abnormality |
| 0x06 / 0x07 | Brake not open / collision reported |
| 0x08 / 0x09 | Teach overspeed / abnormal joint condition |
| 0x0A | Other abnormality |
| 0x0B / 0x0C / 0x0D | Teaching record / execution / pause |
| 0x0E / 0x0F | Main-controller / release-resistor NTC over-temperature |

Check raw errors and per-joint communication/angle-limit flags, not just the
overall arm-state field. Legacy ROS README comments swap some angle-limit
and communication descriptions relative to field names/SDK documentation.
Use the exact installed decoder/message definitions and retain the discrepancy;
do not clear errors based on a comment alone.

Unified `electronic_emergency_stop()` explicitly documents slow descent with
damping when elevated. Unified `reset()` and legacy `ResetPiper()` explicitly
warn of power loss and falling. **Reset is not a hold-position recovery.**
Do not automatically reset, enable or resume a faulted/elevated arm.

The unified API documents `calibrate_joint`, installation-position and payload
configuration. Their absence from a subset of legacy docs is not proof that
calibration is impossible. Calibration changes reference frames and must not
be attempted as routine troubleshooting.

## Unit-boundary checklist

| Layer | Joint/pose convention established here |
|---|---|
| Local CLI | Joint degrees; gripper mm; speed percent |
| Legacy V2 JointCtrl / EndPoseCtrl | Integer millidegrees / micrometers |
| Local taught CSV | Joint radians; optional gripper meters; waits seconds |
| Unified `get_joint_angles` / `move_j` | Joint radians |
| Unified flange-pose documentation | Translation meters, Euler radians |
| ROS JointState | Arm radians/rad/s/N m; gripper representation is driver-specific |

Never assume a unified `move_j` call is a drop-in replacement for the legacy
integer `JointCtrl`.
See [ROS and MoveIt](./ros-and-moveit.md) for the two driver generations.
