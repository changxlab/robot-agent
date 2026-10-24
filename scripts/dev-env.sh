# Shared defaults for scripts/dev-start.sh and scripts/dev-clear.sh (sourced, not executed).
# Override any of them from the environment, e.g. `CC_MODEL=claude-opus-5.5 scripts/dev-start.sh`.

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

: "${HOST:=127.0.0.1}"
: "${PORT:=8000}"
: "${LITELLM_PORT:=43429}"
: "${LITELLM_CONFIG:=$APP_DIR/config.yaml}"
# First interpreter that has the server dependencies (bare `python3` may be a conda env without them).
if [ -z "${PYTHON:-}" ]; then
    for candidate in "$APP_DIR/.venv/bin/python" /usr/bin/python3 python3; do
        if "$candidate" -c 'import uvicorn, fastapi, claude_agent_sdk' 2>/dev/null; then
            PYTHON=$candidate
            break
        fi
    done
    : "${PYTHON:=python3}"
fi
: "${LITELLM:=$(command -v litellm || echo "$HOME/.local/bin/litellm")}"
: "${ROBOT_MODE:=sim}"
: "${CC_MODEL:=gpt-6-luna}"
: "${CC_AUTH_TOKEN:=sk-cc-github-litellm}"
: "${CC_BASE_URL:=http://127.0.0.1:$LITELLM_PORT}"

LOG_DIR="$APP_DIR/artifacts/logs"
LITELLM_LOG="$LOG_DIR/litellm-dev.log"
SERVER_LOG="$LOG_DIR/server-dev.out"

# PIDs listening on a TCP port.
port_pids() {
    { ss -ltnpH "sport = :$1" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u; } || true
}

# A PID and all of its descendants (agent CLI shells, LiteLLM workers).
pid_tree() {
    local pid child
    for pid in "$@"; do
        echo "$pid"
        for child in $(ps -o pid= --ppid "$pid" 2>/dev/null); do
            pid_tree "$child"
        done
    done
}

# SIGTERM the given PIDs and their descendants, SIGKILL whatever is left after 10 s.
stop_pids() {
    local pids
    pids=$(pid_tree "$@" | sort -u)
    [ -n "$pids" ] || return 0
    kill -TERM $pids 2>/dev/null || true
    for _ in $(seq 20); do
        kill -0 $pids 2>/dev/null || return 0
        sleep 0.5
    done
    kill -KILL $pids 2>/dev/null || true
}

# Wait until an HTTP URL answers (any status), up to $2 seconds; give up early if PID $3 exits.
wait_http() {
    local url=$1 timeout=$2 pid=${3:-}
    for _ in $(seq "$timeout"); do
        curl -s --noproxy '*' -o /dev/null -m 2 "$url" && return 0
        [ -z "$pid" ] || kill -0 "$pid" 2>/dev/null || return 1
        sleep 1
    done
    return 1
}
