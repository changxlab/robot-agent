"""Camera discovery and still capture (ROS image topics, V4L2 devices, B2 video service,
iCamera vendor SDK)."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from . import config
from .common import (ToolError, Unavailable, display_path, header, image_line, kv, run, sim_tag,
                     video_line)

USB_VENDORS = {"8086": "Intel RealSense", "2bc5": "Orbbec", "ae86": "CCJT iCAMERA"}
SOURCE_KINDS = ("ros", "v4l2", "unitree", "icamera")
DARK_MEAN = 5.0  # mean pixel value below which a frame is reported as dark
# B2 video service (front_videohub / back_videohub) GetImageSample, from unitree_sdk2
# b2/front_video/front_video_api.hpp: one JPEG per request.
VIDEO_API_GET_IMAGE_SAMPLE = 1001
MAX_RECORD_S = 20.0
MAX_RECORD_FPS = 15.0
SIM_IMAGE_NOTE = ("SIMULATED image: a real plant photo standing in for the simulated farm "
                  "(simulation, not the robot's actual view)")
SIM_CLIP_NOTE = ("SIMULATED clip: a real plant photo standing in for the simulated farm "
                 "(simulation, not the robot's actual view)")


def _out_path(name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return config.artifacts("captures") / f"{stamp}_{name}.jpg"


def _ros_to_bgr(msg):
    import numpy as np
    import cv2

    if hasattr(msg, "format"):  # sensor_msgs/CompressedImage
        return cv2.imdecode(np.frombuffer(bytes(msg.data), np.uint8), cv2.IMREAD_COLOR)
    data = np.frombuffer(bytes(msg.data), np.uint8)
    enc = msg.encoding.lower()
    if enc in ("rgb8", "bgr8"):
        img = data.reshape(msg.height, msg.step)[:, : msg.width * 3].reshape(msg.height, msg.width, 3)
        return cv2.cvtColor(img, cv2.COLOR_RGB2BGR) if enc == "rgb8" else img.copy()
    if enc in ("mono8", "8uc1"):
        return data.reshape(msg.height, msg.step)[:, : msg.width].copy()
    if enc in ("yuv422", "uyvy", "yuyv", "yuv422_yuy2"):
        img = data.reshape(msg.height, msg.width, 2)
        code = cv2.COLOR_YUV2BGR_YUYV if enc in ("yuyv", "yuv422_yuy2") else cv2.COLOR_YUV2BGR_UYVY
        return cv2.cvtColor(img, code)
    if enc in ("16uc1", "mono16"):  # depth: normalise for viewing
        depth = np.frombuffer(bytes(msg.data), np.uint16).reshape(msg.height, msg.width)
        return cv2.applyColorMap(cv2.convertScaleAbs(depth, alpha=255.0 / max(1, depth.max())),
                                 cv2.COLORMAP_JET)
    raise ToolError(f"unsupported image encoding {msg.encoding}")


def capture_ros(topic: str, timeout: float):
    from . import ros

    type_name = ("sensor_msgs/msg/CompressedImage" if topic.endswith("/compressed")
                 else "sensor_msgs/msg/Image")
    with ros.session("camera_capture") as r:
        msg = r.wait_for(topic, type_name, timeout)
    if msg is None:
        raise Unavailable(f"no image received on {topic} within {timeout:.0f}s; is the camera "
                          "driver running? (see `./robot camera list`)")
    return _ros_to_bgr(msg)


def capture_unitree(service: str, timeout: float):
    """One JPEG frame from a B2 video service over ROS 2 (unitree_api Request/Response)."""
    import cv2
    import numpy as np

    from . import ros

    Request = ros.message_type("unitree_api/msg/Request")
    req = Request()
    req.header.identity.id = int(time.time() * 1e6) % (2**62)
    req.header.identity.api_id = VIDEO_API_GET_IMAGE_SAMPLE
    with ros.session("camera_capture") as r:
        resp = r.call(f"/api/{service}/request", req, f"/api/{service}/response",
                      "unitree_api/msg/Response", timeout,
                      match=lambda m: m.header.identity.id == req.header.identity.id)
    if resp is None:
        raise Unavailable(f"no reply from the B2 video service '{service}' within {timeout:.0f}s; "
                          "check the B2 network link (ros.dds_interface) and that the service "
                          "is running")
    if resp.header.status.code != 0:
        raise ToolError(f"B2 video service '{service}' returned error code "
                        f"{resp.header.status.code}")
    jpeg = np.asarray(resp.binary, dtype=np.int8).view(np.uint8)
    frame = cv2.imdecode(jpeg, cv2.IMREAD_COLOR) if jpeg.size else None
    if frame is None:
        raise ToolError(f"B2 video service '{service}' returned no decodable image "
                        f"({jpeg.size} bytes)")
    return frame


def capture_v4l2(device: str):
    import cv2

    dev: int | str = int(device) if device.isdigit() else device
    if isinstance(dev, str) and not Path(dev).exists():
        raise Unavailable(f"video device {dev} does not exist")
    cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
    try:
        if not cap.isOpened():
            raise Unavailable(f"could not open {device} (in use by another process?)")
        frame = None
        for i in range(30):  # let auto exposure settle; keep trying a little longer while dark
            ok, frame = cap.read()
            if i >= 7 and frame is not None and frame.mean() >= DARK_MEAN:
                break
            time.sleep(0.03)
        if frame is None:
            raise Unavailable(f"no frame from {device}")
        return frame
    finally:
        cap.release()


def synthetic(name: str, t: float = 0.0):
    """Simulated frame of the farm scene seen by camera ``name`` at the simulated B2 pose."""
    from . import farm_sim

    return farm_sim.camera_frame(name, t, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def grab(name: str, source: str, timeout: float):
    """One frame from ``source``; returns (frame, extra note, synthetic)."""
    kind, _, target = source.partition(":")
    if not source:
        raise ToolError(f"camera '{name}' is not set up yet (no source in robot.yaml)")
    if kind not in SOURCE_KINDS or not target:
        raise ToolError(f"camera '{name}': unknown source {source!r} (use ros:<topic>, "
                        "v4l2:<dev>, unitree:<video service> or icamera:<sdk dir>)")
    if kind == "v4l2":
        return capture_v4l2(target), "", False
    if config.is_sim():
        return synthetic(name), "", True
    if kind == "ros":
        return capture_ros(target, timeout), "", False
    if kind == "unitree":
        return capture_unitree(target, timeout), "", False
    from . import icamera

    frame, note = icamera.capture(target, timeout)
    return frame, note, False


def capture(name: str, source: str, timeout: float,
            fallback: str = "") -> tuple[Path, str, bool]:
    """Capture one frame; returns (path, description, synthetic)."""
    import cv2

    try:
        frame, extra, synthetic_frame = grab(name, source, timeout)
    except Unavailable as exc:
        if not fallback:
            raise
        frame, extra, synthetic_frame = grab(name, fallback, timeout)
        extra += f" (via fallback {fallback}: {source} unavailable - {exc})"
    path = _out_path(name)
    if not cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 88]):
        raise ToolError(f"could not write {path}")
    h, w = frame.shape[:2]
    note = (f" {SIM_IMAGE_NOTE}" if synthetic_frame else " real camera frame")
    note += extra
    if not synthetic_frame and float(frame.mean()) < DARK_MEAN:
        note += (" - WARNING: the frame is completely dark (lens covered, privacy shutter "
                 "closed, or no light)")
    return path, f"{w}x{h}{note}", synthetic_frame


def _video_path(name: str, ext: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return config.artifacts("videos") / f"{stamp}_{name}.{ext}"


def encode_video(frames: list, fps: float, name: str) -> Path:
    """Write BGR frames as a browser-playable clip: H.264 MP4 via ffmpeg, else VP8 WebM."""
    import shutil
    import subprocess

    import cv2

    h, w = frames[0].shape[:2]
    w2, h2 = w - w % 2, h - h % 2  # yuv420p needs even dimensions
    if shutil.which("ffmpeg"):
        path = _video_path(name, "mp4")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{w2}x{h2}", "-r", f"{fps:.3f}", "-i", "-", "-c:v", "libx264",
               "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", str(path)]
        data = b"".join(f[:h2, :w2].tobytes() for f in frames)
        proc = subprocess.run(cmd, input=data, capture_output=True, timeout=120)
        if proc.returncode == 0 and path.is_file():
            return path
        path.unlink(missing_ok=True)
    path = _video_path(name, "webm")
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"VP80"), fps, (w, h))
    if not writer.isOpened():
        raise ToolError("no video encoder available (install ffmpeg with libx264)")
    for f in frames:
        writer.write(f)
    writer.release()
    return path


def record(name: str, source: str, seconds: float, fps: float, timeout: float,
           fallback: str = "", start_event=None, stop_event=None, start_wait: float = 300.0,
           label: str | None = None) -> tuple[Path, str, bool]:
    """Record a short clip; returns (path, description, synthetic).

    With ``start_event`` the camera is opened first and recording starts when the event is set
    (so a clip can be synchronised with a motion); ``stop_event`` ends it early.
    """
    seconds = max(1.0, min(seconds, MAX_RECORD_S))
    fps = max(1.0, min(fps, MAX_RECORD_FPS))
    label = label or name
    kind, _, target = source.partition(":")
    if not source:
        raise ToolError(f"camera '{name}' is not set up yet (no source in robot.yaml)")
    if config.is_sim() and kind != "v4l2":
        _wait_start(start_event, start_wait)
        start = time.time()
        frames = [_synthetic_at(name, i / fps, start + i / fps) for i in range(int(seconds * fps))]
        path = encode_video(frames, fps, label)
        h, w = frames[0].shape[:2]
        return path, (f"{w}x{h} {len(frames)} frames at {fps:.0f} fps ({seconds:.1f} s) "
                      f"{SIM_CLIP_NOTE}"), True
    if kind == "v4l2":
        return _record_v4l2(target, seconds, fps, label, start_event, stop_event, start_wait)
    _wait_start(start_event, start_wait)
    frames, start, used = [], time.monotonic(), source
    while time.monotonic() - start < seconds and not (stop_event and stop_event.is_set()):
        t0 = time.monotonic()
        try:
            frame, _, _ = grab(name, used, timeout)
        except Unavailable:
            if not fallback or used == fallback:
                raise
            used = fallback
            frame, _, _ = grab(name, used, timeout)
        frames.append(frame)
        time.sleep(max(0.0, 1.0 / fps - (time.monotonic() - t0)))
    if not frames:
        raise ToolError("recording was stopped before any frame was captured")
    elapsed = max(time.monotonic() - start, 1e-3)
    real_fps = max(1.0, len(frames) / elapsed)
    path = encode_video(frames, real_fps, label)
    h, w = frames[0].shape[:2]
    note = f" (via fallback {fallback})" if used != source else ""
    return path, (f"{w}x{h} {len(frames)} frames at {real_fps:.1f} fps ({elapsed:.1f} s) real "
                  f"camera clip{note}"), False


def _wait_start(start_event, start_wait: float) -> None:
    if start_event is not None and not start_event.wait(start_wait):
        raise ToolError("recording was never started")


def _record_v4l2(device: str, seconds: float, fps: float, label: str, start_event,
                 stop_event, start_wait: float) -> tuple[Path, str, bool]:
    """Keep the device open for the whole clip (opening it per frame is far too slow)."""
    import cv2

    dev: int | str = int(device) if device.isdigit() else device
    if isinstance(dev, str) and not Path(dev).exists():
        raise Unavailable(f"video device {dev} does not exist")
    cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
    try:
        if not cap.isOpened():
            raise Unavailable(f"could not open {device} (in use by another process?)")
        for _ in range(8):  # let auto exposure settle before the clip starts
            cap.read()
        _wait_start(start_event, start_wait)
        frames, start = [], time.monotonic()
        next_at = start
        while time.monotonic() - start < seconds and not (stop_event and stop_event.is_set()):
            ok, frame = cap.read()  # keep draining the driver buffer so frames stay current
            if not ok or frame is None:
                if not frames:
                    raise Unavailable(f"no frame from {device}")
                break
            if time.monotonic() >= next_at:
                frames.append(frame)
                next_at += 1.0 / fps
    finally:
        cap.release()
    if not frames:
        raise ToolError("recording was stopped before any frame was captured")
    elapsed = max(time.monotonic() - start, 1e-3)
    real_fps = max(1.0, len(frames) / elapsed)
    path = encode_video(frames, real_fps, label)
    h, w = frames[0].shape[:2]
    dark = (" - WARNING: the clip is completely dark (lens covered or no light)"
            if float(frames[len(frames) // 2].mean()) < DARK_MEAN else "")
    return path, (f"{w}x{h} {len(frames)} frames at {real_fps:.1f} fps ({elapsed:.1f} s) real "
                  f"camera clip{dark}"), False


# ----- V4L2 device discovery (to choose a source, e.g. for the Orbbec Gemini RGB stream) -----

COLOUR_FORMATS = {"YUYV", "MJPG", "RGB3", "BGR3", "NV12", "YU12", "UYVY", "H264", "JPEG"}
DEPTH_FORMATS = {"Z16", "Y16", "Y12I", "Y16I"}
IR_FORMATS = {"GREY", "Y8", "Y10", "Y12", "Y8I"}


def v4l2_devices() -> list[dict[str, str]]:
    """Video capture nodes: stable by-id path, /dev node, name, USB vendor, formats, kind."""
    import re

    by_id = {}
    for link in sorted(Path("/dev/v4l/by-id").glob("*")) if Path("/dev/v4l/by-id").is_dir() else []:
        by_id.setdefault(str(link.resolve()), str(link))
    devices = []
    for sys_dir in sorted(Path("/sys/class/video4linux").glob("video*"),
                          key=lambda p: int(re.sub(r"\D", "", p.name) or 0)):
        node = f"/dev/{sys_dir.name}"
        code, out = run(["v4l2-ctl", "-d", node, "--list-formats"], timeout=5)
        formats = [f.strip() for f in re.findall(r"\[\d+\]: '([^']+)'", out)] if code == 0 else []
        if not formats:
            continue  # metadata node or unreadable
        name = (sys_dir / "name").read_text().strip() if (sys_dir / "name").exists() else ""
        vendor_file = (sys_dir / "device").resolve().parent / "idVendor"
        vid = vendor_file.read_text().strip() if vendor_file.exists() else ""
        kind = ("colour" if COLOUR_FORMATS & set(formats) else
                "depth" if DEPTH_FORMATS & set(formats) else
                "IR/mono" if IR_FORMATS & set(formats) else "other")
        devices.append({"path": by_id.get(node, node), "node": node, "name": name,
                        "vendor": USB_VENDORS.get(vid, vid or "?"),
                        "formats": ",".join(formats), "kind": kind})
    return devices


def print_v4l2_devices(indent: str = "  ") -> list[dict[str, str]]:
    devices = v4l2_devices()
    if not devices:
        print(f"{indent}no V4L2 capture devices found")
    for i, d in enumerate(devices, start=1):
        print(f"{indent}{i}. v4l2:{d['path']}")
        print(f"{indent}   {d['node']} - {d['name']} ({d['vendor']}), {d['kind']}: {d['formats']}")
    return devices


def set_source(name: str, source: str, timeout: float) -> int:
    """Test ``source`` with one frame, then save it as camera ``name``'s source."""
    if name not in config.cameras():
        raise ToolError(f"unknown camera {name!r}; configured: {', '.join(config.cameras())}")
    kind, _, target = source.partition(":")
    if kind not in SOURCE_KINDS or not target:
        raise ToolError(f"invalid source {source!r} (use v4l2:<device>, ros:<topic>, "
                        "unitree:<video service> or icamera:<sdk dir>)")
    if kind == "v4l2" and not target.startswith("/dev/") and not target.isdigit():
        raise ToolError("a v4l2 source must be a /dev/... path (prefer /dev/v4l/by-id/...)")
    path, info, _ = capture(name, source, timeout)  # refuse a source that gives no frame
    config.set_camera_source(name, source)
    rel = display_path(path)
    print(f"{sim_tag()}camera '{name}': source set to {source} (saved in "
          f"{display_path(config.camera_sources_file())}, overrides robot.yaml); "
          f"test frame {info} -> {rel}")
    image_line(str(rel))
    return 0


