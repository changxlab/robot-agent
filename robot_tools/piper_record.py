"""Piper arm trajectory recorder: the recording logic of AgiLex's Gradio ``record.py``.

Ported from ``Agilex-College/piper/recordAndPlayTraj/record.py`` without its Gradio UI and
terminal flow; `./robot piper record` (``piper_gradio.py``) drives it. The recording behaves as
in the original: wait for teach mode, poll the joints (and gripper) in a thread, write a row only
when the pose changes, and keep a timestamped session copy of the CSV.

CSV row: wait_s, j1_rad, j2_rad, j3_rad, j4_rad, j5_rad, j6_rad[, gripper_m]
"""

from __future__ import annotations

import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

Log = Callable[[str, str], None]

# piper_sdk units: joint angles in 0.001 deg, gripper opening in 0.001 mm. AgiLex's rounded
# degree-to-radian factor is kept so recordings match record.py exactly.
RAD_PER_DEG = 0.0174533
MDEG_PER_DEG = 1e3
UM_PER_M = 1e6
CTRL_MODE_TEACH = 0x02
TEACH_POLL_S = 0.02


def print_log(status: str, message: str) -> None:
    print(f"{status}: {message}")


def connect(port: str) -> Any:
    """A connected ``piper_sdk.C_PiperInterface_V2`` (imported here: optional dependency)."""
    from piper_sdk import C_PiperInterface_V2

    piper = C_PiperInterface_V2(port)
    piper.ConnectPort()
    time.sleep(0.1)
    return piper


def read_pose(piper: Any, have_gripper: bool) -> tuple[float, ...]:
    """Joints in rad, plus the gripper opening in m when ``have_gripper``."""
    joint_state = piper.GetArmJointMsgs().joint_state
    joints = tuple(getattr(joint_state, f"joint_{i + 1}") / MDEG_PER_DEG * RAD_PER_DEG
                   for i in range(6))
    if have_gripper:
        return joints + (piper.GetArmGripperMsgs().gripper_state.grippers_angle / UM_PER_M,)
    return joints


class Recorder:
    """Threaded recorder of joint (and gripper) changes into a CSV file."""

    def __init__(self, piper: Any, sessions_dir: Path, log: Log = print_log):
        self.piper = piper
        self.sessions_dir = sessions_dir
        self.log = log
        self.thread: threading.Thread | None = None
        self.stop_flag = False
        self.active = False
        self.points = 0
        self.last_change_time: float | None = None
        self.last_session_path: str | None = None

    def wait_teaching_mode(self, timeout_s: float) -> bool:
        deadline = time.time() + timeout_s
        self.log("info", "Waiting for teaching mode (ctrl_mode==2)")
        while self.piper.GetArmStatus().arm_status.ctrl_mode != CTRL_MODE_TEACH:
            if time.time() > deadline:
                self.log("error", "Teaching mode detection timeout")
                return False
            time.sleep(TEACH_POLL_S)
        self.log("success", "Teaching mode active")
        return True

    def start(self, csv_path: str, have_gripper: bool, duration_s: float,
              poll_interval: float) -> None:
        """Record in a background thread for ``duration_s`` s (0 = until ``stop``)."""
        if self.active:
            self.log("error", "Recording already in progress")
            return
        self.stop_flag = False
        self.thread = threading.Thread(
            target=self._record_loop, args=(csv_path, have_gripper, duration_s, poll_interval),
            daemon=True)
        self.thread.start()
        self.log("info", "Recording thread started "
                         f"(duration={'infinite' if duration_s == 0 else duration_s}s)")

    def stop(self) -> None:
        if not self.active:
            self.log("warning", "No active recording to stop")
            return
        self.stop_flag = True
        self.log("info", "Stop flag set; waiting thread to finish")

    def _record_loop(self, csv_path: str, have_gripper: bool, max_duration: float,
                     poll_interval: float) -> None:
        self.active = True
        self.points = 0
        self.last_change_time = start_time = time.time()
        end_time = start_time + max_duration if max_duration > 0 else None
        try:
            with open(csv_path, "w", encoding="utf-8") as f:
                last_pos = read_pose(self.piper, have_gripper)
                self.log("info", f"Initial position captured: {last_pos}")
                while not self.stop_flag and (end_time is None or time.time() < end_time):
                    current_pos = read_pose(self.piper, have_gripper)
                    if current_pos != last_pos:
                        now = time.time()
                        wait_time = now - self.last_change_time
                        f.write(f"{wait_time}," + ",".join(map(str, current_pos)) + "\n")
                        f.flush()
                        self.points += 1
                        self.last_change_time = now
                        last_pos = current_pos
                        self.log("info", f"Point {self.points} wait={wait_time:0.4f}s "
                                         f"pos={current_pos}")
                    time.sleep(max(poll_interval, 0.001))
            if self.stop_flag:
                self.log("warning", "Recording stopped by user")
            else:
                self.log("success", "Recording duration completed")
        except Exception as exc:
            self.log("error", f"Recording failed: {exc}")
        finally:
            self.active = False
            self.stop_flag = False
            self.log("info", f"Recording finished. Total points: {self.points}")
            self._copy_to_session_file(csv_path)

    def _copy_to_session_file(self, csv_path: str) -> str | None:
        """Keep a timestamped copy ``<stem>_<YYYYmmddHHMM>.csv`` in ``sessions_dir``."""
        try:
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            src = Path(csv_path)
            if not src.exists():
                self.log("warning", f"Source file missing for session copy: {csv_path}")
                return None
            timestamp = datetime.now().strftime("%Y%m%d%H%M")
            dest = self.sessions_dir / f"{src.stem}_{timestamp}{src.suffix or '.csv'}"
            shutil.copy2(src, dest)
            self.last_session_path = str(dest)
            self.log("success", f"Session file saved: {dest}")
            return str(dest)
        except Exception as exc:
            self.log("error", f"Failed to copy session file: {exc}")
            return None
