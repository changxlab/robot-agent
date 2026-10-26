import argparse
import importlib.util
import inspect
import math
import time
import sys
import threading
import types
from pathlib import Path

import pytest

from robot_agent import safety
from robot_tools import base, config, piper_gradio, piper_play, piper_record, trajectory
from robot_tools.__main__ import build_parser
from robot_tools.common import ToolError

AGILEX_DIR = Path(config.DEFAULTS["arm"]["trajectory_dir"]).expanduser()


class FakePiper:
    """Stand-in for piper_sdk.C_PiperInterface_V2, shared state across instances."""
    ctrl_mode = 1
    arm_status = 0
    joint_cmds: list = []
    port = None

    def __init__(self, port):
        FakePiper.port = port
        self.reads = 0

    def ConnectPort(self):
        pass

    def DisconnectPort(self):
        pass

    def GetCanFps(self):
        return 200.0

    def GetArmStatus(self):
        st = types.SimpleNamespace(ctrl_mode=FakePiper.ctrl_mode, arm_status=FakePiper.arm_status)
        return types.SimpleNamespace(arm_status=st)

    def GetArmJointMsgs(self):
        self.reads += 1
        js = types.SimpleNamespace(joint_1=self.reads * 10, joint_2=0, joint_3=0, joint_4=0,
                                   joint_5=20000, joint_6=0)
        return types.SimpleNamespace(joint_state=js)

    def GetArmGripperMsgs(self):
        return types.SimpleNamespace(gripper_state=types.SimpleNamespace(grippers_angle=10000))

    def EmergencyStop(self, code):
        FakePiper.arm_status = 1 if code == 0x01 else 0

    def ModeCtrl(self, *a):
        FakePiper.ctrl_mode = 1

    MotionCtrl_2 = ModeCtrl

    def EnablePiper(self):
        return True

    def JointCtrl(self, *joints):
        FakePiper.joint_cmds.append(joints)

    def GripperCtrl(self, *a):
        pass


STANDING = {"reachable": True, "mode": "balance stand", "mode_id": 1, "body_height_m": 0.55,
            "velocity_mps": [0.0, 0.0, 0.0], "yaw_speed": 0.0}


class FakeArm:
    snap = {}

    def snapshot(self):
        return dict(FakeArm.snap)

    def joints_deg(self):
        return list(FakeArm.snap["joints_deg"])

    def move_joints(self, deg, speed):
        FakeArm.snap["joints_deg"] = deg

    def close(self):
        pass


@pytest.fixture()
def env(monkeypatch, tmp_path):
    sdk = types.ModuleType("piper_sdk")
    sdk.C_PiperInterface_V2 = FakePiper
    monkeypatch.setitem(sys.modules, "piper_sdk", sdk)
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(config, "MODE_FILE", tmp_path / "artifacts" / "run" / "mode")
    monkeypatch.setenv("ROBOT_MODE", "real")
    config.load.cache_clear()
    monkeypatch.setitem(config.load()["arm"], "can_port", "lo")  # an interface that exists
    monkeypatch.setattr(piper_gradio, "open_arm", FakeArm)
    monkeypatch.setattr(piper_gradio, "print_snapshot", lambda s: None)
    monkeypatch.setattr(base, "read_state", lambda: dict(STANDING))
    FakePiper.ctrl_mode, FakePiper.arm_status, FakePiper.joint_cmds = 1, 0, []
    FakeArm.snap = {"ctrl_mode": "CAN command", "arm_status": "normal", "errors": [],
                    "joints_deg": [0.0] * 6, "can_port": "lo", "can_fps": 200, "healthy": True,
                    "enabled": [True] * 6, "moving": False, "gripper_mm": 0, "motors": []}
    yield tmp_path
    config.load.cache_clear()


def args(**kw):
    defaults = dict(name=None, no_gripper=False, seconds=1.0, teach_wait=5.0, start_delay=0.0,
                    poll=0.02, stop_when_still=0.0, speed=None, rate=1.0, times=1, interval=0.0,
                    settle_wait=60.0)
    return argparse.Namespace(**{**defaults, **kw})


def write_traj(name, rows):
    path = trajectory.traj_dir() / f"{name}.csv"
    path.write_text("".join(",".join(map(str, r)) + "\n" for r in rows))
    return path


