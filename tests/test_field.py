"""Field checks: B2 posture, status alerts, weather, and the plant survey photos."""

import argparse
import io
import json

import pytest

from robot_agent import safety
from robot_tools import base, camera, config, status, survey, trajectory, weather
from robot_tools.common import ToolError, Unavailable

STANDING = {"mode": "balance stand", "mode_id": 1, "body_height_m": 0.55,
            "velocity_mps": [0.0, 0.0, 0.0], "yaw_speed": 0.0}


@pytest.fixture()
def sim(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(config, "MODE_FILE", tmp_path / "artifacts" / "run" / "mode")
    monkeypatch.setenv("ROBOT_MODE", "sim")
    config.load.cache_clear()
    yield tmp_path
    config.load.cache_clear()


# ----- B2 posture -----

@pytest.mark.parametrize("state, expected", [
    (STANDING, "standing still"),
    ({**STANDING, "mode": "idle", "mode_id": 0}, "standing still"),
    ({**STANDING, "mode": "lie down", "mode_id": 5}, "lie down"),
    ({**STANDING, "mode": "damping", "mode_id": 7}, "damping"),
    ({**STANDING, "mode": "sit", "mode_id": 10}, "sit"),
    ({**STANDING, "velocity_mps": [0.0, 0.2, 0.0]}, "moving"),
    ({**STANDING, "yaw_speed": -0.3}, "moving"),
    ({"battery_pct": 80}, "unknown (no sport mode state)"),
])
def test_posture(sim, state, expected):
    assert base.posture(state) == expected


def test_optional_body_height_check(sim, monkeypatch):
    monkeypatch.setitem(config.load()["base"], "stand_min_height_m", 0.4)
    assert base.posture({**STANDING, "body_height_m": 0.2}).startswith("body low")
    assert base.posture(STANDING) == "standing still"


def test_sim_base_posture_follows_stand_up_and_down(sim, capsys):
    assert base.posture(base.read_state()) == "lie down"
    with pytest.raises(ToolError, match="not standing"):
        base.require_standing_still("arm replay")
    base.SimBase().command("stand-up")
    base.require_standing_still("arm replay")
    assert "[SIM] B2: standing still (balance stand) - OK for arm replay" in capsys.readouterr().out
    base.print_state(base.read_state())
    assert "posture: standing still" in capsys.readouterr().out


# ----- status alerts -----

def report(base_state=None, motors=None):
    arm_motors = motors or [{"joint": i, "motor_temp_c": 35, "driver_temp_c": 38}
                            for i in range(1, 7)]
    return {
        "base": {"reachable": True, "error_code": 0, "battery_pct": 80,
                 "motor_temps_c": [40] * 12, "max_motor_temp_c": 40, "hot_motors": [],
                 "lost_motors": [], **(base_state or {})},
        "arm": {"available": True, "healthy": True, "arm_status": "normal", "errors": [],
                "motors": arm_motors},
        "cameras": {}, "system": {"disk_used_pct": 10},
    }


def test_status_ok_below_the_alert_thresholds(sim):
    assert status.summarize(report({"battery_pct": 20, "motor_temps_c": [60] * 12})) == {
        "ok": True, "issues": []}


def test_status_alerts_on_low_battery_and_warm_motors(sim):
    temps = [45] * 12
    temps[3] = 63
    motors = [{"joint": 1, "motor_temp_c": 40, "driver_temp_c": 61},
              {"joint": 2, "motor_temp_c": 30, "driver_temp_c": 30}]
    s = status.summarize(report({"battery_pct": 19, "motor_temps_c": temps,
                                 "max_motor_temp_c": 63}, motors))
    assert not s["ok"]
    assert "B2 battery low (19% < 20%)" in s["issues"]
    assert any(i.startswith("B2 motors [3] above 60 C (max 63 C") for i in s["issues"])
    assert "arm motors/drivers above 60 C: j1 61 C" in s["issues"]


def test_status_alert_thresholds_come_from_robot_yaml(sim, monkeypatch):
    monkeypatch.setitem(config.load()["status"], "alert_battery_pct", 30)
    assert "B2 battery low (25% < 30%)" in status.summarize(report({"battery_pct": 25}))["issues"]


# ----- weather -----

OPEN_METEO = {
    "current": {"temperature_2m": 21.4, "apparent_temperature": 22.0, "weather_code": 2,
                "relative_humidity_2m": 78, "wind_speed_10m": 9.5, "wind_direction_10m": 95,
                "precipitation": 0.0},
    "daily": {"time": ["2026-10-27", "2026-10-28"], "weather_code": [61, 3],
              "temperature_2m_min": [15.1, 14.0], "temperature_2m_max": [23.2, 22.5],
              "precipitation_sum": [3.4, 0.0], "precipitation_probability_max": [70, 10],
              "uv_index_max": [4.1, 5.0], "sunrise": ["2026-10-27T06:10", "2026-10-28T06:11"],
              "sunset": ["2026-10-27T17:14", "2026-10-28T17:13"]},
}


def test_weather_for_the_configured_site(sim, monkeypatch, capsys):
    urls = []

    def fake_urlopen(url, timeout):
        urls.append(url)
        return io.BytesIO(json.dumps(OPEN_METEO).encode())

    monkeypatch.setattr(weather.urllib.request, "urlopen", fake_urlopen)
    assert weather.cmd(argparse.Namespace(days=2)) == 0
    out = capsys.readouterr().out
    assert "latitude=31.49" in urls[0] and "longitude=120.31" in urls[0]
    assert "timezone=Asia%2FShanghai" in urls[0] and "forecast_days=2" in urls[0]
    assert "## Weather - Wuxi, Jiangsu, China" in out and "[SIM]" not in out
    assert "now: 21.4 C (feels 22.0 C), partly cloudy, humidity 78%, wind 9.5 km/h E" in out
    assert "today: 2026-10-27: light rain, 15.1..23.2 C, rain 3.4 mm (70% chance)" in out
    assert "sunrise 06:10, sunset 17:14" in out
    assert "tomorrow: 2026-10-28: overcast" in out
    assert "TCM" in out


def test_weather_without_internet_is_reported(sim, monkeypatch):
    def offline(url, timeout):
        raise weather.urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(weather.urllib.request, "urlopen", offline)
    with pytest.raises(Unavailable, match="needs internet access"):
        weather.cmd(argparse.Namespace(days=1))
    with pytest.raises(ToolError, match="--days"):
        weather.cmd(argparse.Namespace(days=9))


def test_weather_is_read_only():
    decision = safety.classify("./robot weather --days 2")
    assert (decision.action, decision.category) == ("allow", "read")


# ----- plant survey: standing check and photos -----

def survey_args(**kw):
    defaults = dict(name=None, camera=None, seconds=None, fps=None, photos=None, speed=None,
                    rate=1.0, settle_wait=60.0, timeout=5.0)
    return argparse.Namespace(**{**defaults, **kw})


@pytest.fixture()
def ready(sim, monkeypatch):
    trajectory.record(argparse.Namespace(name="survey", seconds=24, teach_wait=30.0,
                                         start_delay=0.0))
    config.set_camera_source("orbbec_gemini", "ros:/camera/color/image_raw")
    base.SimBase().command("stand-up")
    return sim


def test_survey_check_needs_the_b2_standing(ready, capsys):
    base.SimBase().command("stand-down")
    survey.check(survey_args())
    out = capsys.readouterr().out
    assert "B2 base: NOT READY - lie down" in out
    assert "ready: no - fix: B2 base" in out and "./robot base stand-up" in out
    base.SimBase().command("stand-up")
    survey.check(survey_args())
    out = capsys.readouterr().out
    assert "B2 base: OK - standing still" in out and "ready: yes" in out
    assert "20 s video at 10 fps + 8 photos spread over the whole motion" in out


def test_survey_run_refuses_unless_standing(ready, monkeypatch):
    played = []
    monkeypatch.setattr(trajectory, "play", lambda *a, **k: played.append(1))
    base.SimBase().command("stand-down")
    with pytest.raises(ToolError, match=r"refusing the plant survey: the B2 is not standing"):
        survey.run(survey_args())
    assert played == []


def test_survey_run_takes_photos_over_the_whole_motion(ready, monkeypatch, capsys):
    def fake_play(play_args, on_start=None):
        on_start()
        return 0

    saved = []
    real_save = camera.save_image
    monkeypatch.setattr(trajectory, "play", fake_play)
    monkeypatch.setattr(camera, "save_image",
                        lambda name, frame: saved.append(name) or real_save(name, frame))
    assert survey.run(survey_args(photos=6)) == 0
    out = capsys.readouterr().out
    # 24 s motion: photos every 4 s from 2 s, the last one after the 20 s video has ended.
    assert saved == [f"survey_orbbec_gemini_{i:02d}" for i in range(1, 7)]
    assert "photo 1/6 at 2.0 s:" in out and "photo 6/6 at 22.0 s:" in out
    assert out.count("IMAGE: ") == 6 and "photos: 6 of 6 captured" in out
    assert "200 frames at 10 fps (20.0 s)" in out
    assert "plant survey complete" in out and "6 of 6 photos" in out


def test_survey_photo_count_is_bounded(ready):
    with pytest.raises(ToolError, match="--photos must be between 0 and 10"):
        survey.run(survey_args(photos=11))


def test_v4l2_camera_keeps_running_for_stills_after_the_clip(sim, monkeypatch):
    import time

    import cv2
    import numpy as np

    class FakeCapture:
        def __init__(self, dev, api):
            pass

        def isOpened(self):
            return True

        def read(self):
            time.sleep(0.005)
            return True, np.full((48, 64, 3), 120, np.uint8)

        def release(self):
            pass

    monkeypatch.setattr(cv2, "VideoCapture", FakeCapture)
    seen = []
    path, info, synthetic = camera.record("orbbec_gemini", "v4l2:0", 1.0, 10.0, 1.0,
                                          on_frame=lambda t, f: seen.append(t),
                                          run_seconds=2.0)
    assert not synthetic and path.exists()
    assert " 10 frames at " in info or " 11 frames at " in info  # the clip stops after 1 s
    assert 18 <= len(seen) <= 21 and 1.8 <= seen[-1] < 2.1  # stills continue for 2 s
