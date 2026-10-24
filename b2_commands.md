# 常用指令速查

依据本机 Bash 历史及现有启动脚本整理，整理日期：2026-10-13。
历史出现过的命令不代表当前仍可成功执行；包、服务、设备和地图需以现场状态为准。
未收录凭据、敏感连接信息、历史中的破坏性操作和固件刷写命令。

## 1. 使用约定

- 每个代码块是独立示例，不要将整份文档连续执行。
- ROS 2 示例需要先在当前终端加载环境；编译后重新加载工作区环境。
- `MAP_NAME`、`MAP_ID`、`PATH_ID`、`SERVICE_NAME`、`BAG_DIR` 是待替换的值。
- 带 `sudo` 的命令需要相应权限；密码只在本机终端输入。
- 启动巡检、回放机械臂、播放录包、重启服务可能影响真实设备，执行前确认安全区域、急停和运行状态。
- 前台进程通常用 `Ctrl+C` 停止；不要用批量杀进程代替正常退出。

## 2. ROS 2 环境与编译

历史中高频使用 `source install/setup.bash` 和 `colcon build`。
主要工作区见 [hdm.sh](hdm.sh)，不是任意当前目录下的 `install`。

```bash
cd ~/dog_ws/infai_work
source /opt/ros/humble/setup.bash
source install/setup.bash
```

在上述工作区编译，按需要选择全量或单包命令，不必全部执行：

```bash
colcon build
colcon build --packages-select infai_navigation2
colcon build --packages-select infai_bringup
colcon build --packages-select infai_slam
colcon build --packages-select dog_inspection
source install/setup.bash
```

`--packages-select` 仅构建指定包，依赖需已构建；需要一起构建工作区内依赖时可用 `--packages-up-to 包名`。

[hdm.sh](hdm.sh)、[hdm_survey.sh](hdm_survey.sh) 和 [rtk.sh](rtk.sh) 使用以下 DDS 设置。
仅在实际网卡为 `eth0`、已安装 `rmw_cyclonedds_cpp` 时使用，跨进程通信需保持兼容配置。

```bash
ip -br link
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="eth0" priority="default" multicast="default" /></Interfaces></General></Domain></CycloneDDS>'
```

## 3. 定位、巡检与配套节点

定位启动在历史中多次出现。先设置实际地图、路径参数，确认对应数据存在：

```bash
MAP_NAME='REPLACE_WITH_MAP_NAME'
MAP_ID='REPLACE_WITH_MAP_ID'
PATH_ID='REPLACE_WITH_PATH_ID'
ros2 launch infai_bringup localization.launch.py \
  pcd_name:="$MAP_NAME" map_id:="$MAP_ID" path_id:="$PATH_ID"
```

以下是独立启动入口，按需选择。不要与已经运行的同名服务重复启动。
巡检、测绘和定位系统可能控制机器人，不应仅为检查语法而执行。

```bash
ros2 launch dog_inspection dog_inspection.launch.py
ros2 launch dog_survey dog_survey.launch.py
ros2 launch network_monitor network_monitor.launch.py
ros2 launch ros_mqtt ros_mqtt.amway.launch.py
ros2 run time_diff_tool comparer_node
```

历史中也使用过 `network_monitor.amway.launch.py`、`network_monitor.infai.launch.py` 和 `ros_mqtt.infai.launch.py`；按当前部署选择，不要同时启动多个版本。

RViz 配置直接打开，不照搬旧脚本中的错误路径：

```bash
rviz2 -d ~/localization.rviz
rviz2 -d ~/nav.rviz
```

需要只看定位错误时，在设置地图变量后使用以下替代启动方式。
它会隐藏非错误输出，完整排查时应去掉过滤：

```bash
ros2 launch infai_bringup localization.launch.py pcd_name:="$MAP_NAME" \
  2>&1 | grep --line-buffered -i 'error'
```

## 4. ROS 2 话题与接口排查

以下查询不会主动发送机器人控制命令，`echo`、`hz` 用 `Ctrl+C` 退出。

```bash
ros2 topic list
ros2 topic info /cmd_vel_nav
ros2 topic echo /cmd_vel_nav
ros2 topic echo /infai_slam/mapping/odometry
ros2 topic hz /rslidar_points
ros2 topic echo /dogoo/net_state/signal_level
ros2 service list
ros2 interface show dog_interfaces/srv/DogInspection
```

历史中还查看过 `/keyboard_ctl` 和 `/infai_slam/mapping/cloud_registered`。
点云输出较大，优先用 `topic info` 或 `topic hz` 检查。
不要直接复用历史中的速度发布、巡检 `start` 请求或机械臂触发请求；先确认接口语义、参数和设备状态。