class ScriptedPiper:
    """Fake arm for comparing with the AgiLex originals: scripted joint readings (0.001 deg)
    and a log of every command sent."""

    def __init__(self, poses, ctrl_mode=1):
        self.poses = poses
        self.reads = 0
        self.ctrl_mode = ctrl_mode
        self.calls = []

    def _pose(self):
        return self.poses[min(self.reads, len(self.poses) - 1)]

    def GetArmJointMsgs(self):
        pose = self._pose()
        self.reads += 1
        return types.SimpleNamespace(joint_state=types.SimpleNamespace(
            **{f"joint_{i + 1}": v for i, v in enumerate(pose)}))

    def GetArmGripperMsgs(self):
        return types.SimpleNamespace(gripper_state=types.SimpleNamespace(
            grippers_angle=1000 * min(self.reads, len(self.poses))))

    def GetArmStatus(self):
        return types.SimpleNamespace(arm_status=types.SimpleNamespace(ctrl_mode=self.ctrl_mode))

    def EmergencyStop(self, code):
        self.calls.append(("EmergencyStop", code))

    def ModeCtrl(self, *a):
        self.calls.append(("ModeCtrl", a))
        self.ctrl_mode = 1

    def MotionCtrl_2(self, *a):
        self.calls.append(("MotionCtrl_2", a))

    def EnablePiper(self):
        self.calls.append(("EnablePiper",))
        return True

    def JointCtrl(self, *a):
        self.calls.append(("JointCtrl", a))

    def GripperCtrl(self, *a):
        self.calls.append(("GripperCtrl", a))


