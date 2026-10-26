import argparse
import threading
import time

import pytest

from robot_agent import safety
from robot_tools import base, camera, config, survey, trajectory
from robot_tools.common import ToolError


@pytest.fixture()
def sim(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(config, "MODE_FILE", tmp_path / "artifacts" / "run" / "mode")
    monkeypatch.setenv("ROBOT_MODE", "sim")
    config.load.cache_clear()
    monkeypatch.setitem(config.load()["cameras"], "orbbec_gemini", {"source": ""})
    monkeypatch.setattr(camera, "v4l2_devices", lambda: [{
        "path": "/dev/v4l/by-id/usb-Orbbec_Gemini-video-index0", "node": "/dev/video6",
        "name": "Orbbec Gemini", "vendor": "Orbbec", "formats": "MJPG,YUYV", "kind": "colour"}])
    base.SimBase().command("stand-up")
    yield tmp_path
    config.load.cache_clear()


def args(**kw):
    defaults = dict(name=None, camera=None, seconds=None, fps=None, photos=None, speed=None,
                    rate=1.0, settle_wait=60.0, timeout=5.0)
    return argparse.Namespace(**{**defaults, **kw})


def teach(seconds=20):
    trajectory.record(argparse.Namespace(name="survey", seconds=seconds, teach_wait=30.0,
                                         start_delay=0.0))


def test_check_lists_what_is_missing_and_the_devices(sim, capsys):
    survey.check(args())
    out = capsys.readouterr().out
    assert "survey motion: MISSING" in out
    assert "./robot traj record --name survey --seconds 20" in out
    assert "camera orbbec_gemini: NOT SET UP" in out
    assert "v4l2:/dev/v4l/by-id/usb-Orbbec_Gemini-video-index0" in out
    assert "ready: no - fix: survey motion, camera" in out


def test_set_source_is_tested_saved_and_cleared(sim, capsys):
    with pytest.raises(ToolError, match="unknown camera"):
        camera.set_source("nope", "ros:/x", 1)
    with pytest.raises(ToolError, match="invalid source"):
        camera.set_source("orbbec_gemini", "/dev/video6", 1)
    with pytest.raises(ToolError, match="/dev/"):
        camera.set_source("orbbec_gemini", "v4l2:video6", 1)
    camera.set_source("orbbec_gemini", "ros:/camera/color/image_raw", 1)
    assert config.cameras()["orbbec_gemini"] == "ros:/camera/color/image_raw"
    assert "IMAGE:" in capsys.readouterr().out
    camera.cmd(argparse.Namespace(action="set-source", camera="orbbec_gemini", clear=True,
                                  source=None, timeout=1))
    assert config.cameras()["orbbec_gemini"] == ""


def test_check_is_ready_after_teaching_and_choosing_the_camera(sim, capsys):
    teach()
    config.set_camera_source("orbbec_gemini", "ros:/camera/color/image_raw")
    capsys.readouterr()
    survey.check(args())
    out = capsys.readouterr().out
    assert "survey motion: OK - survey: 100 points, 20.0 s (simulated recording)" in out
    assert "ready: yes" in out


def test_short_motion_is_only_a_warning(sim, capsys):
    teach(seconds=8)
    config.set_camera_source("orbbec_gemini", "ros:/camera/color/image_raw")
    survey.check(args())
    out = capsys.readouterr().out
    assert "outside the usual 15-30 s" in out and "ready: yes" in out


def test_run_refuses_before_moving_without_motion_or_camera(sim, monkeypatch):
    played = []
    monkeypatch.setattr(trajectory, "play", lambda *a, **k: played.append(1))
    with pytest.raises(ToolError, match="no trajectory named 'survey'"):
        survey.run(args())
    teach()
    with pytest.raises(ToolError, match="not set up"):
        survey.run(args())
    assert played == []


def test_run_starts_the_video_with_the_replay(sim, monkeypatch, capsys):
    teach()
    config.set_camera_source("orbbec_gemini", "ros:/camera/color/image_raw")
    times = {}

    def fake_play(play_args, on_start=None):
        assert play_args.name == "survey" and play_args.times == 1
        time.sleep(0.3)  # the arm settling before the replay
        times["replay"] = time.monotonic()
        on_start()
        time.sleep(0.2)
        return 0

    real_record = camera.record

    def spy_record(*a, start_event=None, **kw):
        assert not start_event.is_set()  # camera ready before the replay starts
        start_event.wait()
        times["video"] = time.monotonic()
        assert kw["label"] == "survey_orbbec_gemini"
        return real_record(*a, start_event=start_event, **kw)

    monkeypatch.setattr(trajectory, "play", fake_play)
    monkeypatch.setattr(camera, "record", spy_record)
    assert survey.run(args()) == 0
    assert abs(times["video"] - times["replay"]) < 0.1
    out = capsys.readouterr().out
    assert "200 frames at 10 fps (20.0 s)" in out
    assert "VIDEO: " in out and "_survey_orbbec_gemini.mp4" in out
    assert "plant survey complete" in out


def test_failed_replay_stops_the_recording(sim, monkeypatch):
    teach()
    config.set_camera_source("orbbec_gemini", "ros:/camera/color/image_raw")
    stopped = threading.Event()

    def spy_record(*a, start_event=None, stop_event=None, **kw):
        start_event.wait(5)
        stopped.set() if stop_event.is_set() else None
        raise ToolError("recording was stopped before any frame was captured")

    def failing_play(play_args, on_start=None):
        raise ToolError("the arm reports a fault")

    monkeypatch.setattr(camera, "record", spy_record)
    monkeypatch.setattr(trajectory, "play", failing_play)
    with pytest.raises(ToolError, match="the arm reports a fault"):
        survey.run(args())
    assert stopped.is_set()


@pytest.mark.parametrize("command, action, category", [
    ("./robot survey check", "allow", "read"),
    ("./robot survey run", "ask", "motion"),
    ("./robot survey run --name survey --rate 0.5", "ask", "motion"),
    ("./robot camera devices", "allow", "read"),
    ("./robot camera set-source --camera orbbec_gemini --source v4l2:/dev/video6", "ask",
     "system"),
])
def test_safety_classification(command, action, category):
    decision = safety.classify(command)
    assert (decision.action, decision.category) == (action, category)
