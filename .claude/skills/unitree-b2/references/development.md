# B2 development interfaces

Checked 2026-10-25. This is an interface/review reference, not executable robot
control guidance. Use the approved local wrapper and installed operation skills.

## Official entry points and version baseline

- [Obtain SDK](https://support.unitree.com/home/en/B2_developer/Obtain%20SDK)
  is the B2 developer download entry point (page revision 2026-07-30).
  B2 and B2-W models/downloads are distinct.
- [unitree_sdk2](https://github.com/unitreerobotics/unitree_sdk2) was checked at
  commit `d1abf001220d3e5f59e00a0c4aaa595e00089a4a`, dated
  2026-10-15. This is a retrieved branch-head commit, not a certified release.
- [unitree_ros2](https://github.com/unitreerobotics/unitree_ros2) was checked at
  commit `668d1ec5a05d1c38d3306bdca7d59f2ba3581a88`, dated
  2026-07-02. Its README explicitly includes B2.
- [unitree_slam](https://github.com/unitreerobotics/unitree_slam) has a very short
  README demonstrating `demo_h1`. That does **not** establish B2 launch steps or
  compatibility with the current commercial Navigation Solution.

The SDK README's prebuilt baseline is Ubuntu 20.04, GCC 9.4.0, aarch64/x86_64;
it lists CMake >=3.10 and dependencies. The ROS 2 README recommends Ubuntu 22.04
with Humble and also lists Ubuntu 20.04/Foxy. Do not mistake either for a
comprehensive support/certification matrix. Follow the target repository's
pinned build instructions; do not blindly install its older example environment
on this existing Humble deployment.

## Network and DDS

The official B2 example initializes `ChannelFactory` with DDS domain **0** and
a network-interface argument. This verifies an **example's choice**, not an
immutable default for every delivery.

The official ROS 2 README:

- Uses CycloneDDS and states robot CycloneDDS version 0.10.2.
- Says its separate CycloneDDS compilation step can be skipped with Humble.
- Shows an example developer-PC address `192.168.123.99` with mask
  `255.255.255.0`, and binds CycloneDDS to the connected NIC.
- Supports loopback configuration for non-robot use.

Do not change this computer's IP, middleware or domain from those examples.
First inspect the installed configuration; avoid IP conflicts and unintended
discovery onto another robot. DDS discovery alone is not control compatibility.

Common state/request surfaces documented by the ROS repository include
`/sportmodestate`, `/lf/sportmodestate`, `/lowstate`, and
`/api/sport/request`. DDS wire names such as `rt/qt_command` and ROS names such
as `/qt_command` require correct middleware/message mapping; never construct a
ROS command by mechanically stripping `rt/`.

Read state freshness, message definition, coordinate frame, units, QoS and
controller ownership before interpreting values. The README's example motion
and low-level-control executables can move hardware on startup; do not run them
as connectivity probes.

## B2 sport service

Pinned evidence:
[sport_api.hpp](https://github.com/unitreerobotics/unitree_sdk2/blob/d1abf001220d3e5f59e00a0c4aaa595e00089a4a/include/unitree/robot/b2/sport/sport_api.hpp)
and
[sport_client.hpp](https://github.com/unitreerobotics/unitree_sdk2/blob/d1abf001220d3e5f59e00a0c4aaa595e00089a4a/include/unitree/robot/b2/sport/sport_client.hpp).

Service `sport`, API version `1.0.0.1`. Presence in headers does not prove
installed firmware support or permission to call.

| ID | Method | Relevance |
|---|---|---|
| 1001 | `Damp()` | Can collapse the robot; not a generic E-stop |
| 1002 | `BalanceStand()` | Physical motion |
| 1003 | `StopMove()` | Base software motion stop |
| 1004 / 1005 | `StandUp()` / `StandDown()` | Payload/arm clearance required |
| 1006 | `RecoveryStand()` | Disabled in this deployment |
| 1008 | `Move(float vx, float vy, float vyaw)` | Use bounded local wrapper instead |
| 1011 | `SwitchGait(int d)` | Enum/range/firmware support must be established |
| 1013 | `BodyHeight(float height)` | Numeric bounds not established here |
| 1015 | `SpeedLevel(int level)` | Level mapping not established here |
| 1018 | `TrajectoryFollow(vector<PathPoint>&)` | Does not imply obstacle-aware navigation |
| 1019 | `ContinuousGait(bool)` | Unsupported local operation surface |
| 1036 | `MoveToPos(float x, float y, float yaw)` | Not interchangeable with navigation goal APIs |
| 1038 | `SwitchMoveMode(bool)` | Controller/mode semantics need firmware documentation |
| 1039 / 1040 | `HandStand(bool)` / `AutoRecoverySet(bool)` | Do not use on this arm-equipped installation |
| 1045 | `FreeWalk()` | Not exposed by local wrapper |
| 1049 / 1050 | `ClassicWalk(bool)` / `FastWalk(bool)` | Not exposed by local wrapper |
| 1051 | `Euler(float roll, float pitch, float yaw)` | Position/range semantics need verification |
| 1052 / 1053 | `FreeHeight(bool)` / `GaitHeight(bool)` | Both take **bool**, not a height float |
| 1101 | `VisionWalk(bool)` | Header presence is not confirmation of installed perception behavior |

`PathPoint` has float fields `timeFromStart`, `x`, `y`, `yaw`, `vx`, `vy`,
`vyaw`. Do not infer frame, trajectory length, sample interval, timing guarantee
or safety behavior solely from this structure.

No verified B2-specific complete numeric bounds were found for `Move`,
`BodyHeight`, `SpeedLevel`, joint torque/current/velocity, API refresh rate or
watchdog timeout in the sources surveyed. Examples are not limit definitions.

## State and motion ownership services

Research also inspected official B2 headers under
[`include/unitree/robot/b2/`](https://github.com/unitreerobotics/unitree_sdk2/tree/d1abf001220d3e5f59e00a0c4aaa595e00089a4a/include/unitree/robot/b2).

| Service/version | ID inventory | Use in engineering review |
|---|---|---|
| `robot_state`, `1.0.0.2` | 1001 service switch; 1002 report frequency; 1003 service list; 1004 low-power switch; 1005 low-power status; 1006 package version | Identify supported versions and service state; switching/report changes are not read-only |
| `motion_switcher`, `1.0.0.1` | 1001 check mode; 1002 select mode; 1003 release mode; 1004 set silent; 1005 get silent | Establish motion ownership; do not change it during a documentation task |

`robot_state` package-version data exposes `packageVersion` and
`moduleVersionMap`. Service-list data includes `name`, `status`, `protect`.
Do not invent units for report-frequency `interval`/`duration`.
Motion switcher names/IDs alone do not establish transition/reset semantics;
in particular do not assume release mode automatically restores a desired
safe high-level state.

Low-level control requires a separate approved engineering procedure and exact
message/CRC/mode/joint documentation. Do not publish low-level commands, release
the current controller, disable protected services or run examples to "test"
an operator question.

## Development workflow

1. Record installed versions and inspect the matching B2 source/message types.
2. Identify whether the target is SDK2 sport/state, legacy DDS SLAM, or the
   newer HTTP/WebSocket navigation product. Do not merge their protocols.
3. Establish units, coordinate frames, IDs, request correlation, timeouts and
   distinction between accepted, completed, failed and cancelled.
4. Design read-only probes and offline message/schema tests first.
5. Implement missing features only through the authorized project engineering
   process; this operator project must not be modified by this skill.
6. Use an approved staged validation plan, installed operation skills, local
   policy bounds and physical emergency-stop access before any hardware test.
