"""iCamera (CCJT, USB ae86:0001) still capture through the vendor libiCamera SDK.

The camera is a 3x3-mosaic multispectral sensor (624-776 nm), not a UVC device, so frames come
from the vendor library (``libiCamera.so`` + ``libgraph.so``). Capture runs in a child process
because the current SDK aborts inside ``FreeiCamera()`` (libusb assertion) after the frame has
been saved; the parent keeps the saved frame and ignores that crash.

Only one program may use the camera: icamera.service and ConsumerMosaicDemo must not run.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import config
from .common import ToolError, Unavailable, run

USB_ID = "ae86:0001"
SERVICE = "icamera.service"
DEMO_PATTERN = r"(^|/)ConsumerMosaicDemo(\.sh)?([[:space:]]|$)"
LIBUSB = "/lib/x86_64-linux-gnu/libusb-1.0.so.0"
WARMUP_S = 1.0  # let exposure settle before keeping a frame (as in the vendor test)
ELF_MACHINE = {0x3E: "x86_64", 0xB7: "aarch64"}


def _elf_arch(path: Path) -> str:
    with path.open("rb") as f:
        head = f.read(20)
    if head[:4] != b"\x7fELF":
        return "not an ELF library"
    return ELF_MACHINE.get(int.from_bytes(head[18:20], "little"), "unknown")


def usb_node() -> str | None:
    """/dev/bus/usb/BBB/DDD of the camera, or None when it is not connected."""
    code, out = run(["lsusb", "-d", USB_ID], timeout=5)
    m = re.search(r"Bus (\d{3}) Device (\d{3})", out) if code == 0 else None
    return f"/dev/bus/usb/{m.group(1)}/{m.group(2)}" if m else None


def busy_reason() -> str | None:
    """Why the camera is held by another program, or None."""
    code, out = run(["systemctl", "is-active", SERVICE], timeout=5)
    if out.strip() == "active":
        return f"{SERVICE} is running and holds the camera"
    code, out = run(["pgrep", "-af", DEMO_PATTERN], timeout=5)
    if code == 0 and out.strip():
        return f"ConsumerMosaicDemo is running and holds the camera ({out.strip().splitlines()[0]})"
    return None


def _check_sdk(sdk_dir: Path) -> None:
    host = os.uname().machine
    for name in ("libiCamera.so", "libgraph.so"):
        lib = sdk_dir / name
        if not lib.is_file():
            raise Unavailable(f"{lib} not found; set the icamera source in robot.yaml to the "
                              "directory with the x86_64 SDK libraries (~/icamera_demo)")
        arch = _elf_arch(lib)
        if arch != host:
            raise Unavailable(f"{lib} is built for {arch}, this computer is {host} "
                              "(~/icamera_sdk holds ARM64 libraries; use ~/icamera_demo)")
    if not Path(LIBUSB).exists():
        raise Unavailable(f"{LIBUSB} not found (install libusb-1.0-0)")


def _loader(sdk_dir: Path) -> Path:
    """Shared object that loads the two mutually dependent vendor libraries plus libusb."""
    out = config.artifacts("run") / "icamera_loader.so"
    libs = [sdk_dir / "libiCamera.so", sdk_dir / "libgraph.so"]
    if out.exists() and all(out.stat().st_mtime >= lib.stat().st_mtime for lib in libs):
        return out
    cmd = ["gcc", "-shared", "-x", "c", "/dev/null", "-x", "none", "-o", str(out),
           "-Wl,--no-as-needed", f"-Wl,-rpath,{sdk_dir}", *map(str, libs), LIBUSB]
    code, text = run(cmd, timeout=60)
    if code != 0:
        raise ToolError(f"could not build the iCamera SDK loader: {text.strip()[-400:]}")
    return out


def capture(sdk_dir: str, timeout: float):
    """Capture one colour frame (BGR) from the iCamera; returns (frame, note)."""
    import cv2

    sdk = Path(sdk_dir).expanduser()
    _check_sdk(sdk)
    node = usb_node()
    if node is None:
        raise Unavailable(f"iCamera (USB {USB_ID}) not detected; check its USB cable and power")
    reason = busy_reason()
    if reason:
        raise Unavailable(f"{reason}. Stop it first (needs operator approval) or use another "
                          "camera; only one program can use the iCamera.")
    if not os.access(node, os.R_OK | os.W_OK):
        user = os.environ.get("USER", "unitree")
        raise Unavailable(f"no read/write permission on {node}. The operator can grant it for "
                          f"this device only with: sudo setfacl -m u:{user}:rw {node}")
    loader = _loader(sdk)
    out = config.artifacts("run") / f"icamera_{os.getpid()}.png"
    out.unlink(missing_ok=True)

    def no_core_dump():
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    env = {**os.environ, "PYTHONPATH": str(config.PROJECT_DIR)}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "robot_tools.icamera", str(sdk), str(loader), str(out),
             str(WARMUP_S), str(timeout)],
            capture_output=True, text=True, timeout=WARMUP_S + timeout + 15, env=env,
            preexec_fn=no_core_dump)
    except subprocess.TimeoutExpired:
        out.unlink(missing_ok=True)
        raise Unavailable(f"the iCamera SDK did not return within {WARMUP_S + timeout + 15:.0f}s")
    m = re.search(r"^FRAME (\d+) (\d+) frames=(\d+) packet_errors=(-?\d+)$", proc.stdout, re.M)
    if not m or not out.exists():
        out.unlink(missing_ok=True)
        detail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
        raise ToolError(f"iCamera capture failed (exit {proc.returncode}): {' | '.join(detail)}")
    frame = cv2.imread(str(out), cv2.IMREAD_COLOR)
    out.unlink(missing_ok=True)
    if frame is None:
        raise ToolError("iCamera frame file could not be read")
    note = (f" multispectral false-colour view (vendor bayer2rgb24), {m.group(3)} frames "
            f"grabbed, SDK packet errors {m.group(4)}")
    if proc.returncode != 0:
        note += "; the SDK crashed while releasing the camera (known issue, frame is valid)"
    return frame, note


def _worker(sdk_dir: str, loader: str, out: str, warmup: float, timeout: float) -> int:
    """Child process: open the camera, keep one frame after ``warmup`` s, save it, release."""
    import ctypes

    import cv2
    import numpy as np

    ctypes.CDLL(loader, mode=ctypes.RTLD_GLOBAL)
    sdk = ctypes.CDLL(str(Path(sdk_dir) / "libiCamera.so"))
    sdk.bayer2rgb24.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    result = sdk.InitCameraTransfer()
    if result < 0:
        print(f"ERROR InitCameraTransfer returned {result}", flush=True)
        return 2
    try:
        width = ctypes.c_int.in_dll(sdk, "im_info_w").value
        height = ctypes.c_int.in_dll(sdk, "im_info_h").value
        bpp = ctypes.c_int.in_dll(sdk, "im_info_bpp").value
        if not (0 < width <= 4096 and 0 < height <= 4096 and bpp == 1):
            print(f"ERROR unsupported format {width}x{height} bpp={bpp}", flush=True)
            return 2
        camera = ctypes.c_void_p.in_dll(sdk, "im_pCameraBuffer")
        triple = ctypes.c_void_p.in_dll(sdk, "im_pTripleBuffer")
        rgb = np.empty((height, width, 3), dtype=np.uint8)
        start = time.monotonic()
        frames = 0
        while time.monotonic() - start < warmup + timeout:
            if sdk.iCameraGrabFrame() == 0:
                continue
            camera.value, triple.value = triple.value, camera.value
            if not triple.value:
                print("ERROR SDK returned an empty image buffer", flush=True)
                return 2
            frames += 1
            if time.monotonic() - start >= warmup:
                sdk.bayer2rgb24(rgb.ctypes.data, triple, width, height)
                tmp = out + ".tmp.png"
                if not cv2.imwrite(tmp, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)):
                    print("ERROR could not write the frame", flush=True)
                    return 2
                os.replace(tmp, out)
                errors = ctypes.c_int.in_dll(sdk, "g_pack_e").value
                print(f"FRAME {width} {height} frames={frames} packet_errors={errors}", flush=True)
                return 0
        print(f"ERROR no frame within {warmup + timeout:.0f}s ({frames} grabbed)", flush=True)
        return 2
    finally:
        sdk.FreeiCamera()  # may abort inside libusb (known SDK issue)


if __name__ == "__main__":
    sys.exit(_worker(sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]),
                     float(sys.argv[5])))
