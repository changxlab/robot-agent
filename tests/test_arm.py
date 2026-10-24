import argparse
from types import SimpleNamespace

import pytest

from robot_tools import arm, config
from robot_tools.common import ToolError

LIMITS = [[-90, 90], [0, 120], [-120, 0], [-80, 80], [-65, 65], [-100, 100]]


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(config, "MODE_FILE", tmp_path / "artifacts" / "run" / "mode")
    monkeypatch.setenv("ROBOT_MODE", "real")
    config.load.cache_clear()
    monkeypatch.setitem(config.load()["arm"], "joint_limits_deg", LIMITS)
    monkeypatch.setitem(config.load()["arm"], "max_step_deg", 30)
    monkeypatch.setitem(config.load()["arm"], "home_deg", [0, 0, 0, 0, 0, 0])
    yield tmp_path
    config.load.cache_clear()


def snap(**kw):
    s = {"ctrl_mode": "CAN command", "arm_status": "normal", "errors": [], "moving": False,
         "joints_deg": [0.0] * 6, "can_port": "can0", "can_fps": 200, "healthy": True,
         "enabled": [True] * 6, "gripper_mm": 0, "motors": []}
    s.update(kw)
    return s


class FakeArm:
    state = {}

    def __init__(self):
        self.moves = []

    def snapshot(self):
        return dict(FakeArm.state)

    def joints_deg(self):
        return list(FakeArm.state["joints_deg"])

    def move_joints(self, deg, speed):
        FakeArm.state["joints_deg"] = list(deg)
        FakeArm.moved = list(deg)
        return list(deg)

    def take_control(self, speed, settle_timeout):
        FakeArm.state["ctrl_mode"] = "CAN command"
        FakeArm.state["arm_status"] = "normal"

    def gripper(self, mm, effort):
        FakeArm.state["gripper_mm"] = mm

    def close(self):
        pass


@pytest.fixture()
def fake(env, monkeypatch):
    FakeArm.state = snap()
    FakeArm.moved = None
    monkeypatch.setattr(arm, "open_arm", FakeArm)
    monkeypatch.setattr(arm, "print_snapshot", lambda s: None)
    return FakeArm


def args(action, **kw):
    defaults = dict(deg=None, speed=None, mm=None, effort=1.0, settle_wait=60.0)
    return argparse.Namespace(action=action, **{**defaults, **kw})


def test_joint_limits_come_from_config_and_only_narrow(env, monkeypatch):
    assert arm.joint_limits()[1] == (0, 120)
    monkeypatch.setitem(config.load()["arm"], "joint_limits_deg",
                        [[-200, 200], [-10, 190], [-170, 0], [-100, 100], [-70, 70], [-120, 120]])
    assert arm.joint_limits()[:2] == [(-150, 150), (0, 180)]
    monkeypatch.setitem(config.load()["arm"], "joint_limits_deg", [[0, 1]] * 5)
    with pytest.raises(ToolError, match="6"):
        arm.joint_limits()


def test_validate_uses_mounted_limits(env):
    arm.validate_joints([0, 120, -120, 0, 0, 0])
    with pytest.raises(ToolError, match="joint 2 = 150"):
        arm.validate_joints([0, 150, -10, 0, 0, 0])


def test_step_limit_suggests_intermediate_target(env):
    arm.check_step([0] * 6, [30, 0, 0, 0, -30, 0])
    with pytest.raises(ToolError, match=r"joint 1 would move 60.0 deg.*first to 30 0 0 0 0 0"):
        arm.check_step([0] * 6, [60, 0, 0, 0, 0, 0])


@pytest.mark.parametrize("state, message", [
    (dict(ctrl_mode="teach"), "teach mode"),
    (dict(ctrl_mode="standby"), "take-control"),
    (dict(arm_status="emergency stop"), "not ready"),
    (dict(errors=["joint 2 communication"]), "not ready"),
    (dict(moving=True), "still moving"),
])
def test_motion_requires_ready_arm(fake, state, message):
    FakeArm.state.update(state)
    for action in (args("move-joints", deg=[10, 0, 0, 0, 0, 0]), args("home"),
                   args("gripper", mm=20)):
        with pytest.raises(ToolError, match=message):
            arm.cmd(action)
    assert FakeArm.moved is None and FakeArm.state["gripper_mm"] == 0


def test_move_joints_checks_step_and_limits_before_moving(fake):
    FakeArm.state["joints_deg"] = [80.0, 0, 0, 0, 0, 0]
    with pytest.raises(ToolError, match="at most 30"):
        arm.cmd(args("home"))
    with pytest.raises(ToolError, match="outside the safe range"):
        arm.cmd(args("move-joints", deg=[95, 0, 0, 0, 0, 0]))
    assert FakeArm.moved is None
    assert arm.cmd(args("move-joints", deg=[60, 10, -10, 0, 0, 0], speed=90)) == 0
    assert FakeArm.moved == [60, 10, -10, 0, 0, 0]


def test_take_control_then_move(fake):
    FakeArm.state["ctrl_mode"] = "standby"
    assert arm.cmd(args("take-control")) == 0
    assert arm.cmd(args("move-joints", deg=[10, 0, 0, 0, 0, 0])) == 0


