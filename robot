#!/usr/bin/env bash
# Entry point for all robot tools used by the agent skills.
# Sources ROS 2 and the robot workspaces, then runs `python3 -m robot_tools`.
ROBOT_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${ROBOT_PYTHON:-/usr/bin/python3}"
export PYTHONPATH="$ROBOT_HOME${PYTHONPATH:+:$PYTHONPATH}"

if ! env_exports="$("$PY" -m robot_tools.env)"; then
  echo "error: could not load robot configuration ($ROBOT_HOME/robot.yaml)" >&2
  exit 1
fi
eval "$env_exports"

# Setup scripts are not written for `set -u`, and missing overlays are skipped.
IFS=':' read -r -a _setup_files <<< "${ROBOT_ROS_SETUP_RESOLVED:-}"
for f in "${_setup_files[@]}"; do
  [ -f "$f" ] && source "$f" >/dev/null 2>&1
done
unset _setup_files f

exec "$PY" -m robot_tools "$@"
