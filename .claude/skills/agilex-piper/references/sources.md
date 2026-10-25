# Primary-source register and research coverage

Research snapshot: **2026-10-25**. Public official manufacturer pages and
official `agilexrobotics` repositories. The bundle paraphrases factual findings
and includes short interface identifiers; it does not redistribute manuals.
Dates indicate retrieved commits, not certified releases or installed firmware.

## Source register

| ID | Source | Revision / scope actually read |
|---|---|---|
| P1 | [AgileX PiPER product page](https://global.agilex.ai/products/piper) | Direct HTML retrieval on snapshot date; base/X technical tables, base/L/H/X comparison, FAQ and commissioning warning; no reliable page-update date |
| P2 | [piper_sdk pinned tree](https://github.com/agilexrobotics/piper_sdk/tree/b847e5393a7ce6ff8508d713eca7bdd3a42421b4) | Commit `b847e5393a7ce6ff8508d713eca7bdd3a42421b4`, 2026-10-14T02:38:23Z; README, interface/changelog material, CAN/dual-arm docs, parameter constants |
| P3 | [piper_param_manager.py](https://github.com/agilexrobotics/piper_sdk/blob/b847e5393a7ce6ff8508d713eca7bdd3a42421b4/piper_sdk/piper_param/piper_param_manager.py) | Same commit; defaults and documented SDK-side limits |
| P4 | [Legacy piper_ros Humble tree](https://github.com/agilexrobotics/piper_ros/tree/017ffefa64511bc6325bd77ddc4e16065c152051) | Commit `017ffefa64511bc6325bd77ddc4e16065c152051`, 2025-12-16T08:25:23Z; English README, CAN script, MoveIt guide |
| P5 | [pyAgxArm pinned tree](https://github.com/agilexrobotics/pyAgxArm/tree/d90e234ba8e408cfa964b38aa9120b3131fc9f85) | Commit `d90e234ba8e408cfa964b38aa9120b3131fc9f85`, 2026-10-15T07:31:42Z; README, Piper API selected sections and firmware-reference tables |
| P6 | [agx_arm_ros pinned tree](https://github.com/agilexrobotics/agx_arm_ros/tree/286633e0d2edb038ee3a1047d9feb7f614a1c076) | Commit `286633e0d2edb038ee3a1047d9feb7f614a1c076`, 2026-10-20T23:54:18Z; English README selected launch/topic/unit sections and MoveIt guide sections |
| P7 | [Legacy piper_ros Noetic tree](https://github.com/agilexrobotics/piper_ros/tree/ac41fcbcdda598f01b51cf6175ed9a24d0dacadc) | Commit `ac41fcbcdda598f01b51cf6175ed9a24d0dacadc`, 2026-03-04T07:36:50Z; driver README and CAN activation setup; not every service/implementation |
| L1 | Existing robot-agent arm/trajectory skills and implementation | Read-only inspection on snapshot date; current wrapper/configuration, not hardware state or vendor certification |

Detailed entry points:

- [Legacy V2 interface](https://github.com/agilexrobotics/piper_sdk/blob/b847e5393a7ce6ff8508d713eca7bdd3a42421b4/assets/V2/INTERFACE_V2.MD).
- [Legacy V3 interface](https://github.com/agilexrobotics/piper_sdk/blob/b847e5393a7ce6ff8508d713eca7bdd3a42421b4/assets/V3/INTERFACE_V3.MD)
  and [V3 changelog](https://github.com/agilexrobotics/piper_sdk/blob/b847e5393a7ce6ff8508d713eca7bdd3a42421b4/assets/V3/CHANGELOG-V3.MD).
- [SDK constants, including conflicting J6 tables](https://github.com/agilexrobotics/piper_sdk/blob/b847e5393a7ce6ff8508d713eca7bdd3a42421b4/piper_sdk/piper_param/constants.py).
- [SDK versioning policy](https://github.com/agilexrobotics/piper_sdk/blob/b847e5393a7ce6ff8508d713eca7bdd3a42421b4/assets/versioning_policy.MD),
  selected 0.x/prerelease-policy sections checked.
- [Unified Piper API](https://github.com/agilexrobotics/pyAgxArm/blob/d90e234ba8e408cfa964b38aa9120b3131fc9f85/docs/piper/piper_api.md)
  and [firmware reference](https://github.com/agilexrobotics/pyAgxArm/blob/d90e234ba8e408cfa964b38aa9120b3131fc9f85/docs/piper/firmware_reference.md).
- [Legacy MoveIt guide](https://github.com/agilexrobotics/piper_ros/blob/017ffefa64511bc6325bd77ddc4e16065c152051/src/piper_moveit/README(EN).md).
- [Unified ROS README](https://github.com/agilexrobotics/agx_arm_ros/blob/286633e0d2edb038ee3a1047d9feb7f614a1c076/README_EN.md)
  and [unified MoveIt guide](https://github.com/agilexrobotics/agx_arm_ros/blob/286633e0d2edb038ee3a1047d9feb7f614a1c076/src/agx_arm_moveit/README_EN.md).

## Cross-checks that materially changed the initial research

1. The manufacturer page was retrievable directly despite an initial research
   tool's network restriction. Hardware values here come from that primary
   HTML, not reseller/search summaries.
2. Manufacturer comparison lists PiPER-H reach as **636 mm**, not 669 mm.
3. Manufacturer J5 ranges differ from SDK presets; report the source layer.
4. The **same SDK file** has base J6 +/-180 degrees in its degree table and
   approximately +/-120 degrees in its radian table. It is not sufficient
   to describe all preset radians as equivalent to the degree table.
5. New official unified SDK/ROS repositories exist and were examined; a
   legacy-V2-only skill would miss important firmware/sign/unit changes.
6. Unified firmware documentation describes multiplicative k/b/c torque
   coefficients. An initial additive `current*k+b` interpretation is not
   retained as an engineering formula.
7. The unified API documents joint calibration, installation/payload settings
   and slow-descent emergency stop. Absence in selected legacy material must
   not be reported as absence from all current public interfaces.
8. Legacy CAN gripper effort is N m, while the current unified ROS effector
   adapter describes N. Neither justifies the local CLI's N/m label.

## Honest limits on completeness

This is a bounded, substantial primary-source survey, **not** a claim that all
latest AgileX documentation or source files were read.

- The manufacturer full-specification/manual download is behind a contact
  details form. No personal details were submitted and no protected customer
  manual was obtained. Full electrical/mechanical drawings, certified safety
  information and delivery-specific commissioning instructions remain gaps.
- L/H-specific complete datasheets and all gripper/accessory manuals were not
  obtained. Gripper 70/80/100 mm representations remain revision/adapter
  dependent and unresolved for the physical unit.
- SDK libraries were not installed, built or executed. No firmware, CAN
  connectivity, calibration, payload or stopping behavior was tested.
- README support matrices are vendor documentation claims, not independently
  validated compatibility on all listed systems.
- Detailed unified effector API implementation, every ROS service/action
  implementation, URDF submodule revisions and complete simulation assets
  were not audited. Interface summaries should not be treated as complete
  binary/protocol conformance tests.
- Latest branch heads were pinned; latest stable PyPI releases and actual
  installed package/firmware versions were not established.
- Permitted combined payload/moment/speed/orientation duty, collision force
  thresholds, watchdog behavior, safe command rates and guaranteed stop
  distances were not verified.

No repository files were changed and no robot commands, service changes,
network/CAN changes, installations or hardware motions were performed.

## Refresh and escalation

1. Reopen P1 and compare specifications/footnotes for the exact model.
2. Resolve official repository heads and releases; record package versions,
   firmware and model separately. Diff unit, sign and limit changes.
3. Obtain the corresponding official full manual from AgileX without sending
   local code, credentials or personal data to external services.
4. Reconcile J6/J5/gripper discrepancies with the installed revision. Do not
   select the larger value merely because it is newer or less restrictive.
5. Use [acceptance questions](./acceptance-checklist.md) for unresolved limits.
6. Update references and dates together; retain local mounted-arm constraints
   and route physical operations to existing skills.
