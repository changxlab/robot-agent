#!/usr/bin/env bash
# Install the robot agent as native systemd services on the robot computer (PC4).
#
# Run from the project checkout as the user that owns it and runs the robot (not root); sudo is
# used for the system steps:
#   ./deploy/install.sh
# Options (environment variables):
#   WITH_LITELLM=0           do not install litellm.service (gateway runs elsewhere; then set
#                            CC_BASE_URL in /etc/robot-agent/robot-agent.env)
#   LITELLM_BIN=/path/litellm use this litellm instead of the one on PATH / a new .venv-litellm
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="$(id -un)"
WITH_LITELLM="${WITH_LITELLM:-1}"
ENV_DIR=/etc/robot-agent
ENV_FILE="$ENV_DIR/robot-agent.env"
UNIT_DIR=/etc/systemd/system

if [ "$(id -u)" -eq 0 ]; then
  echo "error: run as the robot user, not root (sudo is used where needed)" >&2
  exit 1
fi
cd "$APP_DIR"
echo "==> Installing robot agent from $APP_DIR for user $RUN_USER"

# 1. Python environment. System site packages keep ROS 2 (rclpy) and an existing piper_sdk
#    visible; numpy/OpenCV stay on the numpy 1.x ABI that ROS 2 Humble's packages are built for.
echo "==> Python environment (.venv)"
/usr/bin/python3 -m venv --system-site-packages .venv
constraints="$(mktemp)"
trap 'rm -f "$constraints"' EXIT
printf 'numpy<2\nopencv-python-headless<4.11\n' > "$constraints"
.venv/bin/python -m pip install --quiet --upgrade pip
PIP_CONSTRAINT="$constraints" .venv/bin/python -m pip install --quiet \
  --config-settings editable_mode=compat -e ".[robot]"

# 2. LiteLLM gateway
render() {  # render <template> <destination>
  sed -e "s#@APP_DIR@#$APP_DIR#g" -e "s#@USER@#$RUN_USER#g" -e "s#@LITELLM_BIN@#${LITELLM_BIN:-}#g" \
    "$1" | sudo tee "$2" >/dev/null
}
if [ "$WITH_LITELLM" = "1" ]; then
  if [ -z "${LITELLM_BIN:-}" ]; then
    LITELLM_BIN="$(command -v litellm || true)"
  fi
  if [ -z "$LITELLM_BIN" ]; then
    echo "==> LiteLLM not found; installing into .venv-litellm"
    /usr/bin/python3 -m venv .venv-litellm
    .venv-litellm/bin/python -m pip install --quiet --upgrade pip 'litellm[proxy]'
    LITELLM_BIN="$APP_DIR/.venv-litellm/bin/litellm"
  fi
  [ -f config.yaml ] || { echo "error: config.yaml (LiteLLM config) missing in $APP_DIR" >&2; exit 1; }
  echo "==> litellm.service ($LITELLM_BIN)"
  render deploy/litellm.service "$UNIT_DIR/litellm.service"
fi

# 3. Access to cameras/USB/serial and the system journal (`./robot camera`, `./robot logs`).
for group in video dialout plugdev systemd-journal; do
  if getent group "$group" >/dev/null && ! id -nG "$RUN_USER" | grep -qw "$group"; then
    echo "==> adding $RUN_USER to group $group"
    sudo usermod -aG "$group" "$RUN_USER"
  fi
done

# 4. Settings file with a random UI access token (kept on reinstall).
if ! sudo test -f "$ENV_FILE"; then
  echo "==> creating $ENV_FILE"
  token="$(/usr/bin/python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  sudo install -d -m 755 "$ENV_DIR"
  sed -e "s#@TOKEN@#$token#" deploy/robot-agent.env.example | sudo tee "$ENV_FILE" >/dev/null
  sudo chown "root:$(id -gn)" "$ENV_FILE"
  sudo chmod 640 "$ENV_FILE"
fi

# 5. Agent service
echo "==> robot-agent.service"
mkdir -p artifacts .claude/sessions
render deploy/robot-agent.service "$UNIT_DIR/robot-agent.service"
sudo systemctl daemon-reload
if [ "$WITH_LITELLM" = "1" ]; then
  sudo systemctl enable litellm.service
  sudo systemctl restart litellm.service
fi
sudo systemctl enable robot-agent.service
sudo systemctl restart robot-agent.service

# 6. Verify
port="$(sudo sed -n 's/^PORT=//p' "$ENV_FILE" | tail -1)"
port="${port:-8000}"
for _ in $(seq 1 20); do
  if curl -fsS -o /dev/null "http://127.0.0.1:$port/"; then
    echo "==> robot-agent is up: http://$(hostname -I | awk '{print $1}'):$port/?token=<ROBOT_AGENT_TOKEN in $ENV_FILE>"
    exit 0
  fi
  sleep 1
done
echo "error: robot-agent did not answer on port $port; see: journalctl -u robot-agent -n 50" >&2
exit 1