def load_original(name, monkeypatch):
    """AgiLex's Gradio app ``name`` as a module, with gradio unavailable and a fake piper_sdk."""
    path = AGILEX_DIR / name
    if not path.exists():
        pytest.skip(f"AgiLex {name} not installed")
    sdk = types.ModuleType("piper_sdk")
    sdk.C_PiperInterface_V2 = ScriptedPiper
    monkeypatch.setitem(sys.modules, "piper_sdk", sdk)
    monkeypatch.setitem(sys.modules, "gradio", None)
    spec = importlib.util.spec_from_file_location(f"agilex_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MOVING = [(i * 1500, 2000 * i, -1000 * i, 0, 20000 + 500 * i, -i) for i in range(8)]
REST_AFTER_SETTLE = [(0, 30000, -30000, 0, 20000, 0)] * 3 + [(0, 1000, -1000, 0, 20000, 0)]


@pytest.mark.parametrize("have_gripper", [True, False])
def test_recorder_writes_the_same_rows_as_record_py(monkeypatch, tmp_path, have_gripper):
    original = load_original("record.py", monkeypatch)
    original._sessions_dir = tmp_path / "theirs"
    theirs = ScriptedPiper(MOVING)
    original._piper = theirs
    original._start_record(str(tmp_path / "theirs.csv"), have_gripper, 0.3, 0.005)
    original._record_thread.join()

    ours = ScriptedPiper(MOVING)
    recorder = piper_record.Recorder(ours, tmp_path / "ours", log=lambda status, message: None)
    recorder.start(str(tmp_path / "ours.csv"), have_gripper, 0.3, 0.005)
    recorder.thread.join()

    def rows(name):
        return [line.split(",")[1:] for line in (tmp_path / name).read_text().splitlines()]

    assert rows("ours.csv") == rows("theirs.csv")
    assert len(rows("ours.csv")) == len(MOVING) - 1
    assert len(rows("ours.csv")[0]) == (7 if have_gripper else 6)
    assert recorder.points == original._record_points
    assert [p.name.replace("ours", "theirs") for p in (tmp_path / "ours").iterdir()] == \
        [p.name for p in (tmp_path / "theirs").iterdir()]


@pytest.mark.parametrize("ctrl_mode, poses", [(1, MOVING), (0, REST_AFTER_SETTLE)])
@pytest.mark.parametrize("have_gripper", [True, False])
def test_player_sends_the_same_commands_as_play_py(monkeypatch, tmp_path, ctrl_mode, poses,
                                                   have_gripper):
    original = load_original("play.py", monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    csv_path = tmp_path / "t.csv"
    csv_path.write_text("0.01,0.1,0.2,-0.3,0,0.3,-0.05,0.02\n0.02,0.15,0.25,-0.2,0.01,0.35,0,0.03\n"
                        "0.01,0.2,0.3,-0.1,0.02,0.4,0.05\n")

    theirs = ScriptedPiper(poses, ctrl_mode)
    original._piper = theirs
    assert original._load_track(str(csv_path))
    assert original._init_arm(1.0, 30, have_gripper)
    original._play_trajectory(2, 0.0, 30, 0.5, have_gripper)

    ours = ScriptedPiper(poses, ctrl_mode)
    player = piper_play.Player(ours, log=lambda status, message: None)
    assert player.load_track(str(csv_path))
    assert player.init_arm(1.0, 30, have_gripper)
    player.play(2, 0.0, 30, 0.5, have_gripper)

    assert ours.calls == theirs.calls
    assert sum(c[0] == "JointCtrl" for c in ours.calls) == 6
    assert (("EmergencyStop", 0x01) in ours.calls) == (ctrl_mode != 1)


def test_copied_modules_have_no_gradio_ui():
    for module in (piper_record, piper_play):
        src = inspect.getsource(module)
        assert "import gradio" not in src and "gr." not in src and ".launch(" not in src


def test_record_uses_the_gradio_recorder(env, capsys):
    FakePiper.ctrl_mode = 2
    assert piper_gradio.record(args(name="wave")) == 0
    out = capsys.readouterr().out
    assert FakePiper.port == "lo"
    assert "Teaching mode active" in out
    assert "Point 1 wait" not in out  # per-point lines are counted, not printed
    points = trajectory.load_points(trajectory.real_dir() / "wave.csv")
    assert len(points) > 5 and len(points[0]) == 8
    assert "teach button again" in out
    assert list((trajectory.real_dir() / "sessions").glob("wave_*.csv"))
    assert [p.stem for p in trajectory.all_files()] == ["wave"]


def test_record_without_gripper_and_existing_name(env):
    FakePiper.ctrl_mode = 2
    assert piper_gradio.record(args(name="nogrip", no_gripper=True)) == 0
    assert len(trajectory.load_points(trajectory.real_dir() / "nogrip.csv")[0]) == 7
    with pytest.raises(ToolError, match="already exists"):
        piper_gradio.record(args(name="nogrip"))


def test_play_replays_with_the_gradio_player(env, capsys):
    write_traj("wave", [[0.01, 0, 0.2, -0.3, 0, 0.3, 0, 0.02]] * 4)
    assert piper_gradio.play(args(name="wave", speed=90, times=2)) == 0
    out = capsys.readouterr().out
    assert len(FakePiper.joint_cmds) == 8
    assert "points sent: 8" in out and "joint speed 50%" in out
    assert "Replay completed" in out


def test_play_settles_the_arm_outside_can_mode(env, capsys):
    FakePiper.ctrl_mode = 0
    FakeArm.snap["ctrl_mode"] = "standby"
    write_traj("wave", [[0.01, 0, 0.2, -0.3, 0, 0.3, 0, 0.02]] * 2)
    assert piper_gradio.play(args(name="wave")) == 0
    out = capsys.readouterr().out
    assert "emergency stop cycle complete" in out and "points sent: 2" in out


def test_play_stops_on_emergency_stop(env):
    write_traj("slow", [[0.5, 0, 0.2, -0.3, 0, 0.3, 0, 0.02]] * 10)
    threading.Timer(0.3, lambda: setattr(FakePiper, "arm_status", 1)).start()
    with pytest.raises(ToolError, match="emergency-stopped during the replay"):
        piper_gradio.play(args(name="slow"))
    assert len(FakePiper.joint_cmds) < 10


def test_play_refuses_bad_state_limits_and_options(env):
    write_traj("wave", [[0.1, 0, 0.2, -0.3, 0, 0.3, 0, 0.02]])
    FakeArm.snap["ctrl_mode"] = "teach"
    with pytest.raises(ToolError, match="teach mode"):
        piper_gradio.play(args(name="wave"))
    FakeArm.snap["ctrl_mode"] = "CAN command"
    FakeArm.snap["arm_status"] = "emergency stop"
    with pytest.raises(ToolError, match="take-control"):
        piper_gradio.play(args(name="wave"))
    FakeArm.snap["arm_status"] = "collision detected"
    with pytest.raises(ToolError, match="fault"):
        piper_gradio.play(args(name="wave"))
    FakeArm.snap["arm_status"] = "normal"
    write_traj("bad", [[0.1, math.radians(170), 0, 0, 0, 0, 0, 0]])
    with pytest.raises(ToolError, match="joint 1"):
        piper_gradio.play(args(name="bad"))
    for bad in (dict(rate=2.0), dict(times=0), dict(times=6), dict(interval=9)):
        with pytest.raises(ToolError, match="must be between"):
            piper_gradio.play(args(name="wave", **bad))


def test_record_rejects_bad_options(env):
    with pytest.raises(ToolError, match="name"):
        piper_gradio.record(args(name="../x"))
    with pytest.raises(ToolError, match="--seconds"):
        piper_gradio.record(args(name="ok", seconds=600))
    with pytest.raises(ToolError, match="--poll"):
        piper_gradio.record(args(name="ok", poll=1.0))


@pytest.mark.parametrize("state, error", [
    ({"mode": "lie down", "mode_id": 5}, r"not standing \(lie down\)"),
    ({"mode": "damping", "mode_id": 7}, r"not standing \(damping\)"),
    ({"mode": "locomotion", "mode_id": 3, "velocity_mps": [0.3, 0.0, 0.0]}, "B2 is moving"),
    ({"mode": "balance stand", "mode_id": 1, "yaw_speed": 0.4}, "B2 is moving"),
])
def test_arm_work_needs_the_b2_standing_still(env, monkeypatch, state, error):
    monkeypatch.setattr(base, "read_state", lambda: {**STANDING, **state})
    write_traj("wave", [[0.1, 0, 0.2, -0.3, 0, 0.3, 0, 0.02]])
    for action in (piper_gradio.record, piper_gradio.play):
        with pytest.raises(ToolError, match=error):
            action(args(name="wave" if action is piper_gradio.play else "new"))
    assert FakePiper.joint_cmds == []


def test_unreachable_b2_blocks_arm_work_unless_disabled(env, monkeypatch, capsys):
    def unreachable():
        raise piper_gradio.Unavailable("no data on /sportmodestate")

    monkeypatch.setattr(base, "read_state", unreachable)
    write_traj("wave", [[0.01, 0, 0.2, -0.3, 0, 0.3, 0, 0.02]])
    with pytest.raises(ToolError, match="needs the B2 standing still"):
        piper_gradio.play(args(name="wave"))
    monkeypatch.setitem(config.load()["base"], "require_standing_for_arm", False)
    assert piper_gradio.play(args(name="wave")) == 0
    assert "standing check is off" in capsys.readouterr().out


def test_shares_the_arm_lock(env):
    write_traj("wave", [[0.1, 0, 0.2, -0.3, 0, 0.3, 0, 0.02]])
    with trajectory.motion_lock("traj play"):
        with pytest.raises(ToolError, match="busy"):
            piper_gradio.play(args(name="wave"))


def test_missing_piper_sdk_is_reported(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "piper_sdk", None)
    write_traj("wave", [[0.1, 0, 0.2, -0.3, 0, 0.3, 0, 0.02]])
    with pytest.raises(ToolError, match="piper_sdk is not installed"):
        piper_gradio.play(args(name="wave"))


def test_sim_record_follows_the_teach_flow(monkeypatch, tmp_path, capsys):
    from robot_tools import arm

    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(config, "MODE_FILE", tmp_path / "run" / "mode")
    monkeypatch.setenv("ROBOT_MODE", "sim")
    config.load.cache_clear()

    def teach_button():
        sim_arm = arm.SimArm()
        sim_arm.teach_button()
        sim_arm.close()

    try:
        with pytest.raises(ToolError, match=r"B2 is not standing \(lie down\)"):
            piper_gradio.record(args(name="pick", seconds=20, stop_when_still=3.0))
        base.SimBase().command("stand-up")
        with pytest.raises(ToolError, match="teach mode was not detected"):
            piper_gradio.record(args(name="pick", seconds=20, stop_when_still=3.0))
        teach_button()
        assert piper_gradio.record(args(name="pick", seconds=20, stop_when_still=3.0)) == 0
        with pytest.raises(ToolError, match="still in teach mode"):
            piper_gradio.play(args(name="pick"))
        teach_button()
        assert piper_gradio.play(args(name="pick")) == 0
        assert piper_gradio.ACTIONS["list"](args()) == 0
    finally:
        config.load.cache_clear()
    out = capsys.readouterr().out
    assert "recording ended: the arm was back and still for 3s (after 16.0s of at most 20s)" in out
    assert "`./robot arm teach-button`" in out and "./robot piper play --name pick" in out
    assert "[SIM] trajectory played" in out
    points = trajectory.load_points(tmp_path / "sim" / "trajectories" / "pick.csv")
    s = trajectory.summary(points)
    assert all(abs(a - b) < 0.01 for a, b in zip(s["start_deg"], s["end_deg"]))  # out and back
    assert s["range_deg"][0][1] > 20
    assert round(s["duration_s"]) == 13  # 1 s idle + 12 s motion; the still end is not stored


def test_sim_teach_button(monkeypatch, tmp_path, capsys):
    from robot_tools import arm

    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(config, "MODE_FILE", tmp_path / "run" / "mode")
    monkeypatch.setenv("ROBOT_MODE", "sim")
    config.load.cache_clear()
    try:
        cmd = argparse.Namespace(action="teach-button")
        arm._dispatch(cmd)
        snap = arm.SimArm().snapshot()
        assert snap["ctrl_mode"] == "teach" and not any(snap["enabled"])
        with pytest.raises(ToolError, match="teach mode"):
            arm.SimArm().enable()
        arm._dispatch(cmd)
        assert arm.SimArm().snapshot()["ctrl_mode"] == "standby"
        monkeypatch.setenv("ROBOT_MODE", "real")
        config.load.cache_clear()
        with pytest.raises(ToolError, match="physical button"):
            arm._dispatch(cmd)
    finally:
        config.load.cache_clear()
    out = capsys.readouterr().out
    assert "teach mode ON" in out and "teach mode OFF" in out


def test_real_recording_stops_once_the_arm_is_back_and_still(env, monkeypatch, capsys):
    """The operator guides the arm out for 0.6 s and back, then holds it still."""
    t0 = time.monotonic()

    def joints(self):
        t = time.monotonic() - t0
        out = 10_000 * min(t, 1.2 - t) if t < 1.2 else 0  # 0 -> 6 deg -> 0
        return types.SimpleNamespace(joint_state=types.SimpleNamespace(
            joint_1=int(out), joint_2=0, joint_3=0, joint_4=0, joint_5=20000, joint_6=0))

    monkeypatch.setattr(FakePiper, "GetArmJointMsgs", joints)
    FakePiper.ctrl_mode = 2
    assert piper_gradio.record(args(name="back", seconds=20, stop_when_still=1.0)) == 0
    elapsed = time.monotonic() - t0
    out = capsys.readouterr().out
    assert "recording ended: the arm was back and still for 1s" in out
    assert 2.0 < elapsed < 4.0  # 1.2 s motion + 1 s still, not the 20 s maximum
    s = trajectory.summary(trajectory.load_points(trajectory.real_dir() / "back.csv"))
    assert 5.5 < s["range_deg"][0][1] <= 6.0 and abs(s["end_deg"][0]) < 0.5


def test_still_watch_ignores_an_arm_that_never_moved():
    watch = piper_gradio.StillWatch([0.0] * 6, 1.0, now=0.0)
    assert not watch.update([0.3] + [0.0] * 5, now=5.0)  # jitter below MOVED_DEG
    assert not watch.update([10.0] + [0.0] * 5, now=5.5)  # moving
    assert not watch.update([10.2] + [0.0] * 5, now=6.0)
    assert watch.update([10.1] + [0.0] * 5, now=6.6)  # still for 1.1 s after moving


def test_cli_and_safety_classification():
    ns = build_parser().parse_args(["piper", "play", "--name", "wave", "--interval", "0.5"])
    assert (ns.tool, ns.action, ns.interval) == ("piper", "play", 0.5)
    assert safety.classify("./robot piper list").action == safety.ALLOW
    assert safety.classify("./robot arm teach-button").action == safety.ALLOW
    assert safety.classify("./robot piper show --name wave").action == safety.ALLOW
    for cmd in ("./robot piper record --name x", "./robot piper play --times 2"):
        d = safety.classify(cmd)
        assert d.action == safety.ASK and d.category == "motion"
