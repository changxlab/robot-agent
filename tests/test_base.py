import argparse
import os
import signal
import threading
from contextlib import contextmanager

import pytest

from robot_agent import safety
from robot_tools import base, config, ros
from robot_tools.common import ToolError


class FakeRos:
    """Records published sport requests; ``on_step`` runs before each Move repetition."""

    def __init__(self, log, on_step=None):
        self.log = log
        self.on_step = on_step

    def publish(self, topic, msg, repeat=1, period=0.05, wait_subscribers=1.0, stop=None):
        for i in range(max(1, repeat)):
            if self.on_step:
                self.on_step(msg, i)
            if stop is not None and stop():
                break
            self.log.append(msg[0])
        return 1


@pytest.fixture()
def real(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(config, "MODE_FILE", tmp_path / "artifacts" / "run" / "mode")
    monkeypatch.setenv("ROBOT_MODE", "real")
    config.load.cache_clear()
    monkeypatch.setattr(base, "_request", lambda api_id, parameter="": (api_id, parameter))
    log: list[int] = []
    state = {"on_step": None, "signal_handlers": []}

    @contextmanager
    def session(name="x", signal_handlers=True):
        state["signal_handlers"].append(signal_handlers)
        yield FakeRos(log, state["on_step"])

    monkeypatch.setattr(ros, "session", session)
    yield log, state
    config.load.cache_clear()


MOVE = {"vx": 0.3, "vy": 0.0, "vyaw": 0.0, "duration": 2.0}


def test_move_streams_then_stops(real):
    log, state = real
    base.send("move", MOVE)
    assert log == [1008] * 20 + [1003] * 3
    assert state["signal_handlers"] == [False]


def test_stop_request_interrupts_a_running_move(real):
    log, state = real

    def estop_during_move(msg, i):
        if msg[0] == 1008 and i == 4:
            base.request_stop()  # what `./robot estop` / `base stop` do from another process

    state["on_step"] = estop_during_move
    with pytest.raises(ToolError, match="interrupted by a stop request"):
        base.send("move", MOVE)
    assert log == [1008] * 4 + [1003] * 3


def test_old_stop_request_does_not_block_a_new_move(real):
    log, _ = real
    base.request_stop()
    base.send("move", MOVE)
    assert log.count(1008) == 20


def test_sigterm_during_move_still_sends_stopmove(real):
    log, state = real

    def terminate(msg, i):
        if msg[0] == 1008 and i == 2:
            os.kill(os.getpid(), signal.SIGTERM)

    state["on_step"] = terminate
    previous = signal.getsignal(signal.SIGTERM)
    with pytest.raises(KeyboardInterrupt):
        base.send("move", MOVE)
    assert log == [1008] * 2 + [1003] * 3
    assert signal.getsignal(signal.SIGTERM) is previous


def test_base_stop_records_a_stop_request(real):
    log, _ = real
    base.send("stop")
    assert log == [1003] * 3
    assert base.stop_requested_since(0)


def test_recovery_stand_is_refused_unless_enabled(real, monkeypatch):
    log, _ = real
    with pytest.raises(ToolError, match="recovery-stand is disabled"):
        base.send("recovery-stand")
    assert log == []
    monkeypatch.setitem(config.load()["base"], "allow_recovery_stand", True)
    base.send("recovery-stand")
    assert log == [1006] * 3


def test_recovery_stand_refused_in_sim_too(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setenv("ROBOT_MODE", "sim")
    config.load.cache_clear()
    try:
        with pytest.raises(ToolError, match="disabled"):
            base.cmd(argparse.Namespace(action="recovery-stand"))
    finally:
        config.load.cache_clear()


def test_recovery_stand_is_blocked_for_the_agent(monkeypatch):
    decision = safety.classify("./robot base recovery-stand")
    assert (decision.action, decision.category) == (safety.DENY, "blocked")
    assert "manual recovery" in decision.reason
    monkeypatch.setattr(safety, "_recovery_stand_allowed", lambda: True)
    assert safety.classify("./robot base recovery-stand").action == safety.ASK


def test_stop_commands_stay_unapproved():
    for command in ("./robot base stop", "./robot estop"):
        assert safety.classify(command).action == safety.ALLOW


def test_stop_file_is_shared_with_concurrent_writer(real):
    # A stop written by another thread (standing in for another process) is seen by the loop.
    log, state = real
    started = threading.Event()

    def wait_for_stop(msg, i):
        if msg[0] == 1008 and i == 1:
            started.set()
            t = threading.Thread(target=base.request_stop)
            t.start()
            t.join()

    state["on_step"] = wait_for_stop
    with pytest.raises(ToolError):
        base.send("move", MOVE)
    assert started.is_set() and log.count(1008) == 1
