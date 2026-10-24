import pytest

from robot_agent.safety import ALLOW, ASK, DENY, classify


@pytest.mark.parametrize("command", [
    "./robot status",
    "./robot status --json",
    "./robot logs --source kernel --since 2h",
    "./robot camera capture --camera orbbec_gemini",
    "./robot camera look --camera b2_front --prompt 'Is the path clear?'",
    "./robot arm status",
    "./robot base state",
    "./robot map status",
    "./robot map save --name lab_1",
    "./robot camera record --camera b2_front --seconds 5",
    "./robot camera --camera b2_front --seconds 5 record",
    "./robot camera record --camera=b2_front --seconds=5",
    "./robot map scan",
    "./robot map --name lidar_scan scan",
    "./robot estop",
    "./robot arm stop",
    "./robot base stop",
    "./robot --help",
    "ros2 topic list",
    "ros2 topic echo /sportmodestate --once",
    "timeout 5 ros2 topic hz /rslidar_points",
    "ros2 topic echo /cmd_vel_nav --once",
    "systemctl status piper-can.service --no-pager",
    "./robot logs --unit icamera.service",
    "ros2 node list && ros2 topic info /lowstate -v",
    "source /opt/ros/humble/setup.bash && ros2 topic list",
    "journalctl --no-pager -n 50 -u ssh",
    "ip -br addr",
    "ip -details link show can0",
    "candump -n 20 can0",
    "ping -c 3 192.168.123.161",
    "lsusb | grep -i orbbec",
    "dmesg 2>&1 | tail -n 50",
    "ls artifacts/captures > /dev/null",
    "nvidia-smi",
    "systemctl status ssh",
    "top -bn1 | head -20",
    "grep -r ERROR ~/.ros/log | tail",
    "cd /home && ls",
    "find . -name '*.log'",
])
def test_read_only_and_stop_commands_are_allowed(command):
    decision = classify(command)
    assert decision.action == ALLOW, decision


@pytest.mark.parametrize("command,category", [
    ("./robot arm move-joints --deg 0 10 -10 0 0 0", "motion"),
    ("./robot arm home", "motion"),
    ("./robot arm gripper --mm 30", "motion"),
    ("./robot arm enable", "motion"),
    ("./robot arm disable", "motion"),
    ("./robot arm resume", "motion"),
    ("./robot arm take-control", "motion"),
    ("./robot base move --vx 0.3 --duration 2", "motion"),
    ("./robot base --vx 0.3 --duration 2 move", "motion"),
    ("./robot base move --vx 0.2 --vyaw -0.3 --duration 1", "motion"),
    ("./robot base stand-up", "motion"),
    ("./robot base damp", "motion"),
    ("python3 -m robot_tools base move --vx 0.1", "motion"),
    ("/home/changxubo/cc-demo/robot base stand-down", "motion"),
    ("./robot map start", "system"),
    ("ros2 launch realsense2_camera rs_launch.py", "system"),
    ("ros2 param set /camera exposure 100", "system"),
    ("ip link set can0 up type can bitrate 1000000", "system"),
    ("systemctl restart orbbec", "system"),
    ("pkill -f slam_toolbox", "system"),
    ("echo hi > notes.txt", "system"),
    ("ros2 launch infai_bringup localization.launch.py pcd_name:=lab map_id:=1 path_id:=2",
     "motion"),
    ("ros2 launch dog_inspection dog_inspection.launch.py", "motion"),
    ("ros2 launch dog_survey dog_survey.launch.py", "motion"),
    ("ros2 bag play /home/unitree/ros2_bags/run1", "motion"),
    ("ros2 service call /dog_inspection dog_interfaces/srv/DogInspection '{}'", "motion"),
    ("ros2 topic pub /chatter std_msgs/msg/String '{data: hi}'", "system"),
    ("systemctl restart piper-can.service", "system"),
])
def test_actuation_and_state_changes_need_approval(command, category):
    decision = classify(command)
    assert decision.action == ASK, decision
    assert decision.category == category


@pytest.mark.parametrize("command", [
    "python3 -c 'import os'",
    "bash -c './robot status'",
    "echo $(./robot base move --vx 1)",
    "./robot status; `./robot base move`",
    "cat <<EOF > x.sh\n./robot base move\nEOF",
    "ros2 topic echo /lowstate",
    "env",
    "candump can0",
    "curl http://example.com",
])
def test_unknown_or_opaque_commands_need_approval(command):
    assert classify(command).action == ASK


@pytest.mark.parametrize("command", [
    "./robot dance",
    "./robot arm move --joints 20,0,0,0,0,0",
    "./robot camera snap --camera b2_front",
    "./robot base move --vx fast",
    "sudo ip link set can0 up",
    "./robot status && sudo reboot",
    "reboot",
    "shutdown -h now",
    "rm -rf /",
    "rm -rf ~",
    "cansend can0 151#0101",
    "ros2 topic pub --once /api/sport/request unitree_api/msg/Request '{}'",
    "ros2 topic pub /lowcmd unitree_go/msg/LowCmd '{}'",
    "echo 1 > /sys/class/gpio/export",
    "dd if=/dev/zero of=/dev/sda",
    "systemctl poweroff",
    "ros2 topic pub /cmd_vel_nav geometry_msgs/msg/Twist '{linear: {x: 0.5}}'",
    "ros2 topic pub --once cmd_vel geometry_msgs/msg/Twist '{}'",
    "ros2 topic pub -r 10 /robot1/cmd_vel geometry_msgs/msg/Twist '{}'",
    "ros2 topic pub --qos-profile sensor_data /cmd_vel_nav geometry_msgs/msg/Twist '{}'",
    "ros2 topic pub /keyboard_ctl std_msgs/msg/String '{data: w}'",
])
def test_dangerous_commands_are_denied(command):
    assert classify(command).action == DENY


def test_most_restrictive_segment_wins():
    assert classify("./robot status && ./robot base move --vx 0.2").action == ASK
    assert classify("./robot base state | grep mode").action == ALLOW
    assert classify("./robot status; sudo reboot").action == DENY