## 5. 录包与回放

录制传感器数据，结束时按 `Ctrl+C`，等待写入完成：

```bash
ros2 bag record /rslidar_points /fix /dog_imu_raw
```

包含相机图像的录制方式来自 [bag.sh](bag.sh)，磁盘占用通常更大：

```bash
ros2 bag record /camera/camera/color/image_raw /fix /dog_imu_raw /rslidar_points
```

导航排查录包，来自历史中的完整话题组合：

```bash
ros2 bag record /tf /tf_static /local_plan /plan \
  /global_costmap/costmap_updates /global_costmap/costmap \
  /local_costmap/costmap /local_costmap/costmap_updates /cmd_vel_nav
```

下面的查看、回放命令是补充用法。回放会发布录包中的话题，含速度话题的录包必须与真实控制链路隔离。

```bash
BAG_DIR='REPLACE_WITH_BAG_DIRECTORY'
ros2 bag info "$BAG_DIR"
```

```bash
ros2 bag play "$BAG_DIR"
```

## 6. systemd 服务管理

先查看实际安装的服务。历史中既有连字符也有下划线命名，不能互换。
常见名称包括 `piper.service`、`piper-can.service`、`vcopy.service`、`icamera.service`、`dog_survey.service`、`dogoo_can0_activate.service`。

```bash
systemctl --failed
systemctl list-units --type=service --state=running
systemctl list-unit-files --type=service | grep -E 'dog|piper|vcopy|icamera|can'
SERVICE_NAME='piper.service'
systemctl status "$SERVICE_NAME" --no-pager
systemctl cat "$SERVICE_NAME"
```

日志查询是补充排障用法：

```bash
journalctl -u "$SERVICE_NAME" -n 100 --no-pager
journalctl -u "$SERVICE_NAME" -f
```

以下操作会改变服务状态，按需单独执行。`enable` 设置开机启动，不等于立即启动；修改 unit 文件后才需要 `daemon-reload`。

```bash
sudo systemctl daemon-reload
sudo systemctl start "$SERVICE_NAME"
sudo systemctl stop "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl disable "$SERVICE_NAME"
```

工作区里的 [dog_inspection.service](dog_inspection.service)、[dog_survey.service](dog_survey.service) 和 [dog_pcd2pgm.service](dog_pcd2pgm.service) 是服务文件样本，不代表系统已安装或启用；以 `systemctl cat` 输出为准。

## 7. Piper 机械臂与 CAN

历史中频繁进入 `~/piper_sdk/piper_sdk` 激活 CAN。先确认接口和设备连接，再执行初始化脚本；接口名和波特率必须与硬件配置一致。

```bash
ip -br link
cd ~/piper_sdk/piper_sdk
bash find_all_can_port.sh
```

以下会更改 CAN 接口状态，不要在机械臂任务运行中执行：

```bash
bash can_activate.sh can0 1000000
ip -details link show can0
```

位置录制与回放入口来自历史，脚本参数和数据文件以当前实现为准。回放会使机械臂运动；录制脚本是否使能电机也需先确认。

```bash
cd ~/Agilex-College/piper/recordAndPlayPos
python3 record.py
```

```bash
cd ~/Agilex-College/piper/recordAndPlayPos
python3 play.py
```

历史中还使用过 `recordPos.py`、`playPos.py`、`recordPos_new.py`、`playPos_new.py`。
轨迹脚本入口如下，录制和回放按需分别执行：

```bash
cd ~/Agilex-College/piper/recordAndPlayTraj
python3 recordTrajectory_new.py
```

```bash
cd ~/Agilex-College/piper/recordAndPlayTraj
python3 playTrajectory_new.py
```

MQTT 回放相关日志排查：

```bash
tail -f ~/Agilex-College/piper/recordAndPlayMQTT/logs/play.log
```

## 8. 相机、RealSense 与 RTK

USB 设备及 RealSense 只读诊断，命令需已安装；若工具在构建目录中，使用对应的 `./工具名`：

```bash
lsusb
rs-fw-update -l
realsense-viewer
```

RealSense 驱动启动，`pointcloud.enable` 修正了历史中的拼写错误；实际支持参数取决于驱动版本，可先查询：

```bash
ros2 launch realsense2_camera rs_launch.py --show-args
ros2 launch realsense2_camera rs_launch.py pointcloud.enable:=true align_depth.enable:=true
```

PC4 单帧查看 RealSense 彩色画面。先确认设备节点、格式和占用情况；`/dev/video4`、`YUYV` 和 `640x360` 是本机检查到的配置，其他设备以实际输出为准。需要安装 `v4l2-ctl` 和 `ffmpeg`：

