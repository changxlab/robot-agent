# Local robot-agent integration

Inspected 2026-10-25. This is local implementation evidence, not Unitree's
hardware specification. Settings and code can change; recheck before operating.
This reference contains no credentials and prescribes no direct SDK/ROS bypass.

## Deployment

The robot is a Unitree B2 with an AgileX Piper arm and multiple cameras.
ROS 2 Humble, navigation and manipulation share onboard compute. Payload
clearance and center of mass differ from the bare B2.

The application discovers `.claude/skills/*/SKILL.md` using
`robot_agent/skills.py`. Skills use matching lowercase-hyphenated directory/name,
YAML frontmatter and a nonempty description. This standalone bundle is not
registered there and does not modify the repository.

## Existing command surface

These are syntax references, not instructions to execute without loading the
matching operation skill.

```bash
./robot status
./robot base state
./robot base stand-up
./robot base stand-down
./robot base balance-stand
./robot base move --vx 0.1 --vy 0 --vyaw 0 --duration 1
./robot base stop
./robot base damp
./robot estop
./robot map start
./robot map status
./robot map save --name NAME
./robot map stop
./robot map list
./robot map scan --name NAME
```

- Body velocities: `vx` forward and `vy` left in m/s; `vyaw` left-positive
  in rad/s; duration in seconds. Default move values: 0, 0, 0, 1 second.
- Current configured component bounds: |vx| <= 0.5 m/s, |vy| <= 0.3 m/s,
  |vyaw| <= 0.6 rad/s; duration <= 3 seconds. The wrapper clamps requests.
  These are **local policy**, not B2 hardware maxima, combined vector bounds,
  stability guarantees or an invitation to request larger values.
- Local motion guards include battery below 15%, nonzero fault, lost motors,
  motor temperatures >= 70 C, unsuitable lying/damping mode, and competing
  `/cmd_vel_nav` publishers.
- Commands are refreshed at 10 Hz, followed by StopMove. The approximate 0.1 s
  command-loop interruption interval is **not** measured stopping latency,
  braking distance or a safety guarantee.
- `recovery-stand` exists in the parser but is disabled by policy. Never suggest
  running it on this arm/camera-equipped robot.
- Stand-down lowers the body; damping makes joints limp and can collapse it.
  Check arm/payload clearance; neither is a generic emergency-stop substitute.
- `base stop` targets only the base. `estop` attempts base StopMove and arm stop
  independently; use the physical/remote emergency procedure if needed.

## Mapping and navigation gap

Map names use 1-64 characters from `[A-Za-z0-9_-]`.

| Backend | Behavior |
|---|---|
| `unitree` | Uses configured `/qt_command` and `/qt_notice` integration; saving ends mapping and stores the point cloud on the robot |
| `command` | Runs a configured ROS SLAM command and saves using `nav2_map_server` |
| simulation | Produces simulated occupancy/point-cloud artifacts; does not contact hardware |

With the Unitree backend, `./robot map stop` does **not** end onboard SLAM:
the wrapper reports that mapping continues until `./robot map save --name NAME`.
Do not report a successful stop unless tool output establishes it.
Backend-specific map products are not interchangeable: a Unitree point cloud
is not automatically a Nav2 occupancy map or localization database.

There is no supported `./robot nav`, localization command, waypoint command,
route executor or autonomous navigation-start surface in the inspected CLI.
Do not compete with navigation using manual motion. Do not start bringup,
inspection, survey or motion-capable ROS launches to work around this gap.

## Real versus simulation

The configured mode determines whether tools contact hardware. `[SIM]` state
includes sample readings and proves no real connectivity or readiness.
Real operation depends on installed Unitree ROS messages, CycloneDDS, the
configured DDS interface and the robot network. Topics include configured
sport state/request, low state, navigation velocity, lidar, command and notice
channels; these names are local integration choices, not universal API promises.
Never change network addresses or copy another robot's configuration by default.

## Local evidence locations

Paths below are repository-relative evidence pointers for future reinspection,
not portable dependencies of this standalone skill.

- `.claude/skills/b2-locomotion/SKILL.md`: operation policy and wrapper-only rule.
- `.claude/skills/robot-status/SKILL.md`: pre-motion health checks and simulation.
- `.claude/skills/robot-mapping/SKILL.md`: mapping workflow/backend differences.
- `.claude/skills/robot-troubleshooting/SKILL.md`: diagnosis and approval boundary.
- `robot_tools/base.py`: API table, checks, move loop and argument parser.
- `robot_tools/__main__.py`: combined software stop.
- `robot_tools/mapping.py`: map-name validation and backend behavior.
- `robot_tools/config.py`, `robot.yaml`: configuration schema and current policy.
- `robot_agent/skills.py`: application skill discovery and validation.