def test_take_control_refuses_teach_mode_and_faults(fake):
    FakeArm.state["ctrl_mode"] = "teach"
    with pytest.raises(ToolError, match="teach mode"):
        arm.cmd(args("take-control"))
    FakeArm.state.update(ctrl_mode="standby", arm_status="collision detected")
    with pytest.raises(ToolError, match="fault"):
        arm.cmd(args("take-control"))


def test_enable_refused_in_teach_mode(fake, monkeypatch):
    FakeArm.state["ctrl_mode"] = "teach"
    monkeypatch.setattr(FakeArm, "enable", lambda self: None, raising=False)
    with pytest.raises(ToolError, match="teach mode"):
        arm.cmd(args("enable"))


def test_only_one_arm_command_at_a_time(fake):
    with arm.motion_lock("traj play"):
        with pytest.raises(ToolError, match=r"busy \(traj play"):
            arm.cmd(args("move-joints", deg=[10, 0, 0, 0, 0, 0]))
    assert arm.cmd(args("move-joints", deg=[10, 0, 0, 0, 0, 0])) == 0


# ----- PiperArm against a fake piper_sdk -----

class FakePiper:
    def __init__(self, joints, ctrl_mode=0x00, arm_status=0x00, sink=None):
        self.joints = list(joints)
        self.ctrl_mode = ctrl_mode
        self.arm_status = arm_status
        self.sink = sink
        self.calls = []

    def GetArmJointMsgs(self):
        if self.sink and self.arm_status == 0x01:
            self.joints = [j + max(-1, min(1, t - j)) for j, t in zip(self.joints, self.sink)]
        js = SimpleNamespace(**{f"joint_{i + 1}": round(v * 1000) for i, v in
                                enumerate(self.joints)})
        return SimpleNamespace(joint_state=js)

    def GetArmStatus(self):
        return SimpleNamespace(arm_status=SimpleNamespace(ctrl_mode=self.ctrl_mode,
                                                          arm_status=self.arm_status))

    def EmergencyStop(self, code):
        self.calls.append(("estop", code))
        self.arm_status = 0x01 if code == 0x01 else 0x00

    def MotionCtrl_2(self, ctrl_mode, move_mode, speed, mit):
        self.calls.append(("mode", ctrl_mode))
        self.ctrl_mode = ctrl_mode

    def JointCtrl(self, *target):
        self.calls.append(("joints", target))

    def EnablePiper(self):
        self.calls.append(("enable",))
        return True


def piper_arm(fake_piper):
    a = object.__new__(arm.PiperArm)
    a.port, a.p = "can0", fake_piper
    return a


@pytest.fixture()
def fast(env, monkeypatch):
    monkeypatch.setattr(arm.time, "sleep", lambda s: None)


def test_take_control_waits_for_rest_pose_before_clearing_estop(fast):
    p = FakePiper([0, 40, -30, 0, 50, 0], ctrl_mode=0x00, sink=[0, 5, -5, 0, 30, 0])
    piper_arm(p).take_control(20, settle_timeout=5)
    kinds = [c[0] for c in p.calls]
    assert kinds.index("estop") < kinds.index("mode") < kinds.index("enable")
    assert [c for c in p.calls if c[0] == "estop"] == [("estop", 1), ("estop", 2)]
    assert arm._at_rest(p.joints) and p.ctrl_mode == 0x01


def test_take_control_leaves_arm_stopped_when_it_does_not_settle(fast):
    p = FakePiper([0, 40, -30, 0, 50, 0], ctrl_mode=0x00)
    with pytest.raises(ToolError, match="did not settle"):
        piper_arm(p).take_control(20, settle_timeout=0.05)
    assert p.calls == [("estop", 1)]


def test_take_control_skips_estop_in_can_mode(fast):
    p = FakePiper([0, 40, -30, 0, 50, 0], ctrl_mode=0x01)
    piper_arm(p).take_control(20, settle_timeout=5)
    assert ("estop", 1) not in p.calls and ("enable",) in p.calls


def test_move_timeout_holds_current_pose(fast):
    p = FakePiper([10, 20, -20, 0, 0, 0], ctrl_mode=0x01)
    with pytest.raises(ToolError, match="halted at 10.0, 20.0, -20.0"):
        piper_arm(p).move_joints([20, 20, -20, 0, 0, 0], 20, timeout=0.05)
    assert p.calls[-1] == ("joints", (10000, 20000, -20000, 0, 0, 0))


def test_resume_refused_away_from_rest(fast):
    p = FakePiper([0, 40, -30, 0, 50, 0], arm_status=0x01)
    with pytest.raises(ToolError, match="take-control"):
        piper_arm(p).resume()
    assert p.calls == []
    p.joints = [0, 2, -3, 0, 20, 0]
    piper_arm(p).resume()
    assert p.calls == [("estop", 2)]


def test_sim_flow(env, monkeypatch, capsys):
    monkeypatch.setenv("ROBOT_MODE", "sim")
    config.load.cache_clear()
    monkeypatch.setitem(config.load()["arm"], "joint_limits_deg", LIMITS)
    with pytest.raises(ToolError, match="take-control"):
        arm.cmd(args("move-joints", deg=[10, 0, 0, 0, 0, 0]))
    assert arm.cmd(args("take-control")) == 0
    assert arm.cmd(args("move-joints", deg=[10, 0, 0, 0, 0, 0])) == 0
    assert arm.cmd(args("home")) == 0
    assert "[SIM] arm: in CAN command mode" in capsys.readouterr().out