```bash
ls -l /dev/video*
v4l2-ctl -d /dev/video4 --list-formats-ext
fuser -v /dev/video4
```

确认对应彩色设备节点未被其他程序占用后，采集一帧到 `/tmp/unitree_pc4_camera_snapshot.jpg`。`-n` 表示目标文件已存在时不覆盖；需要再次采集时，改用新的输出文件名：

```bash
ffmpeg -hide_banner -loglevel error \
  -f v4l2 -input_format yuyv422 -video_size 640x360 \
  -i /dev/video4 -frames:v 1 -q:v 3 -n \
  /tmp/unitree_pc4_camera_snapshot.jpg
```

在图形桌面打开截图：

```bash
xdg-open /tmp/unitree_pc4_camera_snapshot.jpg
```

ConsumerMosaicDemo 工业相机演示：配套 [启动脚本](../icamera_demo/ConsumerMosaicDemo.sh) 会设置同目录的依赖库路径。
启动前确认服务及手动实例均未运行，避免同时占用相机：

```bash
systemctl status icamera.service --no-pager
pgrep -af '(^|/)ConsumerMosaicDemo(\.sh)?([[:space:]]|$)'
```

手动启动：

```bash
cd ~/icamera_demo
./ConsumerMosaicDemo.sh
```

仅在遇到 USB 访问权限不足时使用以下替代命令，密码只在本机终端输入：

```bash
cd ~/icamera_demo
sudo -E ./ConsumerMosaicDemo.sh
```

前台运行用 `Ctrl+C` 停止。若出现 `could not connect to display`，请在图形桌面的终端启动或使用已配置的图形转发。
尚未确认程序的额外命令行参数，不假定支持 `--help`。

服务模式通过 [自启动脚本](../icamera_demo/auto_start.sh) 启动，与上述手动方式二选一。
以下服务命令按需单独执行，不要连续执行启动、停止和重启：

```bash
sudo systemctl start icamera.service
sudo systemctl stop icamera.service
sudo systemctl restart icamera.service
```

服务日志查询；`-f` 持续跟踪，用 `Ctrl+C` 退出，不会停止服务：

```bash
journalctl -u icamera.service -n 100 --no-pager
journalctl -u icamera.service -f
```

### PC4 iCAMERA SDK 拍照与视频采集测试

以下步骤需在同一个 PC4 终端依次执行，不适用于已连接到 NX5 的终端。仅测试相机，不操作导航或机械臂；不要与相机服务、ConsumerMosaicDemo 或其他采集实例同时运行。

**1. 确认设备、架构和占用**

```bash
hostname
uname -m
lsusb -d ae86:0001
systemctl status icamera.service --no-pager
pgrep -af '(^|/)ConsumerMosaicDemo(\.sh)?([[:space:]]|$)'
file /home/unitree/icamera_sdk/sdk_demo/libiCamera.so
file /home/unitree/icamera_demo/libiCamera.so
```

2026-10-23 实测：主机为 `unitree-b2-pc4`，架构为 `x86_64`，相机为 `ae86:0001 CCJT iCAMERA`；服务未运行，无手动采集实例。[SDK 目录](../icamera_sdk)中的库为 ARM64，不能直接用于 PC4；本次参考其 Qt 示例，使用 [icamera_demo](../icamera_demo) 中的 x86_64 库进行无界面测试。

**2. 检查 USB 权限，必要时临时授权**

根据 `lsusb` 的 Bus、Device 编号填写节点。以下 `001/012` 是本次编号，重新插拔后可能变化，必须重新核对。若 `fuser` 显示设备被占用，先确认已有采集任务，不要直接终止进程。

```bash
USB_NODE=/dev/bus/usb/001/012
fuser -v "$USB_NODE"
getfacl -p "$USB_NODE"
```

仅在缺少写权限时执行，密码在本机交互输入：

```bash
sudo setfacl -m u:unitree:rw "$USB_NODE"
getfacl -p "$USB_NODE"
```

授权成功应包含 `user:unitree:rw-`。这是单设备节点的临时授权，不是全局 USB 放权。

**3. 创建临时输出目录和 SDK 加载库**

需要已有 `gcc`、Python 3、`numpy`、`cv2`、`ffmpeg` 和 `ffprobe`。厂商的两个库相互依赖，需要和系统 libusb 一起加载：

