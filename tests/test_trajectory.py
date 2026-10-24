import argparse
import math

import pytest

from robot_agent import safety
from robot_tools import config, trajectory
from robot_tools.common import ToolError

FAKE_RECORD = '''import os, time
if __name__ == "__main__":
    have_gripper = True
    record_time = 10.0
    timeout = 10.0
    CSV_path = os.path.join(os.path.dirname(__file__), "trajectory.csv")
    print("step 1: 请点击示教按钮进入示教模式")
    if record_time < 0:
        print("ERROR: 示教模式检测超时，请检查示教模式是否开启")
        exit()
    input("step 2: 回车开始录制轨迹")
    with open(CSV_path, "w") as f:
        for i in range(3):
            print(f"INFO: 等待时间: 0.1s，当前位置: {i}")
            f.write(f"0.1,{0.1 * i},0.2,-0.3,0,0.3,0,0.02\\n")
    print(f"INFO: 录制结束 {record_time} {timeout}")
'''

FAKE_PLAY = '''import os, time, csv
if __name__ == "__main__":
    have_gripper = True
    play_times = 1
    play_interval = 1.0
    move_spd_rate_ctrl = 100
    play_speed = 1.0
    timeout = 5.0
    CSV_path = os.path.join(os.path.dirname(__file__), "trajectory.csv")
    track = list(csv.reader(open(CSV_path)))
    print("step 1: 播放前请确保机械臂已退出示教模式")
    print("INFO: 使能成功")
    input("step 2: 回车开始播放轨迹")
    for n in range(play_times):
        for pos in track:
            print(f"INFO: 第{n + 1}次播放，速度{move_spd_rate_ctrl} 倍速{play_speed}")
'''


class FakeArm:
    snap = {}

    def snapshot(self):
        return dict(FakeArm.snap)

    def joints_deg(self):
        return list(FakeArm.snap["joints_deg"])

    def close(self):
        pass


@pytest.fixture()
def env(monkeypatch, tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / trajectory.RECORD_SCRIPT).write_text(FAKE_RECORD, encoding="utf-8")
    (scripts / trajectory.PLAY_SCRIPT).write_text(FAKE_PLAY, encoding="utf-8")
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(config, "MODE_FILE", tmp_path / "artifacts" / "run" / "mode")
    monkeypatch.setenv("ROBOT_MODE", "real")
    config.load.cache_clear()
    monkeypatch.setitem(config.load()["arm"], "trajectory_dir", str(scripts))
    monkeypatch.setattr(trajectory, "open_arm", FakeArm)
    FakeArm.snap = {"ctrl_mode": "standby", "arm_status": "normal", "errors": [],
                    "joints_deg": [0.0] * 6, "can_port": "can0", "can_fps": 200, "healthy": True,
                    "enabled": [True] * 6, "moving": False, "gripper_mm": 0, "motors": []}
    monkeypatch.setattr(trajectory, "print_snapshot", lambda s: None)
    yield tmp_path
    config.load.cache_clear()


def args(**kw):
    defaults = dict(name=None, seconds=15.0, teach_wait=30.0, start_delay=0.0, speed=None,
                    rate=1.0, times=1, settle_wait=60.0)
    return argparse.Namespace(**{**defaults, **kw})


def write_traj(name, rows):
    path = trajectory.traj_dir() / f"{name}.csv"
    path.write_text("".join(",".join(map(str, r)) + "\n" for r in rows))
    return path


@pytest.mark.parametrize("script, params", [
    (trajectory.RECORD_SCRIPT, ["record_time", "timeout", "CSV_path"]),
    (trajectory.PLAY_SCRIPT, ["play_times", "move_spd_rate_ctrl", "play_speed", "CSV_path"]),
])
def test_vendor_scripts_have_the_parameters_we_set(script, params):
    path = trajectory.Path(trajectory.os.path.expanduser(
        config.DEFAULTS["arm"]["trajectory_dir"])) / script
    if not path.exists():
        pytest.skip("AgiLex scripts not installed")
    src = trajectory.patched_source(path, {p: "1" for p in params})
    assert "__file__" not in src
    compile(src, script, "exec")


def test_record_runs_script_with_parameters(env, capsys):
    assert trajectory.record(args(name="wave", seconds=7)) == 0
    out = capsys.readouterr().out
    assert "录制结束 7.0 30.0" in out
    assert "等待时间" not in out  # per-point lines are summarised
    points = trajectory.load_points(trajectory.traj_dir() / "wave.csv")
    assert len(points) == 3
    assert "points: 3" in out and "teach button again" in out


