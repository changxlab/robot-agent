"""Safety policy for agent shell commands.

Every Bash call the agent makes is classified before it runs:

* ``allow`` - read-only inspection, or stop commands (always safe to send)
* ``ask``   - actuates hardware or changes system state; an operator must approve it
* ``deny``  - never allowed from the agent (privilege escalation, bypassing the
  robot CLI's limits, destructive system commands)

The classification is conservative: anything not recognised is ``ask``.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent.parent
ROBOT_CLI = PROJECT_DIR / "robot"

ALLOW, ASK, DENY = "allow", "ask", "deny"
_RANK = {ALLOW: 0, ASK: 1, DENY: 2}


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    category: str = "read"  # read | stop | motion | system | unknown | blocked

    def worse(self, other: "Decision") -> "Decision":
        return other if _RANK[other.action] > _RANK[self.action] else self


def _merge(current: "Decision | None", new: Decision) -> Decision:
    return new if current is None else current.worse(new)


def allow(reason: str, category: str = "read") -> Decision:
    return Decision(ALLOW, reason, category)


def ask(reason: str, category: str = "system") -> Decision:
    return Decision(ASK, reason, category)


def deny(reason: str) -> Decision:
    return Decision(DENY, reason, "blocked")


# ./robot <tool> [action]: (decision, category, description)
ROBOT_ACTIONS: dict[tuple[str, str | None], tuple[str, str, str]] = {
    ("status", None): (ALLOW, "read", "Read robot health status"),
    ("logs", None): (ALLOW, "read", "Read robot logs"),
    ("camera", "list"): (ALLOW, "read", "List cameras"),
    ("camera", "capture"): (ALLOW, "read", "Capture camera images"),
    ("camera", "look"): (ALLOW, "read", "Capture and describe camera images"),
    ("camera", "record"): (ALLOW, "read", "Record a short camera clip"),
    ("camera", "devices"): (ALLOW, "read", "List V4L2 capture devices"),
    ("camera", "set-source"): (ASK, "system", "Change which device or topic a camera uses"),
    ("arm", "status"): (ALLOW, "read", "Read arm status"),
    ("arm", "stop"): (ALLOW, "stop", "Emergency-stop the arm"),
    ("arm", "enable"): (ASK, "motion", "Enable (power) arm motors"),
    ("arm", "take-control"): (ASK, "motion", "Switch the arm to CAN command mode - outside it the "
                                             "arm is emergency-stopped and sinks to rest first"),
    ("arm", "disable"): (ASK, "motion", "Disable arm motors - the arm will drop if unsupported"),
    ("arm", "move-joints"): (ASK, "motion", "Move the arm"),
    ("arm", "home"): (ASK, "motion", "Move the arm to its home pose"),
    ("arm", "gripper"): (ASK, "motion", "Open/close the gripper"),
    ("arm", "resume"): (ASK, "motion", "Clear the arm emergency stop"),
    ("arm", "teach-button"): (ALLOW, "read", "Simulate a press of the arm's teach button "
                                             "(SIM only; refused on the real arm)"),
    ("traj", "list"): (ALLOW, "read", "List recorded arm trajectories"),
    ("traj", "show"): (ALLOW, "read", "Show a recorded arm trajectory"),
    ("traj", "record"): (ASK, "motion", "Record an arm trajectory - the operator presses the "
                                        "teach button and moves the arm by hand"),
    ("traj", "play"): (ASK, "motion", "Replay a recorded arm trajectory - the arm will move"),
    ("piper", "list"): (ALLOW, "read", "List recorded arm trajectories"),
    ("piper", "show"): (ALLOW, "read", "Show a recorded arm trajectory"),
    ("piper", "record"): (ASK, "motion", "Record an arm trajectory with the Gradio recorder - the "
                                         "operator presses the teach button and moves the arm by "
                                         "hand"),
    ("piper", "play"): (ASK, "motion", "Replay a recorded arm trajectory with the Gradio player - "
                                       "the arm will move"),
    ("survey", "check"): (ALLOW, "read", "Check plant survey readiness (motion, arm, camera)"),
    ("survey", "run"): (ASK, "motion", "Plant survey - the arm replays the survey motion while "
                                       "the survey camera records a video"),
    ("base", "state"): (ALLOW, "read", "Read quadruped state"),
    ("base", "stop"): (ALLOW, "stop", "Stop quadruped motion"),
    ("base", "stand-up"): (ASK, "motion", "Make the quadruped stand up"),
    ("base", "stand-down"): (ASK, "motion", "Make the quadruped lie down"),
    ("base", "balance-stand"): (ASK, "motion", "Switch the quadruped to balance stand"),
    ("base", "recovery-stand"): (ASK, "motion", "Recovery stand - rolls the body over; can damage "
                                                "the arm and devices mounted on the B2"),
    ("base", "move"): (ASK, "motion", "Walk the quadruped"),
    ("base", "damp"): (ASK, "motion", "Damp all quadruped joints - the robot will collapse"),
    ("map", "status"): (ALLOW, "read", "Read mapping status"),
    ("map", "list"): (ALLOW, "read", "List saved maps"),
    ("map", "scan"): (ALLOW, "read", "Save a lidar point cloud snapshot"),
    ("map", "save"): (ALLOW, "read", "Save the current map"),
    ("map", "stop"): (ALLOW, "stop", "Stop the mapping process"),
    ("map", "start"): (ASK, "system", "Start the SLAM mapping process"),
    ("weather", None): (ALLOW, "read", "Read the weather at the robot's site"),
    ("estop", None): (ALLOW, "stop", "Emergency-stop all actuators"),
}

READ_ONLY = {
    "cat", "head", "tail", "less", "grep", "egrep", "fgrep", "rg", "wc", "stat", "file", "du",
    "df", "free", "uptime", "uname", "hostname", "date", "whoami", "id", "ps", "pgrep", "lsusb",
    "lsblk", "lscpu", "lspci", "lsmod", "ls", "tree", "pwd", "echo", "printf", "sort", "uniq",
    "cut", "tr", "column", "jq", "which", "type", "true", "sensors", "journalctl", "dmesg", "ss",
    "netstat", "nproc", "basename", "dirname", "realpath", "readlink", "md5sum", "sha256sum",
    "diff", "cd", "sleep", "test", "[", "tegrastats", "iwconfig", "top", "vmstat", "iostat",
}
ROS2_READ = {
    ("topic", "list"), ("topic", "info"), ("topic", "echo"), ("topic", "hz"), ("topic", "bw"),
    ("topic", "type"), ("topic", "find"), ("topic", "delay"), ("node", "list"), ("node", "info"),
    ("service", "list"), ("service", "type"), ("service", "find"), ("action", "list"),
    ("action", "info"), ("param", "list"), ("param", "get"), ("param", "dump"),
    ("param", "describe"), ("interface", "list"), ("interface", "show"),
    ("interface", "package"), ("interface", "packages"), ("interface", "proto"), ("pkg", "list"),
    ("pkg", "prefix"), ("pkg", "executables"), ("pkg", "xml"), ("doctor", None), ("wtf", None),
    ("bag", "info"), ("daemon", "status"), ("lifecycle", "get"), ("lifecycle", "nodes"),
    ("lifecycle", "list"), ("component", "list"), ("control", "list_controllers"),
    ("control", "list_hardware_interfaces"),
}
WRAPPERS = {"timeout", "nice", "stdbuf", "time", "nohup"}
SEPARATORS = {";", "&&", "||", "|", "&", "|&", ";;", "(", ")"}
DENY_PROGRAMS = {
    "sudo": "Privilege escalation is not allowed from the agent.",
    "su": "Privilege escalation is not allowed from the agent.",
    "doas": "Privilege escalation is not allowed from the agent.",
    "pkexec": "Privilege escalation is not allowed from the agent.",
    "reboot": "Rebooting the robot computer is not allowed from the agent.",
    "shutdown": "Shutting down the robot computer is not allowed from the agent.",
    "poweroff": "Powering off the robot computer is not allowed from the agent.",
    "halt": "Halting the robot computer is not allowed from the agent.",
    "mkfs": "Formatting disks is not allowed.",
    "dd": "Raw disk writes are not allowed.",
    "cansend": "Raw CAN frames bypass the arm safety limits; use `./robot arm ...` instead.",
    "cangen": "Raw CAN traffic bypasses the arm safety limits; use `./robot arm ...` instead.",
}
# Topics that move the quadruped directly (B2 sport API, low-level, Nav2/teleop velocity),
# matched on the last name segment so namespaced variants (/robot1/cmd_vel) are covered too.
MOTION_TOPIC_NAME = re.compile(r"cmd_vel\w*|keyboard_ctl|lowcmd|wirelesscontroller")
MOTION_API = re.compile(r"(^|/)api/(sport|loco|motion_switcher)/request$")
# Packages whose launch files start localization, navigation, inspection or survey runs.
AUTONOMY_PACKAGES = {"infai_bringup", "infai_navigation2", "infai_slam", "dog_inspection",
                     "dog_survey"}


def _robot_cli_args(argv: list[str]) -> list[str] | None:
    """Return the robot CLI arguments if ``argv`` invokes ./robot or robot_tools."""
    prog = argv[0]
    if prog in ("./robot", "robot") or (
        prog.endswith("/robot") and Path(os.path.expanduser(prog)).resolve() == ROBOT_CLI
    ):
        return argv[1:]
    if Path(prog).name.startswith("python") and argv[1:3] == ["-m", "robot_tools"]:
        return argv[3:]
    return None


class _CliUsageError(Exception):
    pass


TOOLS_DIR = PROJECT_DIR / "robot_tools"
_parser_lock = threading.Lock()
_parser_cache: dict[str, Any] = {"fingerprint": None, "parser": None}


def _tools_fingerprint() -> tuple:
    """Changes whenever a robot_tools source file is added, removed or edited."""
    try:
        return tuple(sorted((p.name, p.stat().st_mtime_ns) for p in TOOLS_DIR.glob("*.py")))
    except OSError:
        return ()


def _is_tools_module(name: str) -> bool:
    return name == "robot_tools" or name.startswith("robot_tools.")


def _fresh_build_parser() -> argparse.ArgumentParser:
    """Build the parser from the robot_tools code on disk now, not from modules this process
    imported earlier, and leave those modules (used elsewhere in the server) untouched."""
    saved = {n: m for n, m in sys.modules.items() if _is_tools_module(n)}
    for name in saved:
        del sys.modules[name]
    try:
        if str(PROJECT_DIR) not in sys.path:
            sys.path.append(str(PROJECT_DIR))
        from robot_tools.__main__ import build_parser

        return build_parser()
    finally:
        for name in [n for n in sys.modules if _is_tools_module(n)]:
            del sys.modules[name]
        sys.modules.update(saved)


def _cli_parser() -> argparse.ArgumentParser | None:
    """The ./robot argument parser, raising instead of exiting on bad arguments.

    Rebuilt when the robot_tools sources change, so a long-running server accepts commands
    added after it started.
    """
    fingerprint = _tools_fingerprint()
    with _parser_lock:
        if _parser_cache["fingerprint"] == fingerprint:
            return _parser_cache["parser"]
        parser = _build_cli_parser()
        _parser_cache.update(fingerprint=fingerprint, parser=parser)
        return parser


def _build_cli_parser() -> argparse.ArgumentParser | None:
    try:
        parser = _fresh_build_parser()
    except Exception:  # the robot tools cannot be imported here; use the plain heuristic
        return None

    def error(message: str):
        raise _CliUsageError(message)

    parsers = [parser]
    while parsers:
        p = parsers.pop()
        p.error = error  # type: ignore[method-assign]
        for action in p._actions:
            if isinstance(action, argparse._SubParsersAction):
                parsers.extend(action.choices.values())
    return parser


def _invalid(tool: str, args: list[str], detail: str = "") -> Decision:
    # Invalid arguments can only fail argument parsing; reject them without bothering the
    # operator and point the agent at the correct syntax.
    hint = f"./robot {tool} --help" if any(k[0] == tool for k in ROBOT_ACTIONS) \
        else "./robot --help"
    detail = f" ({detail})" if detail else ""
    return deny(f"`./robot {' '.join(args)}` is not a valid robot command{detail}. "
                f"Load the matching skill or run `{hint}` for the exact syntax.")


def classify_robot(args: list[str]) -> Decision:
    positional = [a for a in args if not a.startswith("-")]
    if not positional or positional[0] in ("-h", "--help", "help"):
        return allow("Show robot CLI help")
    if "-h" in args or "--help" in args:
        return allow("Show robot CLI help")
    parser = _cli_parser()
    if parser is None:
        # Without the CLI parser, guess: options never come before the subcommand.
        tool = positional[0]
        action = positional[1] if len(positional) > 1 else None
        entry = ROBOT_ACTIONS.get((tool, action)) or ROBOT_ACTIONS.get((tool, None))
        if entry is None:
            return _invalid(tool, args)
    else:
        # Parse exactly like the CLI, so option values ("--camera b2_front") and options
        # placed before the action are never mistaken for the subcommand.
        try:
            ns = parser.parse_args(args)
        except _CliUsageError as exc:
            return _invalid(positional[0], args, str(exc))
        tool, action = ns.tool, getattr(ns, "action", None)
        entry = ROBOT_ACTIONS.get((tool, action)) or ROBOT_ACTIONS.get((tool, None))
        if entry is None:
            # A valid command the safety table does not know yet (e.g. a newly added action).
            name = f"{tool} {action}" if action else tool
            return ask(f"`./robot {name}` is not in the safety table; review it.", "unknown")
    decision, category, text = entry
    if (tool, action) == ("base", "recovery-stand") and not _recovery_stand_allowed():
        return deny("`./robot base recovery-stand` is disabled: the recovery motion can crush the "
                    "arm, cameras and other devices mounted on the B2. Tell the operator the robot "
                    "needs a manual recovery (secure the payload, then use the B2 remote or lift "
                    "it by hand); do not try other commands to get it up.")
    return Decision(decision, text, category)


def _recovery_stand_allowed() -> bool:
    """robot.yaml base.allow_recovery_stand, read fresh so an edit applies without a restart."""
    try:
        from robot_tools import config as robot_config

        robot_config.load.cache_clear()
        return bool(robot_config.load()["base"].get("allow_recovery_stand", False))
    except Exception:  # unreadable config: keep the dangerous command blocked
        return False


def _is_motion_topic(arg: str) -> bool:
    return bool(MOTION_TOPIC_NAME.fullmatch(arg.rstrip("/").rsplit("/", 1)[-1])
                or MOTION_API.search(arg.rstrip("/")))


def classify_ros2(args: list[str]) -> Decision:
    positional = [a for a in args if not a.startswith("-")]
    if not positional:
        return allow("ROS 2 CLI help")
    verb = positional[0]
    sub = positional[1] if len(positional) > 1 else None
    if verb in ("topic", "service", "action") and sub in ("pub", "call", "send_goal") and \
            any(_is_motion_topic(a) for a in positional[2:]):
        return deny("Commands that move the quadruped must go through `./robot base ...`, which "
                    "enforces speed and duration limits and stops afterwards.")
    if (verb, sub) in ROS2_READ or (verb, None) in ROS2_READ:
        if verb == "topic" and sub == "echo" and "--once" not in args and "--times" not in args:
            return ask("Unbounded `ros2 topic echo` never exits; add --once.", "unknown")
        return allow(f"Read ROS 2 graph: ros2 {verb} {sub or ''}".strip())
    if verb in ("launch", "run"):
        if sub in AUTONOMY_PACKAGES:
            return ask(f"Starts {sub} (localization/navigation/inspection/survey), which can drive "
                       "the robot. Confirm the area is clear and no other instance or service of "
                       "it is already running.", "motion")
        return ask(f"Start ROS 2 processes: ros2 {verb} {' '.join(positional[1:3])}", "system")
    if verb == "bag" and sub == "play":
        return ask("Replays recorded topics onto the live robot; a bag containing /cmd_vel* or "
                   "arm topics would move hardware.", "motion")
    if verb == "service" and sub == "call" and any("inspection" in a or "survey" in a
                                                    for a in positional[2:4]):
        return ask("Service call to the inspection/survey system, which can start or stop an "
                   "autonomous run.", "motion")
    return ask(f"ROS 2 command changes robot state: ros2 {verb} {sub or ''}".strip(), "system")


def _strip_wrappers(argv: list[str]) -> list[str]:
    while argv:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argv[0]):
            argv = argv[1:]
            continue
        if argv[0] in WRAPPERS:
            argv = argv[1:]
            while argv and (argv[0].startswith("-") or re.fullmatch(r"[\d.]+[smhd]?", argv[0])):
                argv = argv[1:]
            continue
        break
    return argv


def classify_simple(argv: list[str]) -> Decision:
    argv = _strip_wrappers(argv)
    if not argv:
        return allow("No-op")
    robot_args = _robot_cli_args(argv)
    if robot_args is not None:
        return classify_robot(robot_args)

    prog = Path(argv[0]).name
    args = argv[1:]
    if prog in DENY_PROGRAMS or prog.startswith("mkfs."):
        return deny(DENY_PROGRAMS.get(prog, "Formatting disks is not allowed."))
    if prog in ("source", "."):
        target = args[0] if args else ""
        if target.endswith((".bash", ".sh")) and "setup" in Path(target).name:
            return allow("Source a ROS setup file")
        return ask(f"Source {target}", "unknown")
    if prog == "ros2":
        return classify_ros2(args)
    if prog == "rm" and any(a.startswith("-") and ("r" in a or "R" in a) for a in args):
        if any(a in ("/", "~", "/*", "~/", os.path.expanduser("~")) for a in args):
            return deny("Recursive deletion of / or the home directory is not allowed.")
        return ask("Recursive delete", "system")
    if prog in ("systemctl", "service"):
        if args and args[0] in ("status", "is-active", "is-failed", "list-units", "show", "cat"):
            return allow("Read service status")
        if any(a in ("poweroff", "reboot", "halt", "kexec", "suspend") for a in args):
            return deny("Power state changes are not allowed from the agent.")
        return ask("Change a system service", "system")
    if prog in ("ip", "ifconfig"):
        if not args or any(a in ("set", "add", "del", "delete", "flush", "up", "down", "change",
                                 "replace") for a in args):
            if args:
                return ask("Change network/CAN interface configuration", "system")
        return allow("Read network interfaces")
    if prog == "find":
        if any(a in ("-exec", "-execdir", "-delete", "-ok", "-okdir", "-fprint") for a in args):
            return ask("find with side effects", "system")
        return allow("Search files")
    if prog == "nvidia-smi":
        if any(a.startswith(("-r", "--gpu-reset", "-pl", "--power-limit", "-pm", "-c", "-lgc",
                             "-rgc", "-ac", "-rac")) for a in args):
            return ask("Change GPU settings", "system")
        return allow("Read GPU status")
    if prog == "v4l2-ctl":
        if any(a.startswith(("--set", "-c", "--stream")) for a in args):
            return ask("Change camera settings", "system")
        return allow("Read camera devices")
    if prog == "candump":
        if "-n" in args or any(a.startswith("-n") for a in args):
            return allow("Read CAN frames")
        return ask("Unbounded candump never exits; add -n <count>.", "unknown")
    if prog == "ping":
        if "-c" in args or any(a.startswith("-c") for a in args):
            return allow("Network reachability check")
        return ask("Unbounded ping never exits; add -c <count>.", "unknown")
    if prog in ("env", "printenv", "export", "set"):
        return ask("Printing the environment can expose credentials", "unknown")
    if prog == "top" and not any(a.startswith("-") and "b" in a for a in args):
        return ask("Interactive top never exits; use `top -bn1`.", "unknown")
    if prog in READ_ONLY:
        return allow(f"Read-only command: {prog}")
    if prog in ("kill", "pkill", "killall"):
        return ask("Stop running processes", "system")
    return ask(f"Command not on the read-only list: {prog}", "unknown")


def _tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def classify(command: str) -> Decision:
    """Classify a shell command for the agent's Bash tool."""
    if not command.strip():
        return allow("Empty command")
    if "`" in command or "$(" in command or "<(" in command or ">(" in command:
        return ask("Command substitution hides what will run; review it.", "unknown")
    if "<<" in command:
        return ask("Here-documents can hide what will run; review it.", "unknown")
    try:
        tokens = _tokens(command)
    except ValueError as exc:
        return ask(f"Could not parse command ({exc}); review it.", "unknown")

    result: Decision | None = None
    segment: list[str] = []
    i = 0

    def flush() -> None:
        nonlocal result, segment
        if segment:
            inner = segment[0]
            if Path(inner).name in ("bash", "sh", "zsh", "eval", "exec", "xargs", "python",
                                    "python3", "perl", "ruby", "node") and \
                    _robot_cli_args(segment) is None:
                result = _merge(result, ask(f"`{inner}` can run arbitrary code; review it.",
                                            "unknown"))
            else:
                result = _merge(result, classify_simple(segment))
        segment = []

    while i < len(tokens):
        tok = tokens[i]
        if tok in SEPARATORS:
            flush()
        elif set(tok) <= set("<>&") and ">" in tok:
            target = tokens[i + 1] if i + 1 < len(tokens) else ""
            i += 1
            if target.isdigit() or target in ("/dev/null", "-"):
                pass
            elif target.startswith("/dev/") or target.startswith("/etc/") or \
                    target.startswith("/sys/") or target.startswith("/proc/"):
                result = _merge(result, deny(f"Writing to {target} is not allowed."))
            else:
                result = _merge(result, ask(f"Writes to file {target}", "system"))
        elif tok == "<":
            i += 1
        else:
            # "2>&1" tokenizes as "2", ">&", "1"; drop a trailing fd number before redirection.
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
            if not (tok.isdigit() and set(nxt) <= set("<>&") and nxt):
                segment.append(tok)
        i += 1
    flush()
    return result or allow("Empty command")