```bash
TEST_DIR="$(mktemp -d /tmp/icamera-test-XXXXXX)"
export TEST_DIR
printf '本轮输出目录：%s\n' "$TEST_DIR"

gcc -shared \
  -x c /dev/null -x none \
  -o "$TEST_DIR/sdk_loader.so" \
  -Wl,--no-as-needed \
  -Wl,-rpath,/home/unitree/icamera_demo \
  /home/unitree/icamera_demo/libiCamera.so \
  /home/unitree/icamera_demo/libgraph.so \
  /lib/x86_64-linux-gnu/libusb-1.0.so.0
```

若编译或库加载报错，应先处理错误，不继续采集。

**4. 拍照并连续采集约 10 秒**

使用 SDK 默认模式，不修改传感器寄存器。按照 Qt 示例交换采集缓冲区并转换 Bayer 图像，保存照片、原始灰度图、MJPEG 视频及统计。

**已知问题：本次两轮测试都在 `FreeiCamera()` 阶段触发 libusb 断言崩溃。文件在释放前已经保存，但命令整体仍为失败退出，不能视为完整测试通过。** `timeout` 限制运行时间，`ulimit -c 0` 用于禁用普通 core 文件生成。

```bash
ulimit -c 0
timeout 30s python3 -u - <<'PY'
import ctypes
import json
import os
import time
from pathlib import Path

import cv2
import numpy as np

out = Path(os.environ["TEST_DIR"])
ctypes.CDLL(str(out / "sdk_loader.so"), mode=ctypes.RTLD_GLOBAL)
sdk = ctypes.CDLL("/home/unitree/icamera_demo/libiCamera.so")
sdk.bayer2rgb24.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int
]
result = sdk.InitCameraTransfer()
print("InitCameraTransfer =", result, flush=True)
if result < 0:
    raise RuntimeError("相机初始化失败")

writer = None
try:
    width = ctypes.c_int.in_dll(sdk, "im_info_w").value
    height = ctypes.c_int.in_dll(sdk, "im_info_h").value
    bpp = ctypes.c_int.in_dll(sdk, "im_info_bpp").value
    if not (0 < width <= 4096 and 0 < height <= 4096 and bpp == 1):
        raise RuntimeError(f"不支持的格式：{width}x{height}, bpp={bpp}")
    camera = ctypes.c_void_p.in_dll(sdk, "im_pCameraBuffer")
    triple = ctypes.c_void_p.in_dll(sdk, "im_pTripleBuffer")
    rgb = np.empty((height, width, 3), dtype=np.uint8)
    writer = cv2.VideoWriter(
        str(out / "capture.avi"),
        cv2.VideoWriter_fourcc(*"MJPG"), 30, (width, height)
    )
    if not writer.isOpened():
        raise RuntimeError("视频文件创建失败")
    start = time.monotonic()
    times = []
    saved = False
    while time.monotonic() - start < 10:
        if sdk.iCameraGrabFrame() == 0:
            continue
        camera.value, triple.value = triple.value, camera.value
        if not triple.value:
            raise RuntimeError("SDK 返回空图像指针")
        sdk.bayer2rgb24(rgb.ctypes.data, triple, width, height)
        frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        elapsed = time.monotonic() - start
        times.append(elapsed)
        writer.write(frame)
        if elapsed >= 1 and not saved:
            raw = np.ctypeslib.as_array(
                ctypes.cast(triple, ctypes.POINTER(ctypes.c_uint8)),
                shape=(height, width)
            ).copy()
            if not cv2.imwrite(str(out / "photo.jpg"), frame):
                raise RuntimeError("照片保存失败")
            if not cv2.imwrite(str(out / "raw_gray.png"), raw):
                raise RuntimeError("原始图保存失败")
            saved = True
    writer.release()
    writer = None
    if len(times) < 2 or not saved:
        raise RuntimeError(f"有效帧不足：{len(times)}")
    report = {
        "width": width,
        "height": height,
        "frames": len(times),
        "capture_seconds": time.monotonic() - start,
        "measured_fps": (len(times) - 1) / (times[-1] - times[0]),
        "max_frame_gap_seconds": float(np.diff(times).max()),
        "sdk_packet_errors": ctypes.c_int.in_dll(sdk, "g_pack_e").value,
    }
    (out / "stats.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    print("文件已保存至：", out, flush=True)
finally:
    if writer is not None:
        writer.release()
    print("调用 FreeiCamera；当前 SDK 在此阶段可能断言崩溃", flush=True)
    sdk.FreeiCamera()
PY
```

**5. 转换 MP4 并验证解码**

确认本轮 `stats.json` 和 `capture.avi` 已生成后再执行。AVI 按 30 fps 写入，实际采集约 27 fps；下面根据统计调整时间轴。输出可能补帧，不能用 MP4 的 30 fps 代替相机实测帧率。