def _synthetic_at(name: str, t: float, epoch: float):
    from . import farm_sim

    return farm_sim.camera_frame(name, t, datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S"))


def list_cameras() -> int:
    header("Configured cameras")
    for name, source in config.cameras().items():
        kind, _, target = source.partition(":")
        available = "unknown"
        if not source:
            available = "not set up yet"
        elif kind == "v4l2":
            available = "device present" if (target.isdigit() or Path(target).exists()) else "missing"
        elif kind == "unitree":
            available = "B2 video service"
        elif kind == "icamera":
            from . import icamera

            available = "USB device present" if icamera.usb_node() else "USB device missing"
            busy = icamera.busy_reason()
            if busy:
                available += f"; busy: {busy}"
        fallback = config.camera_fallback(name)
        chosen = " (set with camera set-source)" if name in config.camera_source_overrides() else ""
        kv(name, f"{source or '-'}{chosen}  [{available}]"
           + (f"  fallback {fallback}" if fallback else ""))

    header("USB depth cameras", real=True)
    code, out = run(["lsusb"], timeout=5)
    found = [line for line in out.splitlines()
             if any(f"ID {vid}:" in line for vid in USB_VENDORS)] if code == 0 else []
    for line in found:
        print(f"  {line}")
    if not found:
        print("  none detected" if code == 0 else f"  lsusb unavailable: {out}")

    header("V4L2 devices", real=True)
    code, out = run(["v4l2-ctl", "--list-devices"], timeout=5)
    print("\n".join(f"  {line}" for line in out.splitlines()) or "  none")

    if not config.is_sim():
        header("ROS image topics")
        try:
            from . import ros

            with ros.session("camera_list") as r:
                topics = r.topics()
            images = sorted(t for t, types in topics.items()
                            if any(x.startswith("sensor_msgs/msg/") and "Image" in x for x in types))
            print("\n".join(f"  {t}" for t in images) or "  none (camera drivers not running?)")
        except Unavailable as exc:
            print(f"  unavailable: {exc}")
    return 0


def describe(path: Path, prompt: str) -> str:
    """Ask the configured Anthropic-compatible model to describe an image.

    The image is sent as a user content block, which works through gateways that do not
    forward images inside tool results.
    """
    import base64
    import json
    import os
    import urllib.error
    import urllib.request

    base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    model = os.environ.get("ROBOT_VISION_MODEL") or os.environ.get("ANTHROPIC_MODEL", "")
    if not model or not (auth_token or api_key):
        raise Unavailable("no vision model configured (ROBOT_VISION_MODEL and "
                          "ANTHROPIC_AUTH_TOKEN/ANTHROPIC_API_KEY); open the image with Read instead")
    media = "image/png" if path.suffix == ".png" else "image/jpeg"
    body = {
        "model": model,
        "max_tokens": 700,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media,
                                         "data": base64.b64encode(path.read_bytes()).decode()}},
            {"type": "text", "text": (
                "This image comes from a camera on a legged robot with a manipulator arm. "
                f"{prompt} Describe only what is visible; say so if the image is dark, blurred "
                "or a placeholder. Be concise and concrete (objects, positions, distances, "
                "obstacles, people, text).")},
        ]}],
    }
    headers = {"content-type": "application/json", "anthropic-version": "2023-06-01"}
    if auth_token:
        headers["authorization"] = f"Bearer {auth_token}"
    else:
        headers["x-api-key"] = api_key
    req = urllib.request.Request(f"{base}/v1/messages", json.dumps(body).encode(), headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        raise Unavailable(f"vision request failed: {exc}") from exc
    return "\n".join(c.get("text", "") for c in data.get("content", [])
                     if c.get("type") == "text").strip()


def cmd(args) -> int:
    if args.action == "list":
        return list_cameras()
    if args.action == "devices":
        header("V4L2 capture devices", real=True)
        print_v4l2_devices()
        print("\nUse a colour device for an RGB camera: ./robot camera set-source --camera NAME "
              "--source v4l2:<path>")
        return 0
    if args.action == "set-source":
        if args.camera == "all":
            raise ToolError("set-source needs --camera NAME")
        if args.clear:
            config.set_camera_source(args.camera, None)
            print(f"camera '{args.camera}': operator source removed; robot.yaml applies again")
            return 0
        if not args.source:
            raise ToolError("set-source needs --source (or --clear)")
        return set_source(args.camera, args.source, args.timeout)
    cams = config.cameras()
    if args.camera == "all":
        names = [n for n, src in cams.items() if src]
        skipped = [n for n, src in cams.items() if not src]
        if skipped:
            print(f"skipping {', '.join(skipped)} (not set up yet)")
        if not names:
            raise ToolError("no cameras are set up in robot.yaml")
    else:
        names = [args.camera]
    failures = 0
    for name in names:
        if name not in cams:
            raise ToolError(f"unknown camera {name!r}; configured: {', '.join(cams)}")
        try:
            if args.action == "record":
                path, info, synthetic_frame = record(name, cams[name], args.seconds, args.fps,
                                                     args.timeout, config.camera_fallback(name))
            else:
                path, info, synthetic_frame = capture(name, cams[name], args.timeout,
                                                      config.camera_fallback(name))
        except ToolError as exc:
            failures += 1
            print(f"{sim_tag()}camera '{name}': {args.action} failed - {exc}")
            continue
        rel = display_path(path)
        verb = "recorded" if args.action == "record" else "captured"
        print(f"{'[SIM] ' if synthetic_frame else ''}camera '{name}': {verb} {info} -> {rel}")
        (video_line if args.action == "record" else image_line)(str(rel))
        if args.action == "look":
            try:
                print(f"what camera '{name}' sees:\n{describe(path, args.prompt)}\n")
            except ToolError as exc:
                print(f"camera '{name}': could not describe the image - {exc}")
    return 1 if failures == len(names) else 0


def register(sub) -> None:
    p = sub.add_parser("camera", help="list cameras, capture still images or short clips, "
                                      "describe the scene")
    p.add_argument("action", choices=["list", "devices", "capture", "look", "record",
                                       "set-source"])
    p.add_argument("--camera", default="all", help="camera name from robot.yaml or 'all'")
    p.add_argument("--source", help="set-source: v4l2:<device>, ros:<topic>, ...")
    p.add_argument("--clear", action="store_true",
                   help="set-source: remove the operator's source (back to robot.yaml)")
    p.add_argument("--timeout", type=float, default=5.0,
                   help="seconds to wait for a ROS frame or B2 video reply")
    p.add_argument("--prompt", default="Describe the scene.",
                   help="what to look for (look only)")
    p.add_argument("--seconds", type=float, default=5.0,
                   help=f"clip length for record (max {MAX_RECORD_S:.0f} s)")
    p.add_argument("--fps", type=float, default=10.0,
                   help=f"target frame rate for record (max {MAX_RECORD_FPS:.0f})")
    p.set_defaults(func=cmd)
