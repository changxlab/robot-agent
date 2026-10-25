# Piper specifications and unresolved limits

Checked 2026-10-25. Source IDs are defined in [sources](./sources.md).
Numbers are manufacturer claims or SDK definitions, not measurements of the
installed B2-mounted arm. Applicable limits depend on hardware, firmware,
mounting, tool and payload.

## Manufacturer product page

Primary source P1:
[AgileX PiPER](https://global.agilex.ai/products/piper), retrieved directly.
No reliable publication/revision date was established.

| Model | DOF | Published payload | Published reach | Published arm mass |
|---|---|---|---|---|
| PiPER | 6 | 1.5 kg | 626 mm | 4.2 kg |
| PiPER-X | 6 | 1.5 kg | 669 mm | 4.5 kg |
| PiPER-L | Series comparison | 1.5 kg | 750 mm | 4.5 kg |
| PiPER-H | Series comparison | 2 kg | **636 mm** | 4.5 kg |

The product page's H reach is 636 mm. Do not substitute the 669 mm figure found
in secondary search summaries. Do not transfer the base model's full table
to L/H without the model-specific datasheet.
"PiPER Pro" was not established as a separate official model in the sources
read. Nero is a different arm family, not a seven-joint Piper variant.

The base and X technical tables both list:

| Quantity | Published value | Qualification |
|---|---|---|
| Repeatability | +/-0.1 mm | Not absolute accuracy or a guaranteed safe clearance |
| Supply | DC 24 V | Voltage tolerance/current/inrush not established |
| Communication | CAN | Version/backend specifics belong to the software docs |
| Temperature | -20 to 50 C | No complete duty/load/environment test conditions given |
| Humidity | 25-85% | Condensation qualification not established in retrieved table |
| Mounting dimension | 70 x 70 mm | Not a full bolt-pattern, bolt-grade or fastening instruction |
| J5 speed | 225 degrees/s | Does not establish other joint or TCP speed limits |

P1 lists J5 range +/-75 degrees for base PiPER and +/-90 degrees for PiPER-X.
The SDK presets below instead list +/-70 and +/-89 degrees. Preserve this
discrepancy and use the stricter verified installed limits; do not loosen the
wrapper to match marketing figures.

P1 says secure mounting, power/CAN checks, joint-zero calibration and J6 zero
after installing an end effector must precede use. These are commissioning
requirements, not instructions to recalibrate an already-installed robot.
Crucially, it states **PiPER has no automatic obstacle avoidance or sensing**.
Collision fault reporting in software does not contradict that by establishing
proactive perception or certified human collision protection.

No verified primary-source IP rating, complete power/current budget, permitted
mounting-moment envelope, cycle-life or stopping-distance specification was
obtained. Secondary claims such as average/peak power or gripper clamp force
are not promoted into this skill's specification table.

## SDK joint limits: identify the layer and units

P2 pinned
[constants.py](https://github.com/agilexrobotics/piper_sdk/blob/b847e5393a7ce6ff8508d713eca7bdd3a42421b4/piper_sdk/piper_param/constants.py)
provides model presets. These are software definitions, not a complete
mechanical safety manual.

| Joint | Base `piper`, degrees | `piper_h`, degrees | `piper_l`, degrees | `piper_x`, degrees |
|---|---|---|---|---|
| J1 | -150 to 150 | -150 to 150 | -150 to 150 | -150 to 150 |
| J2 | 0 to 180 | 0 to 180 | 0 to 180 | 0 to 180 |
| J3 | -170 to 0 | -170 to 0 | -170 to 0 | -170 to 0 |
| J4 | -100 to 100 | -135 to 135 | -127 to 127 | -89 to 89 |
| J5 | -70 to 70 | -89.5 to 89.5 | -89.5 to 89.5 | -89 to 89 |
| J6 | **degree table: -180 to 180** | -180 to 180 | -180 to 180 | -180 to 180 |

**Important same-file inconsistency:** the base `piper` radian table gives J6
`[-2.094396, 2.094396]`, approximately **+/-120 degrees**, while the degree
table gives +/-180 degrees. The alias `ROBOT_JOINT_LIMIT_PRESET` points to the
**radian** table. Do not treat these two tables as equivalent conversions.
H/L/X J6 radian entries are approximately +/-pi.

P3
[parameter manager](https://github.com/agilexrobotics/piper_sdk/blob/b847e5393a7ce6ff8508d713eca7bdd3a42421b4/piper_sdk/piper_param/piper_param_manager.py)
also uses legacy base J6 software limits of approximately +/-120 degrees and
explains that newer presets may permit +/-180. Its SDK limits are disabled
unless enabled by the interface options. Constructor defaults
`start_sdk_joint_limit=False` and `start_sdk_gripper_limit=False` are documented
in the V2 interface. Header/default presence is not an active safety guard.

Do not resolve the J6 discrepancy by selecting the larger value. The installed
wrapper's mounted J6 limit is narrower still: +/-100 degrees.
Joint limits do not establish safe interpolation, self-collision clearance,
payload stability, velocity, torque or thermal duty.

## Gripper: three different sources/objects

| Evidence | Meaning | Do not infer |
|---|---|---|
| P3 SDK `gripper_range=[0,0.07]` m | Legacy default opening 0-70 mm | Universal mechanical travel of all AgileX grippers |
| P4 legacy ROS README says actual travel 0.08 m | Documentation uses 80 mm with RViz scaling x2 | Authority to increase local 70 mm cap |
| P6 unified ROS `agx_gripper` joint range 0-0.1 m | Current end-effector adapter's total-width representation | That the old installed gripper is a 100 mm model |
| P2 V2 `GripperCtrl` effort | Encoded torque 0-5000 in 0.001 N m, i.e. 0-5 N m | Fingertip force in N |
| Local CLI effort label `N/m` | A local documentation/unit mismatch | A valid torque or force definition |

These may combine documentation inconsistency and different gripper generations.
Record exact gripper model, firmware and adapter before reconciling travel.
Teaching-pendant selectable ranges (including 70/100 mm) are configuration
fields, not proof of a particular installed mechanical stroke.

The unified ROS adapter documents gripper effort in **N**, whereas the legacy
CAN API documents **N m**. An effector driver may convert between different
representations; do not assume the same scalar or conversion. The transfer
depends on actual adapter implementation and gripper geometry.

## Mobile manipulation

Rated payload must account for gripper/tool/camera hardware and grasped object
according to the exact vendor definition; the public table does not supply
the full load-center/dynamic moment envelope. A 626 mm reach is not a safe
626 mm collision-free radius on the B2. Arm extension changes base center of
mass and tipping risk.

See [local mounted constraints](./local-integration.md) and
[questions for acceptance](./acceptance-checklist.md). Do not test unknown
limits by loading, striking, extending or driving the robot to failure.