```bash
TIME_SCALE="$(python3 -c \
  'import json,os; s=json.load(open(os.environ["TEST_DIR"]+"/stats.json")); print(30/s["measured_fps"])')"
```

确认上一步成功后转换：

```bash
ffmpeg -hide_banner -loglevel error \
  -itsscale "$TIME_SCALE" -i "$TEST_DIR/capture.avi" \
  -an -c:v libx264 -preset fast -crf 20 \
  -pix_fmt yuv420p -movflags +faststart \
  -n "$TEST_DIR/video.mp4"

ffprobe -v error -count_frames -select_streams v:0 \
  -show_entries stream=codec_name,width,height,avg_frame_rate,nb_read_frames:format=duration,size \
  -of json "$TEST_DIR/video.mp4"

ffmpeg -hide_banner -v error -i "$TEST_DIR/video.mp4" -f null -
```

在有图形桌面的终端查看文件：

```bash
xdg-open "$TEST_DIR/photo.jpg"
xdg-open "$TEST_DIR/video.mp4"
```

**6. 本次实测结果（2026-10-23）**

| 指标 | 第一轮 | 第二轮 |
|---|---:|---:|
| 分辨率 | 752×480 | 752×480 |
| 帧数 | 270 | 269 |
| 采集时间 | 10.005 秒 | 10.006 秒 |
| 实测帧率 | 27.031 fps | 27.027 fps |
| 最大帧间隔 | 39.01 ms | 38.90 ms |
| 完全相同的相邻帧（原测试另行统计） | 0 | 0 |
| SDK `g_pack_e` 计数 | 1 | 1 |

SDK 初始化返回 `0`。第一轮 MP4 为 H.264、752×480、299 帧（含补帧）、9.967 秒，完整解码无错误；第二轮重新打开设备采集成功。两轮释放时均出现：

```text
libusb/os/threads_posix.h:46: usbi_mutex_lock:
Assertion `pthread_mutex_lock(mutex) == 0' failed.
```

图片存在模糊、网格纹理和局部过曝，原始灰度图也有类似现象，尚需核对镜头、对焦和传感器输出模式，不能仅凭视频可解码判定成像正常。测试期间未发现该相机 USB 断连，结束后未发现占用进程。

测试后用 `fuser -v "$USB_NODE"` 检查是否仍被占用。输出位于临时目录，重启可能清理，需要保留的文件应另行保存。若本轮新加的临时 ACL 不再需要，可执行以下命令撤销；不要删除原先已有的用户授权：

```bash
sudo setfacl -x u:unitree "$USB_NODE"
```

### RTK 串口

RTK 串口启动参数来自 [rtk.sh](rtk.sh)。先加载 ROS 环境，并确认实际端口和权限；不要与已有串口节点重复运行。

```bash
ls -l /dev/ttyUSB*
ros2 run nmea_navsat_driver nmea_serial_driver \
  --ros-args -p port:=/dev/ttyUSB0 -p baud:=115200
```

## 9. 网络、资源与代码状态

历史中常用 `ip a`、`ping`、`df -h`、`git status` 和 `git pull`。
以下以只读排查为主，目标地址用现场设备地址替换：

```bash
ip a
ip route
TARGET_HOST='REPLACE_WITH_DEVICE_ADDRESS'
ping -c 4 "$TARGET_HOST"
df -h
du -sh ~/rosbag2_* ~/ros2_bags
git status
git branch
git diff
```

Git 命令应在对应仓库目录执行；`git pull` 会修改工作区，先检查本地改动，不要用 `restore`、`reset` 直接覆盖未保存的工作。

## 10. 历史记录中的注意事项

- `cd..` 应为 `cd ..`；`--packages-selet` 应为 `--packages-select`。
- `poincloud.enable` 应为 `pointcloud.enable`，并用 `--show-args` 核对当前驱动。
- `grep EOORR` 不能正确筛选 `ERROR`；筛选启动日志时需考虑标准错误输出。
- [na.sh](na.sh) 引用了 `~/nav.sh`，而现有配置为 [nav.rviz](nav.rviz)；该脚本还会停用 `/map_server`，不应作为纯查看命令使用。
- `sudo export ...` 不能设置当前 shell 环境；当前终端用 `export`，需要特权进程时须明确传递其所需环境。
- 不复制历史里的全局 USB 放权、固件恢复、批量杀进程、删除文件等操作作为日常步骤。
- Bash 历史可能缺少尚未写入文件的终端记录，也不记录命令是否成功。本文件是速查文档，不是已验证的部署手册。