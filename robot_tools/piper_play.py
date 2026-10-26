"""Piper arm trajectory player: the replay logic of AgiLex's Gradio ``play.py``.

Ported from ``Agilex-College/piper/recordAndPlayTraj/play.py`` without its Gradio UI;
`./robot piper play` (``piper_gradio.py``) drives it. The replay behaves as in the original:
outside CAN command mode the arm is emergency-stopped until joints 2, 3 and 5 settle at rest,
then switched to CAN mode and enabled; each point is sent with ``JointCtrl`` (and
``GripperCtrl``) and held for its recorded wait divided by the speed multiplier.

CSV row: wait_s, j1_rad, j2_rad, j3_rad, j4_rad, j5_rad, j6_rad[, gripper_m]
"""

from __future__ import annotations

import csv
import os
import time
from typing import Any

from .piper_record import MDEG_PER_DEG, RAD_PER_DEG, UM_PER_M, Log, print_log, read_pose

CTRL_MODE_CAN = 0x01
ESTOP = 0x01
ESTOP_RESUME = 0x02
# Rest pose before the emergency stop is cleared (rad): |J2|, |J3| < ~10 deg, J5 ~12..45 deg.
REST_J23_MAX_RAD = 0.1745
REST_J5_RANGE_RAD = (0.2094, 0.7854)
GRIPPER_EFFORT = 1000  # 0.001 N/m
SLICE_S = 0.01  # waits are sliced so a stop request is seen quickly


class Player:
    """Replays a recorded trajectory CSV on the arm."""

    def __init__(self, piper: Any, log: Log = print_log):
        self.piper = piper
        self.log = log
        self.track: list[list[float]] = []
        self.stop_flag = False
        self.ready = False

    def stop(self) -> None:
        self.stop_flag = True

    def load_track(self, path: str) -> bool:
        try:
            with open(path, encoding="utf-8") as f:
                rows = list(csv.reader(f))
            if not rows:
                self.log("error", "Trajectory file empty")
                return False
            self.track = [[float(c) for c in r] for r in rows]
            self.log("success", f"Loaded trajectory file '{os.path.basename(path)}' with "
                                f"{len(self.track)} points")
            return True
        except FileNotFoundError:
            self.log("error", f"Trajectory file not found: {path}")
            return False
        except Exception as exc:
            self.log("error", f"Failed to load trajectory: {exc}")
            return False

    def init_arm(self, timeout: float, move_spd_rate_ctrl: int, have_gripper: bool) -> bool:
        """Bring the arm into CAN command mode and enable it; False on a mode-switch timeout."""
        p = self.piper
        self.log("info", "Initializing arm for replay (ensure teaching mode exited)")
        if p.GetArmStatus().arm_status.ctrl_mode != CTRL_MODE_CAN:
            self._stop_arm(have_gripper)
        deadline = time.time() + timeout
        while p.GetArmStatus().arm_status.ctrl_mode != CTRL_MODE_CAN:
            if time.time() > deadline:
                self.log("error", "CAN mode switch timeout")
                return False
            p.ModeCtrl(0x01, 0x01, move_spd_rate_ctrl, 0x00)
            time.sleep(SLICE_S)
        self._enable_arm(move_spd_rate_ctrl, have_gripper)
        self.ready = True
        self.log("success", "Arm ready for trajectory replay")
        return True

    def play(self, play_times: int, play_interval: float, move_spd_rate_ctrl: int,
             play_speed: float, have_gripper: bool) -> None:
        """Replay ``play_times`` loops (0 = until ``stop``); ``play_interval`` s after each."""
        if not self.ready:
            self.log("error", "Arm not initialized")
            return
        if not self.track:
            self.log("error", "No trajectory loaded")
            return
        self.stop_flag = False
        loops = "infinite" if play_times == 0 else play_times
        self.log("info", f"Starting replay: loops={loops}, points={len(self.track)}")
        cycle = 0
        while play_times == 0 or cycle < play_times:
            cycle += 1
            for idx, row in enumerate(self.track):
                if self.stop_flag:
                    self.log("warning", "Replay stopped by user")
                    return
                wait_time = row[0] / max(play_speed, 1e-6)
                with_gripper = have_gripper and len(row) == 8
                joints_rad = row[1:-1] if with_gripper else row[1:]
                joints_cmd = [round(r / RAD_PER_DEG * MDEG_PER_DEG) for r in joints_rad[:6]]
                self.piper.MotionCtrl_2(0x01, 0x01, move_spd_rate_ctrl, 0x00)
                self.piper.JointCtrl(*joints_cmd)
                if with_gripper:
                    self.piper.GripperCtrl(round(row[-1] * UM_PER_M), GRIPPER_EFFORT, 0x01, 0x00)
                self.log("info", f"Cycle {cycle} point {idx + 1}/{len(self.track)} "
                                 f"wait={wait_time:0.3f}s")
                last = idx == len(self.track) - 1
                if not self._sleep(play_interval if last else wait_time):
                    self.log("warning", "Replay stopped during wait")
                    return
        self.log("success", "Replay completed")

    def _sleep(self, seconds: float) -> bool:
        """Sleep in slices; False as soon as a stop is requested."""
        end = time.time() + seconds
        while time.time() < end:
            if self.stop_flag:
                return False
            time.sleep(SLICE_S)
        return True

    def _at_rest(self, have_gripper: bool) -> bool:
        pos = read_pose(self.piper, have_gripper)
        return (abs(pos[1]) < REST_J23_MAX_RAD and abs(pos[2]) < REST_J23_MAX_RAD
                and REST_J5_RANGE_RAD[0] < pos[4] < REST_J5_RANGE_RAD[1])

    def _stop_arm(self, have_gripper: bool) -> None:
        """Emergency-stop, wait until joints 2, 3 and 5 sink to rest, then clear the stop."""
        self.piper.EmergencyStop(ESTOP)
        time.sleep(1.0)
        while not self._at_rest(have_gripper):
            time.sleep(SLICE_S)
        self.piper.EmergencyStop(ESTOP_RESUME)
        time.sleep(1.0)
        self.log("info", "Arm emergency stop cycle complete")

    def _enable_arm(self, move_spd_rate_ctrl: int, have_gripper: bool) -> None:
        while not self.piper.EnablePiper():
            time.sleep(SLICE_S)
        if have_gripper:
            time.sleep(SLICE_S)
            self.piper.GripperCtrl(0, GRIPPER_EFFORT, 0x01, 0x00)
        self.piper.ModeCtrl(0x01, 0x01, move_spd_rate_ctrl, 0x00)
        self.log("info", "Arm enabled and in CAN mode")
