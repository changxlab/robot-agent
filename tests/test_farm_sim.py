"""Simulated farm data used in SIM mode: camera frames, video clips, point clouds and maps."""

import math
import shutil
from types import SimpleNamespace

import numpy as np
import pytest

from robot_tools import camera, config, farm_sim, mapping


@pytest.fixture()
def sim(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(config, "is_sim", lambda: True)
    return tmp_path


def read_pcd(path):
    raw = path.read_bytes()
    end = raw.index(b"DATA binary\n") + len(b"DATA binary\n")
    header = dict(line.split(" ", 1) for line in raw[:end].decode().splitlines()
                  if line and not line.startswith("#"))
    fields = header["FIELDS"].split()
    types = {"F": "<f4", "U": "<u4"}
    dtype = np.dtype([(f, types[t]) for f, t in zip(fields, header["TYPE"].split())])
    return header, np.frombuffer(raw[end:], dtype=dtype)


def test_camera_frames_show_real_plant_photos(sim):
    assert len(farm_sim.photos("field")) >= 4 and len(farm_sim.photos("closeup")) >= 4
    front = farm_sim.camera_frame("b2_front", 0.0, "stamp")
    assert front.shape == (480, 640, 3)
    b, g, r = (front[..., i].astype(int) for i in range(3))
    assert ((g > r + 15) & (g > b + 10)).mean() > 0.1  # plenty of vegetation
    assert farm_sim.camera_frame("realsense_d455").shape == (360, 640, 3)
    assert farm_sim.camera_frame("icamera").shape == (480, 752, 3)
    # Frames follow the simulated B2 pose: turning around changes the view.
    (config.artifacts("sim") / "base.json").write_text(
        '{"mode": 1, "position": [0.0, 0.0, 0.0], "yaw": 3.1416}')
    assert np.abs(farm_sim.camera_frame("b2_front", 0.0, "stamp").astype(int) - front).mean() > 10
    # Clips sway slightly over time instead of freezing.
    assert np.abs(farm_sim.camera_frame("b2_front", 0.0).astype(int)
                  - farm_sim.camera_frame("b2_front", 1.5).astype(int)).mean() > 2


def test_camera_frames_fall_back_to_rendered_farm_without_photos(sim, monkeypatch):
    monkeypatch.setattr(farm_sim, "PHOTO_DIR", sim / "no_photos")
    farm_sim.photos.cache_clear()
    try:
        front = farm_sim.camera_frame("b2_front", 0.0, "stamp")
    finally:
        farm_sim.photos.cache_clear()
    b, g, r = (front[..., i].astype(int) for i in range(3))
    assert front.shape == (480, 640, 3)
    assert (b[:60] > r[:60]).mean() > 0.5  # rendered sky at the top


def test_sim_capture_uses_farm_scene(sim):
    path, info, synthetic = camera.capture("b2_front", "unitree:front_videohub", 1)
    assert synthetic and path.is_file() and "SIMULATED image" in info and "simulated farm" in info


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_sim_record_writes_h264_clip(sim):
    path, info, synthetic = camera.record("b2_front", "unitree:front_videohub", 1.0, 4, 1)
    assert synthetic and path.suffix == ".mp4" and path.parent.name == "videos"
    assert path.stat().st_size > 1000 and "4 frames" in info
    with pytest.raises(camera.ToolError, match="not set up yet"):
        camera.record("orbbec_gemini", "", 1.0, 4, 1)


def test_pcd_round_trip(tmp_path):
    xyz = np.array([[1, 2, 3], [-1.5, 0, 0.25]], np.float32)
    bgr = np.array([[10, 20, 30], [255, 0, 128]], np.float32)
    n = farm_sim.write_pcd(tmp_path / "c.pcd", xyz, bgr, np.array([5, 7], np.float32))
    header, rec = read_pcd(tmp_path / "c.pcd")
    assert n == 2 and header["POINTS"] == "2" and header["FIELDS"] == "x y z rgb intensity"
    assert np.allclose(np.column_stack([rec["x"], rec["y"], rec["z"]]), xyz)
    assert rec["rgb"][0] == (30 << 16) | (20 << 8) | 10  # packed 0xRRGGBB
    assert list(rec["intensity"]) == [5, 7]


def test_sim_map_save_writes_grid_and_cloud(sim, capsys):
    assert mapping.save("field_1") == 0
    out = capsys.readouterr().out
    assert "IMAGE: artifacts/maps/field_1.png" in out
    assert "POINTCLOUD: artifacts/maps/field_1.pcd" in out
    header, rec = read_pcd(sim / "artifacts" / "maps" / "field_1.pcd")
    assert int(header["POINTS"]) > 100000
    assert rec["z"].max() > 1.0  # maize, fence posts, shed and trees stand above the soil
    grid = farm_sim.occupancy_map()
    assert {0, 205, 254} <= set(np.unique(grid).tolist())
    # The robot starts in a free lane between crop rows.
    col = row = int((0 - farm_sim.MAP_ORIGIN) / farm_sim.MAP_RES)
    assert grid[farm_sim.MAP_SIZE - 1 - row, col] == 254


def test_sim_lidar_scan_is_in_robot_frame(sim, capsys):
    assert mapping.scan("scan_a") == 0
    assert "POINTCLOUD: artifacts/pointclouds/scan_a.pcd" in capsys.readouterr().out
    _, rec = read_pcd(sim / "artifacts" / "pointclouds" / "scan_a.pcd")
    rng = np.hypot(rec["x"], rec["y"])
    assert len(rec) > 10000 and rng.max() < 15.5 and rng.min() > 0.5
    with pytest.raises(mapping.ToolError):
        mapping.scan("../bad")


def test_pointcloud2_parsing():
    dtype = np.dtype({"names": ["x", "y", "z", "intensity"], "formats": ["<f4"] * 4,
                      "offsets": [0, 4, 8, 16], "itemsize": 32})
    rec = np.zeros(3, dtype)
    rec["x"], rec["y"], rec["z"], rec["intensity"] = [1, math.nan, 3], [4, 5, 6], [7, 8, 9], [1, 2, 3]
    field = lambda name, off: SimpleNamespace(name=name, offset=off, datatype=7)  # noqa: E731
    msg = SimpleNamespace(is_bigendian=False, point_step=32, width=3, height=1, data=rec.tobytes(),
                          fields=[field("x", 0), field("y", 4), field("z", 8),
                                  field("intensity", 16), field("ring", 20)])
    xyz, inten = mapping._cloud_to_arrays(msg)
    assert xyz.tolist() == [[1, 4, 7], [3, 6, 9]] and inten.tolist() == [1, 3]
