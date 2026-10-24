#!/usr/bin/env bash
# Stop the dev debug stack (web server on $PORT, LiteLLM on $LITELLM_PORT) and clear Python caches.
# Chats (.claude/sessions/) and artifacts/ are kept.
#
#   scripts/dev-clear.sh            stop the server and the dev LiteLLM gateway
#   scripts/dev-clear.sh --keep-llm stop only the web server
#   scripts/dev-clear.sh --all      also stop every other `uvicorn server:app` / `litellm` started
#                                   from this project (other ports, e.g. the :4000 Claude Code gateway)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/dev-env.sh"

keep_llm=0 all=0
for arg in "$@"; do
    case $arg in
        --keep-llm) keep_llm=1 ;;
        --all) all=1 ;;
        -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

stop_port() {
    local name=$1 port=$2 pids
    pids=$(port_pids "$port")
    if [ -z "$pids" ]; then
        echo "$name: nothing listening on :$port"
        return
    fi
    echo "$name: stopping PID $(echo $pids) on :$port"
    stop_pids $pids
}

stop_port "server " "$PORT"
[ "$keep_llm" = 1 ] || stop_port "litellm" "$LITELLM_PORT"

if [ "$all" = 1 ]; then
    for pid in $(pgrep -f 'uvicorn server:app|litellm --config' || true); do
        [ "$(readlink "/proc/$pid/cwd" 2>/dev/null)" = "$APP_DIR" ] || continue
        echo "other  : stopping PID $pid ($(ps -o args= -p "$pid" | cut -c1-80))"
        stop_pids "$pid"
    done
fi

find "$APP_DIR" -path "$APP_DIR/.venv*" -prune -o -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$APP_DIR/.pytest_cache"
echo "caches : cleared __pycache__/ and .pytest_cache/"
