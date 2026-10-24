"""Tests of the B2 front/rear camera capture (unitree_api request/response over ROS 2)."""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from robot_tools import camera, ros
from robot_tools.common import ToolError, Unavailable


def _request():
    return SimpleNamespace(header=SimpleNamespace(identity=SimpleNamespace(id=0, api_id=0)))


def _response(identity, code=0, binary=b""):
    signed = np.frombuffer(binary, np.uint8).view(np.int8).tolist()  # unitree_api: int8[] binary
    return SimpleNamespace(header=SimpleNamespace(identity=identity,
                                                  status=SimpleNamespace(code=code)),
                           binary=signed)


@pytest.fixture()
def fake_ros(monkeypatch):
    calls = []
    reply = {}

    class FakeRos:
        def call(self, request_topic, msg, response_topic, response_type, timeout, match):
            calls.append((request_topic, response_topic, msg.header.identity.api_id))
            if "build" not in reply:
                return None
            other = _response(SimpleNamespace(id=-1, api_id=1001))
            assert not match(other)  # replies to other requests are ignored
            resp = reply["build"](msg.header.identity)
            return resp if match(resp) else None

    @contextmanager
    def session(name):
        yield FakeRos()

    monkeypatch.setattr(ros, "message_type", lambda name: _request)
    monkeypatch.setattr(ros, "session", session)
    return calls, reply


def test_b2_camera_decodes_jpeg_reply(fake_ros):
    calls, reply = fake_ros
    image = np.zeros((48, 64, 3), np.uint8)
    image[:, :, 2] = 200  # bytes >127 exercise the signed int8 conversion
    jpeg = cv2.imencode(".jpg", image)[1].tobytes()
    reply["build"] = lambda identity: _response(identity, binary=jpeg)
    frame = camera.capture_unitree("front_videohub", timeout=1)
    assert frame.shape == (48, 64, 3) and frame[:, :, 2].mean() > 150
    assert calls == [("/api/front_videohub/request", "/api/front_videohub/response", 1001)]


def test_b2_camera_errors(fake_ros):
    _, reply = fake_ros
    with pytest.raises(Unavailable, match="no reply"):
        camera.capture_unitree("back_videohub", timeout=1)
    reply["build"] = lambda identity: _response(identity, code=3104)
    with pytest.raises(ToolError, match="error code 3104"):
        camera.capture_unitree("back_videohub", timeout=1)
    reply["build"] = lambda identity: _response(identity, binary=b"not a jpeg")
    with pytest.raises(ToolError, match="no decodable image"):
        camera.capture_unitree("back_videohub", timeout=1)


def test_unconfigured_camera_is_reported(monkeypatch):
    with pytest.raises(ToolError, match="not set up yet"):
        camera.capture("icamera", "", timeout=1)
    with pytest.raises(ToolError, match="unknown source"):
        camera.capture("x", "rtsp://host/stream", timeout=1)


FAKE_SDK = r"""
#include <stdlib.h>
#include <string.h>
int im_info_w = 752, im_info_h = 480, im_info_bpp = 1;
void *im_pCameraBuffer, *im_pTripleBuffer;
int g_pack_e = 1;
static unsigned char a[752 * 480], b[752 * 480];
int InitCameraTransfer(void) {
    const char *rc = getenv("FAKE_ICAMERA_INIT");
    memset(a, 100, sizeof a); memset(b, 200, sizeof b);
    im_pCameraBuffer = a; im_pTripleBuffer = b;
    return rc ? atoi(rc) : 0;
}
int iCameraGrabFrame(void) { return 1; }
void bayer2rgb24(unsigned char *dst, unsigned char *src, int w, int h) {
    for (int i = 0; i < w * h; i++) { dst[3*i] = src[i]; dst[3*i+1] = src[i] / 2; dst[3*i+2] = 0; }
}
void FreeiCamera(void) { abort(); }  /* the real SDK hits a libusb assertion here */
"""


@pytest.fixture()
def fake_icamera(tmp_path, monkeypatch):
    import shutil
    import subprocess

    from robot_tools import config, icamera

    if not shutil.which("gcc") or not Path(icamera.LIBUSB).exists():
        pytest.skip("needs gcc and libusb")
    sdk = tmp_path / "sdk"
    sdk.mkdir()
    (tmp_path / "fake.c").write_text(FAKE_SDK)
    subprocess.run(["gcc", "-shared", "-fPIC", "-o", str(sdk / "libiCamera.so"),
                    str(tmp_path / "fake.c")], check=True)
    subprocess.run(["gcc", "-shared", "-fPIC", "-x", "c", "/dev/null", "-o",
                    str(sdk / "libgraph.so")], check=True)
    node = tmp_path / "usbnode"
    node.write_bytes(b"")
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(icamera, "usb_node", lambda: str(node))
    monkeypatch.setattr(icamera, "busy_reason", lambda: None)
    monkeypatch.setattr(icamera, "WARMUP_S", 0.1)
    return icamera, sdk


def test_icamera_frame_survives_sdk_crash_on_release(fake_icamera):
    icamera, sdk = fake_icamera
    frame, note = icamera.capture(str(sdk), timeout=2)
    assert frame.shape == (480, 752, 3)
    assert tuple(int(v) for v in frame[0, 0]) == (0, 100, 200)  # BGR of the swapped buffer
    assert "packet errors 1" in note and "crashed while releasing" in note
    assert not list((icamera.config.ARTIFACTS_DIR / "run").glob("icamera_*.png"))


def test_icamera_init_failure_is_reported(fake_icamera, monkeypatch):
    icamera, sdk = fake_icamera
    monkeypatch.setenv("FAKE_ICAMERA_INIT", "-3")
    with pytest.raises(ToolError, match="InitCameraTransfer returned -3"):
        icamera.capture(str(sdk), timeout=2)


def test_icamera_refuses_when_busy_or_missing(fake_icamera, monkeypatch):
    icamera, sdk = fake_icamera
    monkeypatch.setattr(icamera, "busy_reason", lambda: "icamera.service is running")
    with pytest.raises(Unavailable, match="icamera.service is running"):
        icamera.capture(str(sdk), timeout=2)
    monkeypatch.setattr(icamera, "usb_node", lambda: None)
    with pytest.raises(Unavailable, match="not detected"):
        icamera.capture(str(sdk), timeout=2)


def test_fallback_source_used_when_ros_driver_missing(monkeypatch, tmp_path):
    from robot_tools import config

    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(config, "is_sim", lambda: False)

    def no_driver(topic, timeout):
        raise Unavailable("no image received")

    monkeypatch.setattr(camera, "capture_ros", no_driver)
    monkeypatch.setattr(camera, "capture_v4l2", lambda dev: np.full((360, 640, 3), 90, np.uint8))
    path, info, synthetic = camera.capture("realsense_d455", "ros:/camera/camera/color/image_raw",
                                           1, "v4l2:/dev/video4")
    assert path.is_file() and "via fallback v4l2:/dev/video4" in info and not synthetic
    with pytest.raises(Unavailable):
        camera.capture("realsense_d455", "ros:/camera/camera/color/image_raw", 1)
