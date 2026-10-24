# syntax=docker/dockerfile:1
#
# Robot agent web server + ./robot tools on ROS 2 Humble (Ubuntu 22.04, Python 3.10).
#
# Build (match USER_UID to the host user that owns the mounted artifacts/ directory):
#   docker build --build-arg USER_UID=$(id -u) --build-arg USER_GID=$(id -g) -t robot-agent .
#
# Simulation (no hardware):
#   docker run --rm -p 8000:8000 -e ROBOT_MODE=sim -e ROBOT_AGENT_TOKEN=<token> \
#     --add-host=host.docker.internal:host-gateway -e CC_BASE_URL=http://host.docker.internal:4000 \
#     robot-agent
#
# Real robot: host network/IPC for DDS (B2) and SocketCAN (Piper), plus devices and workspaces:
#   docker run -d --name robot-agent --network host --ipc host \
#     -e ROBOT_AGENT_TOKEN=<token> -e CC_BASE_URL=http://127.0.0.1:4000 \
#     -v "$PWD/artifacts:/app/artifacts" -v "$PWD/.claude/sessions:/app/.claude/sessions" \
#     -v "$HOME/unitree_ros2:/home/robot/unitree_ros2:ro" -v "$HOME/dog_ws:/home/robot/dog_ws:ro" \
#     -v "$HOME/icamera_demo:/home/robot/icamera_demo:ro" \
#     --device /dev/video4 -v /dev/bus/usb:/dev/bus/usb --device-cgroup-rule='c 189:* rmw' \
#     -v /var/log/journal:/var/log/journal:ro -v /etc/machine-id:/etc/machine-id:ro \
#     robot-agent

ARG ROS_DISTRO=humble
FROM ros:${ROS_DISTRO}-ros-base

ARG ROS_DISTRO
ARG USERNAME=robot
ARG USER_UID=1000
ARG USER_GID=1000

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# CycloneDDS for the B2; CLI tools used by ./robot status/logs/camera; gcc + libusb for the
# iCamera SDK loader that robot_tools builds on first use.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip \
        ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
        ffmpeg v4l-utils usbutils iproute2 procps systemd \
        gcc libc6-dev libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip install --upgrade pip

RUN groupadd --gid "${USER_GID}" "${USERNAME}" \
    && useradd --uid "${USER_UID}" --gid "${USER_GID}" --create-home --shell /bin/bash \
        --groups video,dialout,plugdev "${USERNAME}"

WORKDIR /app

# Install dependencies from pyproject.toml in their own layer (placeholder sources so the
# editable install resolves); the real sources are copied below. numpy/OpenCV stay on the
# numpy 1.x ABI used by ROS 2 Humble's Python packages.
COPY pyproject.toml README.md ./
RUN mkdir robot_agent robot_tools \
    && touch robot_agent/__init__.py robot_tools/__init__.py server.py copilot_stream_fix.py \
    && printf 'numpy<2\nopencv-python-headless<4.11\n' > /tmp/constraints.txt \
    && PIP_CONSTRAINT=/tmp/constraints.txt python3 -m pip install \
        --config-settings editable_mode=compat -e ".[robot]" \
    && rm -rf /tmp/constraints.txt *.egg-info

COPY --chown=${USERNAME}:${USERNAME} . .
RUN mkdir -p artifacts .claude/sessions \
    && chown -R "${USERNAME}:${USERNAME}" /app

USER ${USERNAME}
ENV HOME=/home/${USERNAME} \
    USER=${USERNAME} \
    ROBOT_PYTHON=/usr/bin/python3 \
    HOST=0.0.0.0 \
    PORT=8000

VOLUME ["/app/artifacts", "/app/.claude/sessions"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python3 -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/', timeout=4)"

# /ros_entrypoint.sh (from the base image) sources ROS 2; ./robot sources the overlays itself.
CMD ["sh", "-c", "exec uvicorn server:app --host \"$HOST\" --port \"$PORT\""]
