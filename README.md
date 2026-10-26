# Robot Agent
Robot operator assistant with cluade agent sdk
![agent](<agent.png>)
## GitHub Copilot模型列表

以下模型名称根据 [GitHub Copilot支持的AI模型](https://docs.github.com/en/copilot/reference/ai-models/supported-models) 整理（2026-10-23核对）。实际可用性取决于Copilot套餐、使用的产品界面以及组织管理员策略；预览模型也可能随时变化。配置中的 `github_copilot/` 名称按Copilot模型名转换为LiteLLM模型标识，仍需结合LiteLLM版本和账户权限确认。

```text
github_copilot/gpt-5.3-codex
github_copilot/gpt-5.4-nano
github_copilot/gpt-5.6-luna
github_copilot/gpt-5.6-sol
github_copilot/gpt-5.6-terra
github_copilot/gpt-6-astra
github_copilot/gpt-6-luna
github_copilot/gpt-6-sol
github_copilot/gpt-6.1-sol
github_copilot/claude-fable-5
github_copilot/claude-fable-5.1
github_copilot/claude-haiku-4.5
github_copilot/claude-haiku-5.5
github_copilot/claude-opus-4.8
github_copilot/claude-opus-4.8-fast
github_copilot/claude-opus-5
github_copilot/claude-opus-5.5
github_copilot/claude-sonnet-4.6
github_copilot/claude-sonnet-5
github_copilot/claude-sonnet-5.5
github_copilot/gemini-3.8-flash
github_copilot/gemini-4-argon
github_copilot/mai-code-1.1-flash
github_copilot/kimi-k3
github_copilot/grok-4.5
github_copilot/grok-4.6
github_copilot/grok-4.7
```

`claude-opus-4.8-fast` 对应文档中的 Claude Opus 4.8 fast mode 预览选项。Claude Fable 模型可能需要GitHub批准并由组织管理员启用。若某个标识在你的LiteLLM版本或Copilot账户中不可用，请以Copilot模型选择器和LiteLLM [GitHub Copilot provider文档](https://docs.litellm.ai/docs/providers/github_copilot) 为准。

## 安装litellm
Install AI Gateway (Proxy Server)
https://docs.litellm.ai/docs/providers/github_copilot

```bash
conda create -n claude-code python=3.12

pip install litellm[proxy]

litellm --config config.yaml

# RUNNING on http://0.0.0.0:4000
```

## 启动Claude Code并连接LiteLLM
先在一个终端启动LiteLLM代理，然后在另一个终端设置Claude Code的API地址和模型并启动。

Linux/macOS:

```bash
ANTHROPIC_BASE_URL="http://127.0.0.1:4000" \
ANTHROPIC_AUTH_TOKEN="sk-cc-github-litellm" \
ANTHROPIC_MODEL="claude-haiku-5.5" \
claude
```

Windows PowerShell:

```powershell
$env:ANTHROPIC_BASE_URL = "http://127.0.0.1:4000"
$env:ANTHROPIC_AUTH_TOKEN = "sk-cc-github-litellm"
$env:ANTHROPIC_MODEL = "claude-opus-5.5"
claude
```

`ANTHROPIC_MODEL` 可以替换为 `config.yaml` 中的任一 `model_name`。如果已设置其他 Claude API 凭据，请确保当前终端使用上述地址和凭据。

## 验证本地调用Claude Opus 5.5
```bash
python test_claude_opus_55.py
```

## 安装Claude Code Router

https://github.com/musistudio/claude-code-router

```bash
npm install -g @anthropic-ai/claude-code
npm install -g @musistudio/claude-code-router
```

## 机器人 Agent 网页 Demo

运行在机器人上的 Web 运维助手：操作员在浏览器中与 Claude Agent 对话，Agent 通过 **Skills** 调用 `./robot` 命令行工具，完成检查设备状态、控制机械臂、相机拍照与识别、查看日志与排查问题、SLAM 建图等任务。

目标硬件：**Unitree B2 四足机器人**（ROS 2 Humble，`unitree_ros2`）、一台 **AgileX Piper 机械臂**（`piper_sdk`，CAN 口 `can0`），以及 5 个相机：**B2 自带前、后相机**（B2 视频服务）、**RealSense D455**（ROS 图像话题）、**Orbbec Gemini**（RGB，暂无图像话题）和 **iCamera** 多光谱相机（厂商 SDK）。Agent、导航（Nav2、定位、巡检、测绘）、机械臂和相机都在 B2 的 PC4（x86_64）上运行；ROS 工作空间为 `~/dog_ws/infai_work`。

架构参考 Anthropic 官方 [claude-agent-sdk-demos](https://github.com/anthropics/claude-agent-sdk-demos)：

- `simple-chatapp`：每个会话一个长连接 Agent（Python 版用 `ClaudeSDKClient`），WebSocket 推送事件，支持多会话。
- `ask-user-question-previews`：通过 `can_use_tool` 回调把需要人工决定的工具调用发到浏览器，等待操作员回复。

```text
浏览器 (index.html) ──WebSocket/REST──▶ server.py (FastAPI)
                                          │  每个会话一个 ClaudeSDKClient
                                          │  PreToolUse hook → robot_agent/safety.py 分级
                                          │  can_use_tool → 浏览器审批卡片
                                          ▼
                              Claude Code CLI ──Skill/Bash──▶ ./robot (robot_tools)
                                                                 ├─ status  健康检查
                                                                 ├─ weather 无锡天气（Open-Meteo）
                                                                 ├─ logs    ROS/系统/内核日志
                                                                 ├─ camera  拍照 / look 识别
                                                                 ├─ arm     Piper 机械臂
                                                                 ├─ traj    机械臂轨迹录制 / 回放（示教模式）
                                                                 ├─ piper   同上，使用 AgiLex Gradio 版录制 / 回放逻辑（已移除界面）
                                                                 ├─ survey  植株巡检：回放巡检动作，Gemini 拍照并录制视频
                                                                 ├─ base    B2 运动
                                                                 ├─ map     SLAM 建图
                                                                 └─ estop   急停
```

### 目录

| 路径 | 说明 |
|---|---|
| `server.py` | FastAPI 服务：会话、WebSocket、机器人状态、急停、媒体文件（图片 / 视频 / 点云，`/api/artifacts` 列表） |
| `robot_agent/session.py` | `ClaudeSDKClient` 会话、PreToolUse 安全钩子、操作员审批 |
| `robot_agent/media.py` | 可预览的媒体类型与目录、工具输出中 `IMAGE:` / `VIDEO:` / `POINTCLOUD:` 行的解析 |
| `robot_agent/store.py` | 会话持久化：聊天记录与 Claude 对话记录保存到 `.claude/sessions/` |
| `robot_agent/skills.py` | 界面中的技能管理：列出、查看、编辑、新建、停用（移到 `.claude/skills-disabled/`）和删除 `.claude/skills/` 下的技能 |
| `robot_agent/suggestions.py` | 界面欢迎页的提示词（按语言保存到 `.claude/sessions/suggestions.json`） |
| `robot_agent/instructions.py` | 界面中编辑智能体规则 `CLAUDE.md`（保存时检查版本，避免覆盖他处的修改） |
| `robot_agent/safety.py` | Bash 命令安全分级（allow / ask / deny） |
| `index.html` | 操作界面：会话、工具卡片、审批、媒体预览（图片、MP4/WebM 视频、PCD/PLY 点云 3D 查看器、全屏查看与媒体浏览）、状态面板（含 B2 电机最高温度，< 70 °C 为安全）、侧栏最近 5 个会话与“全部会话”窗口（可搜索）、提示词、技能与 CLAUDE.md 管理窗口、仿真/真机切换、中英文与深浅色主题、E-STOP |
| `static/` | 前端静态文件：`pointcloud-viewer.js`（点云查看器）与本地 three.js r186（`vendor/three/`，离线可用，按需加载） |
| `robot`, `robot_tools/` | 机器人命令行工具（自动 source ROS 与工作空间） |
| `robot.yaml` | 机器人配置：模式、ROS/DDS、话题、速度上限、机械臂 CAN 口、相机、建图 |
| `.claude/skills/` | Agent Skills：`robot-status`、`robot-briefing`、`robot-logs`、`robot-camera`、`piper-arm`、`arm-trajectory`、`piper-gradio`、`plant-survey`、`b2-locomotion`、`robot-mapping`、`robot-troubleshooting` |
| `.claude/sessions/` | 运行时生成：`chats/<id>/` 会话标题与事件记录，`transcripts/` Claude Code 对话记录（服务重启后恢复会话与 Agent 上下文） |
| `CLAUDE.md` | Agent 的操作规则（项目记忆，随会话加载） |
| `artifacts/` | 运行时生成：`captures/` 照片、`videos/` 视频、`pointclouds/` 点云、`maps/` 地图、`trajectories/` 机械臂轨迹 CSV（仿真录制的合成轨迹在 `sim/trajectories/`，真机不会回放）、`logs/` 服务与建图日志 |

### 媒体预览

工具输出中形如 `IMAGE: artifacts/<目录>/<文件>`、`VIDEO: …`、`POINTCLOUD: …` 的行（`robot_tools/common.py` 的 `image_line` / `video_line` / `pointcloud_line`）会在工具卡片下直接显示：图片缩略图、带进度条的视频播放器（适合约 30 秒的短片）、点云卡片。点击后全屏查看，`←` `→` 切换、`Esc` 关闭；点云在 three.js 查看器中显示（拖动旋转、右键平移、滚轮缩放，可按 RGB / 高度 / 强度着色、调整点大小）。侧栏 **媒体 → 浏览** 可查看 `artifacts/` 下所有媒体文件。

- 支持的目录：`captures`、`maps`、`videos`、`pointclouds`；格式：jpg/jpeg/png/gif/webp、mp4/webm、pcd（ascii / binary / binary_compressed）/ply。
- 浏览器只能播放 H.264 编码的 MP4（OpenCV 默认的 `mp4v` 无法播放），否则请用 WebM（VP8/VP9）。视频接口支持 HTTP Range，可拖动进度。
- three.js 已放在本地 `static/vendor/three/`，机器人离线时也可使用；只有打开点云时才会加载。点云查看需要浏览器支持 WebGL。

### 安全机制

Agent 的每条 Bash 命令都会先经过 `PreToolUse` 钩子分级：

| 分级 | 示例 | 处理 |
|---|---|---|
| 自动允许 | `./robot status`、`./robot weather`、`./robot arm teach-button`（仅仿真）、`./robot logs`、`./robot camera look`、`./robot traj list/show`、`./robot piper list/show`、`./robot survey check`、`./robot camera devices`、`ros2 topic list`、`journalctl`、`./robot estop`、`arm stop`、`base stop` | 直接执行 |
| 需要审批 | `./robot arm move-joints/home/gripper/enable/take-control`、`./robot traj record/play`、`./robot piper record/play`、`./robot survey run`、`./robot camera set-source`、`./robot base stand-up/move/damp`、`./robot map start`、`ros2 launch`（`infai_bringup`/`dog_inspection`/`dog_survey` 等会驱动机器人，单独提示）、`ros2 bag play`、巡检/测绘服务调用、修改网络/服务的命令、未知命令 | 浏览器显示审批卡片，操作员批准或拒绝（默认 120 秒无响应自动拒绝） |
| 禁止 | `./robot base recovery-stand`（翻身起立会压坏机身上的机械臂和设备；仅当 `robot.yaml` 的 `base.allow_recovery_stand: true` 时改为需要审批）、`sudo`、`reboot`、`rm -rf /`、`cansend`、直接 `ros2 topic pub` 到 `/api/sport/request`、`/cmd_vel*`（含 `/cmd_vel_nav`）或 `/keyboard_ctl`、写 `/dev`/`/sys`，以及不存在的 `./robot` 子命令 | 直接拒绝并告诉 Agent 原因 |

另外：

- `./robot` 内置硬件限制：B2 速度/时长上限（`robot.yaml` 的 `base.max_*`，每次移动结束都会发送 StopMove）、低电量/故障/电机过热/趴下时拒绝行走，`/cmd_vel_nav` 上正在有导航速度指令时拒绝 `base move`（Nav2 空闲时只提示）；Piper 关节角度范围检查（`robot.yaml` 的 `arm.joint_limits_deg`：机械臂装在机身上的实际可达范围，只能比官方范围更窄）、单次关节变化上限（`arm.max_step_deg`）、速度上限、夹爪行程检查；`move-joints/home/gripper` 仅在 CAN 指令模式、状态正常且未在运动时执行（上电或退出示教模式后先 `./robot arm take-control`，按 AgiLex 流程急停并等待 2、3、5 关节回到静止位再切换），超时未到位时就地保持；机械臂命令与 `traj record/play` 互斥（`arm stop` 不受影响）。
- `./robot traj record/play` 调用 AgiLex 的 `recordTrajectory_new.py` / `playTrajectory_new.py`（`robot.yaml` 的 `arm.trajectory_dir`）：脚本文件不修改，运行时设置录制时长、速度（不超过 `arm.max_speed`）、倍速（≤ 1.0）和轨迹路径，自动应答回车提示，每次运行有超时；回放前检查轨迹关节范围，示教模式或机械臂故障时拒绝回放。
- `./robot piper record/play/list/show`（`piper-gradio` 技能）：使用 AgiLex Gradio 版 `record.py` / `play.py` 的录制 / 回放逻辑：去掉 Gradio 界面后移植为 `robot_tools/piper_record.py`（`Recorder`）/ `robot_tools/piper_play.py`（`Player`），行为与原文件一致（测试用同一个模拟机械臂运行两者，逐条比对发送的指令和录制的轨迹行），不再依赖 `~/Agilex-College` 下的原文件；CAN 口取自 `robot.yaml`，与 `traj` 共用机械臂锁、关节范围检查、速度 / 倍速（≤ 1.0）/ 循环次数（≤ 5）上限和超时，回放中检测到急停立即停止发送轨迹点；B2 未站立静止时拒绝录制和回放（`base.require_standing_for_arm`）。录制在机械臂移动后回到静止 `--stop-when-still` 秒（默认 3 s）时自动结束并保存 CSV，`--seconds` 为最长时长。仿真模式同样走示教流程：操作员说已按下示教按钮后，Agent 用仅限仿真的 `./robot arm teach-button` 模拟按键（真机拒绝），录制模拟“拉出再回位并静止”的动作。额外参数：录制轮询间隔 `--poll`、`--no-gripper`、每轮回放后的停顿 `--interval`。轨迹与 `traj` 共用 `artifacts/trajectories/`，录制器的带时间戳副本存于 `artifacts/trajectories/sessions/`。
- `./robot survey check/run`（`plant-survey` 技能）：`check` 检查 B2 是否站立静止、巡检动作轨迹（`artifacts/trajectories/survey.csv`，缺失时引导操作员示教 15–30 s）、机械臂状态和巡检相机（`robot.yaml` 的 `survey`，默认 `orbbec_gemini`，拍一张测试图）；`run` 用 `traj play` 回放巡检动作，从回放开始在整个动作过程中均匀拍摄 `--photos` 张照片（默认 8 张，0–10，`artifacts/captures/<时间>_survey_orbbec_gemini_NN.jpg`），同时录制 20 s 视频（`artifacts/videos/<时间>_survey_orbbec_gemini.mp4`）。B2 未站立静止、相机或轨迹不可用时在运动前拒绝执行。Gemini 的 V4L2 设备由操作员选择：`./robot camera devices` 列出采集节点（by-id 路径、厂商、彩色/深度格式），`./robot camera set-source` 测试一帧后保存到 `artifacts/run/camera_sources.json`（覆盖 `robot.yaml`）。
- 现场简报（`robot-briefing` 技能）：`./robot status` 的问题列表在 B2 电量低于 20 %、B2 腿部电机或机械臂电机/驱动器温度高于 60 °C 时告警（`robot.yaml` 的 `status`）；`./robot base state` 显示 B2 姿态（站立静止、运动中、趴下等）；`./robot weather` 从 Open-Meteo（无需 API Key）读取 `site`（默认无锡）的当前天气和预报，只读、无需审批，需要联网。
- 页面右上角 **E-STOP** 直接在服务端执行 `./robot estop`（B2 StopMove + 机械臂急停），同时中断所有 Agent 会话，不经过模型。它不能替代硬件急停按钮。
- 急停后机械臂保持急停状态（B2 只是停止行走，无需恢复）。机械臂报告急停时 E-STOP 旁出现 **↺ 恢复机械臂** 按钮：确认后服务端执行 `./robot arm take-control`（`POST /api/recover`）——机械臂缓慢下沉到折叠静止位（关节 2、3、5）后解除急停并以 CAN 指令模式重新使能，最长约 60 s；有智能体正在执行时拒绝。恢复过程中按 E-STOP 会立即终止恢复，机械臂保持急停。
- `./robot base move` 每 0.1 s 发送一次 Move（最长 `base.max_duration` 秒），结束时（包括被中断或进程收到 SIGTERM/SIGINT）总会发送 StopMove。`./robot estop`、`./robot base stop` 和页面 E-STOP 会写入 `artifacts/run/base_stop`，正在执行的 move 在下一次发送前检测到后立即停止发送并发送 StopMove（约 0.1 s 内）。
- Agent 只开放 `Bash`、`Read`、`Glob`、`Grep`、`Skill` 工具，不能修改项目文件。

### 安装与运行

在机器人电脑上（ROS 2 Humble 已安装）：

```bash
# 服务端 Python 环境
pip install claude-agent-sdk fastapi uvicorn websockets pyyaml
# 或按 pyproject.toml 安装（可编辑模式；可选 extras：robot=piper_sdk，proxy=LiteLLM，dev=pytest）
pip install -e ".[robot,dev]"

# 机器人工具使用系统 Python（/usr/bin/python3，可 import rclpy）
pip3 install --user piper_sdk opencv-python pyyaml

# 编译 unitree_ros2 的 cyclonedds_ws，并在 robot.yaml 的 ros.setup_files 中列出各工作空间
# 激活机械臂 CAN 口（由 piper-can.service 完成；手动激活需要 sudo，由操作员执行）
cd ~/piper_sdk/piper_sdk && bash can_activate.sh can0 1000000
```

根据机器人修改 `robot.yaml`：`ros.setup_files`（默认包含 `~/dog_ws/infai_work` 与 `~/unitree_ros2/cyclonedds_ws`，不存在的文件会跳过）、`ros.dds_interface`（连接 B2 的网卡，192.168.123.x 网段）、机械臂 CAN 口（`arm.can_port`，由 `piper-can.service` 激活）、相机、`services`（`./robot status` 显示其运行状态，`./robot logs --unit` 查看日志）、`monitor_topics`（IMU `/dog_imu_raw`、RTK `/fix`、SLAM 里程计、`/cmd_vel_nav`，仅作信息显示）、`mapping`（激光雷达 `/rslidar_points`）。

相机（`robot.yaml` 的 `cameras`，`source` 支持 `ros:<图像话题>`、`v4l2:<设备>`、`unitree:<B2 视频服务>`、`icamera:<SDK 目录>`；可选 `fallback` 为主来源不可用时的备用来源）：

| 名称 | 相机 | 来源 |
|---|---|---|
| `b2_front` / `b2_back` | B2 自带前 / 后相机 | `unitree:front_videohub` / `unitree:back_videohub`：通过 `/api/<服务>/request` 与 `/api/<服务>/response`（`unitree_api` 消息，API 1001 `GetImageSample`）每次获取一张 JPEG |
| `realsense_d455` | Intel RealSense D455 彩色图像 | `ros:/camera/camera/color/image_raw`（realsense2_camera）；ROS 驱动未运行时备用 `v4l2:/dev/video4` |
| `orbbec_gemini` | Orbbec Gemini RGB | 暂无图像话题（`source` 为空，拍照提示“not set up yet”，状态显示 `not configured`） |
| `icamera` | CCJT iCAMERA 多光谱相机（USB `ae86:0001`，752×480，9 波段 624–776 nm） | `icamera:~/icamera_demo`：在子进程中通过 ctypes 加载 x86_64 的 `libiCamera.so` + `libgraph.so` + libusb（首次使用时用 gcc 生成加载库到 `artifacts/run/`），约 1 秒后取一帧，经 `bayer2rgb24` 转为伪彩色图。`FreeiCamera()` 释放时的 libusb 断言崩溃不影响已保存的图像。`icamera.service` 或 `ConsumerMosaicDemo` 运行时拒绝拍照（相机只能被一个程序使用）；缺少 USB 权限时提示操作员执行 `setfacl` |

先启动 LiteLLM 代理，再启动服务：

```bash
CC_BASE_URL="http://127.0.0.1:4000" \
CC_AUTH_TOKEN="sk-cc-github-litellm" \
CC_MODEL="claude-opus-5.5" \
uvicorn server:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 。如需从其他电脑访问（例如笔记本连接机器人），设置访问令牌并监听所有网卡：

```bash
ROBOT_AGENT_TOKEN="<随机长字符串>" uvicorn server:app --host 0.0.0.0 --port 8000
# 浏览器打开 http://<机器人IP>:8000/?token=<随机长字符串>
```

#### 开发调试脚本

`scripts/dev-start.sh` 一条命令启动开发环境：LiteLLM 网关（`:43429`，已在运行则复用，日志 `artifacts/logs/litellm-dev.log`）和 Web 服务（`:8000`，先停掉端口上的旧服务；自动选用装有 uvicorn / fastapi / claude-agent-sdk 的 Python）。`scripts/dev-clear.sh` 停止这两个进程（连同 Agent 子进程）并清理 `__pycache__/`、`.pytest_cache/`；会话记录和 `artifacts/` 保留。

```bash
scripts/dev-start.sh              # 前台运行，Ctrl+C 停止服务（LiteLLM 继续运行）
scripts/dev-start.sh --reload     # 修改 .py 文件后自动重启服务
scripts/dev-start.sh --bg         # 后台运行，输出在 artifacts/logs/server-dev.out
CC_MODEL=claude-opus-5.5 ROBOT_MODE=real scripts/dev-start.sh   # 覆盖默认值（sim、gpt-6-luna）

scripts/dev-clear.sh              # 停止服务和开发用 LiteLLM，清理缓存
scripts/dev-clear.sh --keep-llm   # 只停止服务
scripts/dev-clear.sh --all        # 同时停止本项目启动的其他 uvicorn / litellm（包括 :4000 网关）
```

可覆盖的变量：`HOST`、`PORT`、`LITELLM_PORT`、`LITELLM_CONFIG`、`PYTHON`、`LITELLM`、`ROBOT_MODE`、`CC_MODEL`、`CC_BASE_URL`、`CC_AUTH_TOKEN`（见 `scripts/dev-env.sh`）。

### 在机器人（PC4）上部署：systemd 原生运行（推荐）

PC4 上的 ROS 2 导航等服务均由 systemd 原生启动，Agent 同样以 systemd 服务原生运行，与它们共享主机网络（B2 的 CycloneDDS）、CAN、相机/USB 设备、ROS 工作空间和系统日志（`systemctl` / `journalctl` 可直接查看 `piper.service` 等服务），无需 Docker。

```bash
# 1. 在开发机上同步代码到 PC4（不覆盖 PC4 上的 artifacts/ 与会话）
rsync -av --exclude artifacts/ --exclude .claude/sessions/ --exclude .venv/ --exclude .venv-litellm/ \
  --exclude __pycache__/ --exclude .pytest_cache/ ./ <user>@<PC4>:~/robot-agent/

# 2. 在 PC4 上以运行机器人的用户执行（不要用 root；需要 sudo 权限）
cd ~/robot-agent
litellm --config config.yaml        # 仅首次：完成 GitHub Copilot 登录后 Ctrl+C（令牌缓存在 ~/.config/litellm/github_copilot）
./deploy/install.sh                 # 网关在其他机器上时：WITH_LITELLM=0 ./deploy/install.sh
```

[deploy/install.sh](deploy/install.sh) 会：

- 用 `/usr/bin/python3` 创建 `.venv`（`--system-site-packages`，可使用 ROS 2 的 `rclpy` 与已安装的 `piper_sdk`；约束 `numpy<2`，避免破坏 ROS Humble 的 numpy 1.x），安装 `.[robot]`；
- 安装 `litellm.service`（`127.0.0.1:4000`，使用 PATH 中的 `litellm`，或新建 `.venv-litellm`；`LITELLM_BIN=` 可指定路径）；
- 将用户加入 `video`、`dialout`、`plugdev`、`systemd-journal` 组（相机、串口、`./robot logs --source system`）；
- 首次创建 `/etc/robot-agent/robot-agent.env`（随机 `ROBOT_AGENT_TOKEN`、网关地址、模型、`ROBOT_MODE` 等，重复安装不会覆盖），模板见 [deploy/robot-agent.env.example](deploy/robot-agent.env.example)；
- 安装并启用 [robot-agent.service](deploy/robot-agent.service)（开机自启，`Restart=on-failure`，只用 `Wants=` 依赖网关，不依赖机器人服务，这样机器人服务故障时 Agent 仍可启动并排查），最后检查 `http://127.0.0.1:8000/` 是否可访问。

```bash
sudo systemctl status robot-agent litellm
journalctl -u robot-agent -f                     # 服务日志；./robot logs --source agent 读取 artifacts/logs/server.log
sudo nano /etc/robot-agent/robot-agent.env && sudo systemctl restart robot-agent
# 更新代码：在开发机上重新 rsync，然后 sudo systemctl restart robot-agent（依赖有变化时重新运行 install.sh）
```

浏览器打开 `http://<PC4 IP>:8000/?token=<ROBOT_AGENT_TOKEN>`。注意：停止或重启 `robot-agent.service` 会结束 Agent 启动的所有子进程，包括 `mapping.backend: command` 时 `./robot map start` 启动的 SLAM 进程（`unitree` 后端在 B2 上运行，不受影响）。`dmesg` 受 `kernel.dmesg_restrict` 限制时 `./robot logs --source kernel` 无权限读取。

### Docker

镜像基于 `ros:humble-ros-base`（Python 3.10），服务端与 `./robot` 共用系统 Python，以非 root 用户 `robot` 运行，默认监听 `0.0.0.0:8000`（可用 `HOST` / `PORT` 修改）。`artifacts/` 与 `.claude/sessions/` 为数据卷。

```bash
docker build --build-arg USER_UID=$(id -u) --build-arg USER_GID=$(id -g) -t robot-agent .

# 仿真模式
docker run --rm -p 8000:8000 -e ROBOT_MODE=sim -e ROBOT_AGENT_TOKEN=<令牌> \
  --add-host=host.docker.internal:host-gateway -e CC_BASE_URL=http://host.docker.internal:4000 \
  robot-agent
```

真机运行需要 `--network host --ipc host`（B2 的 DDS 与机械臂 SocketCAN），并挂载 ROS 工作空间（`robot.yaml` 中的 `~` 在容器内为 `/home/robot`）、相机设备、USB（iCamera）和宿主机日志；完整命令见 [Dockerfile](Dockerfile) 开头注释。容器内 `systemctl` 无法查询宿主机服务，`dmesg` 可能因 `kernel.dmesg_restrict` 无权限。

### 仅仿真镜像与 Kubernetes 部署

[Dockerfile.sim](Dockerfile.sim) 构建只能运行仿真模式的轻量镜像（`python:3.10-slim`，不含 ROS 2、CAN、piper_sdk），镜像内设置 `ROBOT_MODE_LOCK=sim`：界面的真机按钮被禁用，`POST /api/mode` 切换到真机返回 403，`./robot` 也始终以仿真模式运行。镜像以 UID 10001 / GID 0 运行，兼容任意 UID（如 OpenShift）。

```bash
docker build -f Dockerfile.sim -t <镜像仓库>/robot-agent-sim:<标签> . && docker push <镜像仓库>/robot-agent-sim:<标签>

kubectl create namespace robot-agent-sim
kubectl -n robot-agent-sim create secret generic robot-agent-sim-secrets \
  --from-literal=ROBOT_AGENT_TOKEN=<令牌> --from-literal=CC_AUTH_TOKEN=<网关令牌>
# 修改 k8s/sim/kustomization.yaml 中的镜像和 CC_BASE_URL（集群内可访问的 LiteLLM 网关）
kubectl apply -k k8s/sim
kubectl -n robot-agent-sim port-forward svc/robot-agent-sim 8000:80   # 或启用 ingress.yaml
```

[k8s/sim/](k8s/sim/) 包含单副本 Deployment（会话与 WebSocket 保存在进程内，使用 `Recreate` 策略）、ClusterIP Service、`artifacts/` 与 `.claude/sessions/` 两个 PVC，以及可选的 ingress-nginx 示例（WebSocket `/ws` 需要较长的代理超时）。

### 仿真模式（无硬件）

```bash
ROBOT_MODE=sim uvicorn server:app --port 8000
ROBOT_MODE=sim ./robot status
```

仿真模式下 B2、机械臂、建图和 ROS 相机返回带 `[SIM]` 标记的模拟数据，状态保存在 `artifacts/sim/`；V4L2 相机仍然使用真实设备，日志与计算资源信息也是真实数据。真实模式下如果硬件不可达，工具会返回明确的错误（退出码 3），不会返回模拟数据。

界面顶栏的 **仿真 / 真机（SIM / REAL）** 开关可在运行时切换模式（切换到真机前会弹窗确认；有智能体正在执行时服务端拒绝切换，返回 409）。所选模式写入 `artifacts/run/mode`，`./robot` 每次执行都会读取，因此已打开的会话立即生效；每个会话中会显示切换提示，并在下一条消息中告知智能体。模式优先级：`ROBOT_MODE_LOCK` > `ROBOT_MODE` 环境变量 > `artifacts/run/mode` > `robot.yaml`。服务启动时如设置了 `ROBOT_MODE`，会把它写入 `artifacts/run/mode` 并从服务进程环境中移除（否则智能体进程继承该变量后界面无法切换）；删除 `artifacts/run/mode` 即恢复 `robot.yaml` 中的模式。

界面语言（English / 中文）和主题（浅色 / 深色，默认跟随系统）在侧栏底部切换，保存在浏览器本地。

界面支持 iPad（及手机）：宽度小于 1024 px（iPad 竖屏、分屏）时侧栏收起为 ☰ 抽屉，横屏和 12.9 英寸竖屏保留侧栏；触屏设备上按钮放大到约 44 px（E-STOP、审批的批准 / 拒绝、发送、会话行），删除按钮常显，输入框使用 16 px 字号（避免 Safari 聚焦时放大），图片查看器可左右滑动切换。在 Safari 中“添加到主屏幕”可全屏使用（适配圆角与主屏指示条的安全区域）。

侧栏只显示最近 5 个会话，**⋯ 全部会话** 打开可搜索的完整会话列表。侧栏 **管理** 中：

- **提示词**：编辑欢迎页卡片（每种语言一组，可增删、排序、恢复内置提示词），保存在服务端（`.claude/sessions/suggestions.json`），所有操作员共享。
- **技能**：查看和编辑 `.claude/skills/<名称>/SKILL.md`、新建、停用 / 启用（停用的技能移到 `.claude/skills-disabled/`，智能体看不到）和删除。保存前检查 front matter（`name` 必须与文件夹名一致，并需要 `description`）。修改从每个会话的下一条消息起生效：会话的智能体进程以原上下文（`resume`）重新启动并加载新的技能列表。
- **CLAUDE.md**：查看和编辑智能体规则（项目目录下的 `CLAUDE.md`：工作场景、技能与 `./robot` 用法、安全规则），Ctrl/⌘+S 保存。保存时检查文件版本：如果期间文件在别处被修改（例如编辑器中），保存会被拒绝，需先 **↻ 重新加载**。修改从每个会话的下一条消息起生效：智能体进程以原上下文重新启动并读取新规则。

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `CC_BASE_URL` / `CC_AUTH_TOKEN` | `http://127.0.0.1:43783` / `sk-cc-github-litellm` | 模型网关 |
| `CC_MODEL` | `claude-opus-5.5` | Agent 模型 |
| `CC_MAX_TURNS` | `40` | 每次请求的最大步数 |
| `ROBOT_MODE` | `robot.yaml` 中的 `mode` | `real` 或 `sim`；服务启动时写入 `artifacts/run/mode`，之后可在界面切换 |
| `ROBOT_MODE_LOCK` | 空 | 设置为 `sim`（或 `real`）后锁定模式，界面和 API 均不能切换（`Dockerfile.sim` 中为 `sim`） |
| `ROBOT_APPROVAL_TIMEOUT` | `120` | 审批超时（秒），超时自动拒绝 |
| `ROBOT_AGENT_TOKEN` | 空 | 设置后 API、WebSocket 和图片都需要令牌 |
| `ROBOT_SESSIONS_DIR` | `.claude/sessions` | 会话保存目录 |
| `ROBOT_VISION_MODEL` | 同 `CC_MODEL` | `./robot camera look` 使用的视觉模型 |
| `ROBOT_DDS_INTERFACE`、`ROBOT_ROS_SETUP`、`ROBOT_MAP_START_CMD` | | 覆盖 `robot.yaml` 对应配置 |

### 通过 LiteLLM + GitHub Copilot 网关使用时的注意事项

实测（2026-10-23）该网关存在两个限制，Demo 已做兼容：

1. **不转发 Anthropic `system` 字段。** 因此操作规则写在 `CLAUDE.md`（Claude Code 以对话上下文方式注入），`system_prompt` 只保留简短角色说明。
2. **`tool_result` 中的图片无法被模型识别。** Claude Code 的 `Read` 工具以这种方式返回图片，所以 Agent 改用 `./robot camera look`：该命令把图片作为用户消息中的图片块发送给模型并返回文字描述。直连 Anthropic API 时两种方式都可用。

### 建图后端

- `mapping.backend: unitree`：通过 `/qt_command`（`unitree_interfaces/msg/QtCommand`，3=开始建图，4=结束并保存）控制 B2 自带的 `unitree_slam`（LIO-SAM），进度读取 `/qt_notice`。需要 Unitree 提供的 `unitree_interfaces` ROS 2 消息包；Unitree 官方示例为 C++ / DDS，ROS 2 Python 绑定尚未在真机上验证。
- `mapping.backend: command`：在后台运行 `mapping.start_cmd`（默认 slam_toolbox），用 nav2 `map_saver_cli` 保存到 `artifacts/maps/` 并生成 PNG 预览。

### 测试

```bash
python -m pytest -q tests/          # 安全分级 + 服务端端到端（模拟 SDK 客户端）
ROBOT_MODE=sim ./robot status       # 工具冒烟测试
```

### 已知限制

- 会话保存在 `.claude/sessions/`，服务重启后自动恢复聊天记录，下一条消息通过 `resume` 继续原来的 Agent 上下文（如果无法恢复，保留聊天记录并开始新的 Agent 上下文）。重启时正在进行的请求不会继续执行，需要重新发送；未处理的审批请求视为拒绝。删除会话会同时删除这些文件。
- B2 的 `unitree_go` / `unitree_api` 接口按 `unitree_ros2` 与 `unitree_sdk2`（B2 sport API id 1001–1008；前后相机 `front_videohub` / `back_videohub` API 1001）实现，Piper 接口按本机 `piper_sdk` 0.6.1 实现；均已在仿真与无硬件环境下验证，**首次在真机上使用前请在安全环境中逐项验证**，并确认硬件急停可用。
- 待确认：本机建图使用 `infai_slam` / `dog_survey`（定位为 `infai_bringup localization.launch.py`），当前 `mapping` 后端（`unitree` 的 `/qt_command`、或 `command` 的 slam_toolbox）尚未适配；PC4 上是否编译了 `unitree_ros2`（`unitree_go`/`unitree_api` 消息，B2 状态、运动指令和前后相机都依赖它）也待确认。
- iCamera 拍照流程依据 `b2_commands.md` 中的 PC4 实测步骤实现，并用模拟 SDK 测试过（含释放时崩溃）；尚未在真机上运行。成像存在模糊、网格纹理和局部过曝，需核对镜头、对焦与传感器模式。