def test_record_reports_teach_timeout(env, monkeypatch):
    real = trajectory.patched_source
    monkeypatch.setattr(trajectory, "patched_source",
                        lambda script, params: real(script, params).replace(
                            "record_time = 15.0", "record_time = -1"))
    with pytest.raises(ToolError, match="teach mode was not detected"):
        trajectory.record(args(name="late"))
    assert not (trajectory.traj_dir() / "late.csv").exists()


def test_record_rejects_bad_name_and_duration(env):
    with pytest.raises(ToolError, match="name"):
        trajectory.record(args(name="../x"))
    with pytest.raises(ToolError, match="--seconds"):
        trajectory.record(args(name="ok", seconds=600))


def test_play_caps_speed_and_counts_points(env, capsys):
    write_traj("wave", [[0.1, 0, 0.2, -0.3, 0, 0.3, 0, 0.02]] * 4)
    assert trajectory.play(args(name="wave", speed=90, times=2, rate=0.5)) == 0
    out = capsys.readouterr().out
    assert "points sent: 8" in out
    assert "joint speed 50%" in out


def test_play_refuses_teach_mode_faults_and_limits(env):
    write_traj("wave", [[0.1, 0, 0.2, -0.3, 0, 0.3, 0, 0.02]])
    FakeArm.snap["ctrl_mode"] = "teach"
    with pytest.raises(ToolError, match="teach mode"):
        trajectory.play(args(name="wave"))
    FakeArm.snap["ctrl_mode"] = "standby"
    FakeArm.snap["arm_status"] = "collision detected"
    with pytest.raises(ToolError, match="fault"):
        trajectory.play(args(name="wave"))
    FakeArm.snap["arm_status"] = "normal"
    write_traj("bad", [[0.1, math.radians(170), 0, 0, 0, 0, 0, 0]])
    with pytest.raises(ToolError, match="joint 1"):
        trajectory.play(args(name="bad"))
    with pytest.raises(ToolError, match="--rate"):
        trajectory.play(args(name="wave", rate=2.0))


def test_play_uses_mounted_joint_limits_and_arm_lock(env, monkeypatch):
    monkeypatch.setitem(config.load()["arm"], "joint_limits_deg",
                        [[-90, 90], [0, 120], [-120, 0], [-80, 80], [-65, 65], [-100, 100]])
    write_traj("wide", [[0.1, math.radians(100), 0, 0, 0, 0, 0, 0]])
    with pytest.raises(ToolError, match=r"joint 1 = 100.0 deg .*\[-90, 90\]"):
        trajectory.play(args(name="wide"))
    write_traj("wave", [[0.1, 0, 0.2, -0.3, 0, 0.3, 0, 0.02]])
    with trajectory.motion_lock("arm move-joints"):
        with pytest.raises(ToolError, match="busy"):
            trajectory.play(args(name="wave"))
    assert trajectory.play(args(name="wave")) == 0


def test_sim_record_and_play(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(config, "MODE_FILE", tmp_path / "run" / "mode")
    monkeypatch.setenv("ROBOT_MODE", "sim")
    config.load.cache_clear()
    try:
        assert trajectory.record(args(name="simwave", seconds=4)) == 0
        assert trajectory.play(args()) == 0
        assert trajectory.list_(args()) == 0
    finally:
        config.load.cache_clear()
    out = capsys.readouterr().out
    assert "[SIM] recorded" in out and "[SIM] trajectory played" in out and "simwave" in out


def test_sim_recordings_are_never_visible_to_the_real_arm(env, monkeypatch, capsys):
    write_traj("taught", [[0.1, 0, 0.2, -0.3, 0, 0.3, 0, 0.02]] * 3)
    monkeypatch.setenv("ROBOT_MODE", "sim")
    config.load.cache_clear()
    assert trajectory.record(args(name="simwave", seconds=2)) == 0
    assert (config.ARTIFACTS_DIR / "sim" / "trajectories" / "simwave.csv").exists()
    assert trajectory.resolve("taught").parent == trajectory.real_dir()
    assert trajectory.resolve(None).stem == "simwave"
    capsys.readouterr()
    trajectory.list_(args())
    out = capsys.readouterr().out
    assert "simwave" in out and "simulated" in out and "taught" in out

    monkeypatch.setenv("ROBOT_MODE", "real")
    config.load.cache_clear()
    with pytest.raises(ToolError, match="no trajectory named 'simwave'"):
        trajectory.play(args(name="simwave"))
    assert trajectory.resolve(None).stem == "taught"


@pytest.mark.parametrize("command, action, category", [
    ("./robot traj list", "allow", "read"),
    ("./robot traj show --name wave", "allow", "read"),
    ("./robot traj record --name wave --seconds 10", "ask", "motion"),
    ("./robot traj play --name wave --rate 0.5", "ask", "motion"),
])
def test_safety_classification(command, action, category):
    decision = safety.classify(command)
    assert (decision.action, decision.category) == (action, category)
