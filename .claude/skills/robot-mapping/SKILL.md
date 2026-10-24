---
name: robot-mapping
description: Build, monitor and save a map of the environment with the robot's SLAM - the Unitree B2 built-in SLAM (unitree_slam, LIO-SAM with the B2 lidar) or a ROS 2 SLAM launch such as slam_toolbox. Use when asked to map an area, check mapping progress, or list/show saved maps.
---

# Mapping

```bash
./robot map status              # SLAM session, lidar cloud, /map size (read-only)
./robot map start               # start mapping (needs operator approval)
./robot map save --name lab_1   # end mapping and save the map
./robot map stop                # stop a ROS SLAM process without saving
./robot map list                # saved maps in artifacts/maps
./robot map scan [--name scan1] # save one lidar sweep as a point cloud (artifacts/pointclouds/*.pcd)
```

The backend is set by `mapping.backend` in `robot.yaml`:

- `unitree` - sends start/end mapping commands to the B2 SLAM service on `/qt_command`
  (command 3 = start, 4 = end and save) and reads progress from `/qt_notice`. The point-cloud map is
  stored on the robot by `unitree_slam`.
- `command` - launches `mapping.start_cmd` (default slam_toolbox) in the background, logging to
  `artifacts/logs/mapping.log`; `save` runs nav2 `map_saver_cli` into `artifacts/maps/<name>.yaml/.pgm`
  and creates a PNG preview.

In SIM mode, `save` writes an occupancy grid and a 3D point-cloud map of the simulated farm
(`artifacts/maps/<name>.pcd`), and `scan` returns a simulated lidar sweep from the simulated B2 pose.

When a preview is created, `save` prints `IMAGE: artifacts/maps/<name>.png`; point clouds are announced
as `POINTCLOUD: <path>.pcd` and the operator can inspect them in the UI's 3D viewer (you cannot). The operator sees it in the
UI; open it with the Read tool before describing the map.

## Mapping workflow

1. `./robot status` - the base must be healthy and the lidar topic present.
2. `./robot map start`, then `./robot map status` to confirm the lidar cloud is arriving.
3. Explore with short `./robot base move` commands (b2-locomotion skill), checking the camera and
   obstacle ranges between moves. Slow, smooth motion (<= 0.3 m/s, gentle turns) gives better maps;
   revisit the start point to close the loop.
4. Check progress with `./robot map status`.
5. `./robot map save --name <name>` and show the result.

If mapping fails to start, read `./robot logs --source mapping --level all`.
