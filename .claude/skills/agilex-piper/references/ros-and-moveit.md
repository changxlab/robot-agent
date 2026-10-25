# ROS, kinematics and MoveIt integration

Checked 2026-10-25. These sources describe engineering interfaces, not permission
to start a second controller on this robot. Its installed wrapper uses the
legacy CAN SDK directly.

## Official driver generations

| Repository | Snapshot | Coverage |
|---|---|---|
| [piper_ros](https://github.com/agilexrobotics/piper_ros) `noetic` | `ac41fcbcdda598f01b51cf6175ed9a24d0dacadc`, 2026-03-04 | ROS 1 legacy driver |
| [piper_ros](https://github.com/agilexrobotics/piper_ros/tree/humble) `humble` | `017ffefa64511bc6325bd77ddc4e16065c152051`, 2025-12-16 | ROS 2 legacy driver and MoveIt 2 |
| [agx_arm_ros](https://github.com/agilexrobotics/agx_arm_ros/tree/ros2) `ros2` | `286633e0d2edb038ee3a1047d9feb7f614a1c076`, 2026-10-20 | Unified driver, README labels Humble/Jazzy supported; uses pyAgxArm |

Do not search only for a hypothetical `piper_ros2` repository: official legacy
ROS 2 support is in a branch of `piper_ros`. The newer unified driver is a
separate stack. Its existence does not establish a mandatory migration or
compatibility with this installation's vendor record/play scripts.

## Legacy piper_ros

Documented topics include `/arm_status`, `/enable_flag`, `/end_pose`,
`/joint_states`, `/joint_states_single` and `/pos_cmd`.
`/joint_states` is a **control input**, whereas `/joint_states_single` is
feedback; familiar topic naming does not imply read-only use.
ROS 1 also documents `/end_pose_euler`.
The ROS 2 service `/enable_srv` uses `piper_msgs/srv/Enable`.

Parameters include `can_port`, `auto_enable`, `gripper_exist`, `rviz_ctrl_flag`
and the literally spelled `gripper_val_mutiple`. The README's RViz gripper
scale of 2 relates a 0-0.04 m model slider to its stated 0.08 m travel.
Do not copy that into the local 70 mm gripper without model/adapter checks.

The legacy manual selects old versus current URDF at firmware **S-V1.6-3**
because of J2/J3 coordinate offsets. Use matched firmware, URDF, SDK
`dh_is_offset`, tool transform and zero calibration. A two-degree mismatch is
not fixed by adding arbitrary offsets to desired poses.

The legacy MoveIt guide distinguishes real-arm and Gazebo launches. Its
`demo.launch.py` is used in a **real control workflow**, not guaranteed fake
hardware merely because it is called "demo".
The simulation `piper_moveit.launch.py` must follow Gazebo; MuJoCo sequencing
differs. Do not run any of these as read-only environment probes.

## Unified agx_arm_ros and pyAgxArm

Current README parameters include actual arm type, end-effector type, CAN port,
TCP offset and controller settings. Exact namespaces and defaults must be
checked at the pinned revision. The model/URDF stack uses the official
`agx_arm_urdf` submodule; record submodule commits instead of silently updating
them while validating a deployed configuration.

Key documented surfaces:

| Surface | Meaning |
|---|---|
| `/feedback/joint_states` | Combined state: arm radians, rad/s, N m |
| `/feedback/gripper_status` | End-effector-specific status/diagnostics |
| `/control/joint_states` | Motion input, can include end-effector joints |
| `/control/move_j`, `/control/move_js`, `/control/move_cpv` | Other control inputs, firmware/mode applicability must be checked |
| `control_enable` | SetBool gate service in documented MoveIt integration; namespace configurable |
| `arm_controller/follow_joint_trajectory` | Action execution monitored by optional MoveIt gate |

The unified `agx_gripper` adapter exposes a total-width `gripper` joint in
meters, documented range 0-0.1 m; internal finger joints mimic it.
Its effort field is force in N, unlike the legacy V2 effort torque in N m.
Do not infer gripper equivalence or pass identical effort scalars across stacks.

RViz `follow` determines whether visualization tracks feedback versus control
state. `control` determines whether sliders publish control commands.
`control:=false` on a visualization launch does not by itself certify every
other node on the bus is inactive.

### MoveIt control gating

The current
[MoveIt guide](https://github.com/agilexrobotics/agx_arm_ros/blob/286633e0d2edb038ee3a1047d9feb7f614a1c076/src/agx_arm_moveit/README_EN.md)
documents:

- A no-real-arm simulation demo and a distinct real-arm control workflow.
- One-click launch combines arm driver, MoveIt and RViz and can control hardware.
- Real-state following uses feedback, but execution still depends on fresh
  state and start-state consistency.
- Optional `auto_control_gate:=true` enables control during trajectory execution
  and closes it afterward via a configurable SetBool service.
- The documented default example leaves auto gate disabled/control open.
  Do not assume automatic ownership isolation is on by default.

Such gating reduces idle control-topic occupation; it is not a safety-rated
interlock, collision detector or permission to run two controllers together.
The local wrapper's lock does not necessarily arbitrate an external ROS node.

## Kinematics and scene correctness

1. Select the exact base/H/L/X model, matching URDF and firmware zero convention.
2. Establish base-to-arm mounting transform, flange-to-tool/TCP transform,
   gripper state, sensor extrinsics and payload geometry.
3. Include the B2 body, fixtures, arm bracket, camera/cables and carried object
   in the planning scene as appropriate. A bare desktop-arm model omits them.
4. Match joint names/order and position/velocity/acceleration limits at all
   layers. Do not enlarge hardware/wrapper limits to make a plan succeed.
5. Validate scene and unit conversions offline. Planning success is not proof
   of real collision avoidance or base stability.
6. Use a separately approved integration process for execution. This knowledge
   skill must not alter the operator project or launch motion software.

The legacy SDK's MDH tables are model-specific; do not copy base-model lengths
to H/L/X or combine them with a mismatched frame-offset URDF.
The full delivery-specific collision matrix, payload dynamics and calibration
procedure remain to be verified for this robot.
