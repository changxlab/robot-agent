# Navigation: two generations, different protocols

Checked 2026-10-25. Do not combine these interfaces or assume either is installed.

| Generation | Official source | Interface |
|---|---|---|
| B2 onboard SLAM/navigation | [S4, SLAM and Navigation Services Interface](https://support.unitree.com/home/en/B2_developer/SLAM%26Navigation%20Interface), updated 2024-04-03 | DDS topics, Qt/graph custom message types, command codes and notice strings |
| Optional industry-grade navigation product | [S5, Overview of SLAM Navigation Service](https://support.unitree.com/home/en/navigation/SLAM%26Navigation_service), updated 2026-09-16 | Web console and HTTP + WebSocket integration; different protocols from earlier units |

The open-source `unitree_slam` README demonstrates an H1 example. Its existence
does not identify the B2's installed navigation generation or replace either
manual.

## Industry-grade Navigation Solution: eligibility first

S5 explicitly states:

- This is optional; contact sales for availability and model support.
- The B2/B2-W upgrade requires **serial numbers after 365 and standard lidar**.
  Confirm the interpretation of the serial number and actual eligibility with
  Unitree; do not parse an arbitrary serial-string suffix as proof.
- Earlier units use an older version without the web interface and with
  different protocols.
- Installing the industry navigation software removes **APP navigation**
  availability. This is a compatibility/migration decision, not a harmless add-on.
- Currently supported models include B2, B2-W, G1-EDU, A2 PRO and A2-W PRO.
  As2-EDU is listed as extended/future support, not currently supported.

Do not install, upgrade, reset or change usernames/passwords as a research task.
S5 warns that forgotten changed PC credentials can require factory reset with
data loss.

### Published performance and feature constraints

S5 section 1.5 is a cross-model table. Apply the B2/legged entries only.

| Item | Published value / qualification |
|---|---|
| Single mapping range | B2/B2-W: 100-200 m; page does not define radius versus extent |
| Maximum range per PCD | 1000 m; not stated as autonomous travel distance |
| Scene range per task | 30 map sheets; map switching supports larger scenes |
| Relocalization error | +/-3 cm |
| RTK-integrated positioning error | +/-2 cm, optional |
| Arrival error | Legged <=5 cm; wheeled <=8 cm |
| Route deviation | Legged <=5 cm; wheeled <=20 cm |
| Governed navigation speed | Legged 0.1-1 m/s; wheeled 0.1-2 m/s |
| Ramp navigation | <=30 degrees |
| Stair navigation | <=45 degrees; not a stair-rise measurement |
| Outdoor mapping scenes | Table requires optional RTK |
| Tunnel mapping | B2 support with optional tunnel-specific lidar |
| Soft emergency stop | Supported; physical stop button listed as optional |

These are vendor specifications, not a complete statistical test protocol,
guaranteed worst-case bound, or achieved performance of the local robot.
Centimeter localization/arrival figures do not justify centimeter clearance.
Do not apply G1 dance-system figures, such as high-dynamic angular motion or
stage dimensions, to B2 locomotion.

Other advertised capabilities include PCD import/downsampling/feature
enhancement, occupancy-grid generation/editing/import/export, localization
failure detection, cross-map positioning/navigation, multi-floor routes,
topological and coordinate goals, obstacle stopping/avoidance and replanning.
Support in an overview does not establish usable endpoint schemas.

**Hazardous option:** the table includes a force-through behavior that ignores
obstacles. Do not enable it or recommend it as a workaround.
Door, elevator and charging-dock integration entries are marked for Unitree
internal use. This does not mean every advertised charging function is absent:
other rows describe model/option-dependent docking and low-battery return.
Confirm the actual external integration contract and purchased hardware.

### Positioning modes: options and prerequisites

| Mode | Prerequisites and limitations in S5 section 1.8 |
|---|---|
| RTK-integrated mapping/positioning | Optional dual-antenna RTK and 5G modules, differential account and data SIM; mapping initialization needs good RTK reception |
| Imported RTK-aligned map | Supply longitude, latitude and elevation at the PCD origin so the coordinate transformation can be established |
| Tunnel/corridor | Optional XT32 lidar; third-party scanner mapping because the robot/payload occludes the rear field of view; PCD feature enhancement by Unitree or its provided web tool |
| LiDAR/visual fusion | **Optional** fusion module; handheld-scanner mapping; unsuitable for darkness or dramatic lighting changes |

The standard shipped navigation software does not include the optional tunnel
and RTK variants. Do not label lidar/visual fusion a standard/default mode.
RTK fallback claims do not establish guaranteed continued safe navigation in
all sensor failures.

### Development modes in S5

1. **Single-point navigation:** after mapping, send pose goals; the planner
   chooses a route.
2. **Topological-map navigation:** after mapping and road-network setup,
   navigate to named points constrained to that network.
3. **Dynamic topology:** an external task planner supplies consecutive paths
   and points; the robot is a navigation execution component.
4. **Fully automated inspection:** configure route/tasks; use timed dwell or
   explicit remote continuation triggers at inspection points.
5. **Inspection validation:** validate web-configured topology/tasks before
   integrating the full inspection platform.

Navigation and point inspection do not provide target recognition or image
inspection analytics automatically. Those require user hardware/software or
the separately purchased complete inspection solution.

### Safe lifecycle for planning an integration

This is a synthesis of S5's feature flow, **not** a verified sequence of endpoint
calls or exact UI clicks:

1. Verify eligibility, installed version/options and migration implications.
2. Establish sensor calibration, timestamps, clearances, map frame and exclusive
   motion ownership under an approved operating procedure.
3. Select the appropriate mapping/positioning mode. Build or import a compatible
   PCD with required geographic alignment/feature processing; retain map version.
4. Generate/edit occupancy representation where applicable; inspect obstacles
   and exclusions rather than assuming the PCD alone supplies safe traversability.
5. Initialize localization and verify its quality/freshness and failure behavior.
6. Configure the chosen coordinate, topological, dynamic-path or inspection mode.
   Set conservative speed, orientation, obstacle stop/avoid policy and dwell.
7. Validate in a controlled site before scheduling unattended tasks. Verify
   pause/resume, cancellation, failure, relocalization, map switching and
   low-battery behavior through an approved test plan.
8. Record actual state transitions and arrival/task outcomes, not only request
   acknowledgements.

The overview confirms HTTP/WebSocket availability, but this survey did **not**
verify their endpoint paths, authentication, ports, payload schemas, event codes,
timeouts or command completion semantics. Obtain the version-matched detailed
protocol documentation from Unitree before writing an adapter. Do not invent
URLs or translate the legacy numeric codes into HTTP requests.

## Legacy B2 DDS SLAM/navigation

### Prerequisites and addressing

S4 requires PC2 and the 3D lidar and asks that OTA be complete:

- PC2/navigation computer: default `192.168.123.162`.
- PC1 connectivity example: `192.168.123.161`.
- Lidar: default `192.168.124.20`, target `192.168.123.162`.
- User PC: nonconflicting `192.168.123.XXX`.

These are delivery defaults, not permission to reconfigure the local robot.
The source lists different lidar/PC subnets without establishing the entire
routing/interface topology. Do not assume the lidar must respond through the
same interface merely because PC2 responds.

### Message and topic inventory

| DDS topic | Type/purpose |
|---|---|
| `rt/qt_command` | `QtCommand`, commands other than add-node/add-edge |
| `rt/qt_add_node`, `rt/qt_add_edge` | `QtNode`, `QtEdge`, graph additions |
| `rt/all_node`, `rt/all_edge` | Current graph resent after additions/deletions |
| `rt/query_result_node`, `rt/query_result_edge` | Query results |
| `rt/qt_notice` | Standard ROS 2 String feedback |
| `rt/lio_sam_ros2/mapping/re_location_odometry` | Standard Odometry, relocation pose |

The page supplies IDL for `QtNode_`, `Node_`, `QtEdge_`, `Edge_` and
`QtCommand_`. QtNode/QtEdge pair a request identifier with graph data.
Nodes include ID, x/y/z and yaw arrays; edges include ID, start/end node, length
and behavior arrays. QtCommand includes command/attribute, identifier,
floor/map/graph indexes, node/edge IDs and pose fields.
Reserved/unavailable fields are not extension points.

For edges, S4 documents `dog_speed` as **0-1**, without establishing SI speed
units; do not call it 0-1 m/s. `edge_state_2` selects obstacle behavior:
0 stop, 1 avoid, 3 replan. The source recommends 0 for safety.
Verify coordinate frame and yaw/translation units before serializing commands.

### Command code reference

| Code | Function | Lifecycle caution |
|---|---|---|
| 1 / 2 | Delete / query nodes or edges | Attributes and IDs must match exact schema |
| 3 | Start mapping | Can change onboard process state |
| 4 | End mapping | Saves PCD and closes mapping node |
| 6 | Start relocation | Starting process is not localized readiness |
| 7 | Initialize relocation | Needs a valid initial pose |
| 8 | Start navigation node | Not a navigation goal |
| 9 | Single-node navigation | May move hardware |
| 10 | Default multi-node loop | Proceeds through all topology nodes in sequence |
| 11 | Configured multi-node loop | Proceeds through received topology nodes in sequence |
| 13 / 14 | Pause / restore navigation | Verify state and ownership before resuming |
| 15 | Return to start node | Default start is the first node; may move |
| 99 | Close all functional nodes | Not a safety-rated emergency-stop action |

### Feedback: exact syntax matters

The legacy source documents **semicolon-separated key/value fields**, not a
slash-delimited string. Short format reference:

```text
index:XXX;feedback:X;state:X;notice:XXX;
```

- User request index range: 1-10000.
- Feedback: 1 success, 0 failure, 2 waiting.
- State: 0 idle; -1 system error; 2 mapping; 3 navigation;
  4 relocation open; 5 localization initialization complete;
  6 navigation node open.
- Index 10001 is unsolicited navigation-progress feedback with `arrive`,
  `finish`, `all`, `loop`, `obstruct`, `notice`.
- `obstruct`: **1 means no obstacle; -1 means obstacle**.
- Single-node navigation uses -1 for the loop-task counters described in S4.

Separate the request acknowledgement from asynchronous progress and completion.
Do not conflate state 3 with state 6 or assume either certifies safe movement.
The complete allowed command/attribute combinations, recovery behavior,
QoS, timing and persistence contract need the installed implementation/manual.

## Local integration boundary

The current wrapper exposes mapping but no localization, waypoint, route/task
or navigation-goal CLI. Its Unitree map save ends mapping; its Unitree map stop
does not. See [local integration](./local-integration.md).
Use installed `robot-mapping`/`b2-locomotion` skills for actual operations.
Do not publish the above DDS messages directly to bypass missing wrapper APIs.
