#!/usr/bin/env bash
# Start the dev debug stack: LiteLLM gateway on $LITELLM_PORT (reused if already up) and the web
# server on $HOST:$PORT. A server already on $PORT is stopped first.
#
#   scripts/dev-start.sh            server in the foreground (Ctrl+C stops it; LiteLLM keeps running)
#   scripts/dev-start.sh --reload   restart the server automatically when .py files change
#   scripts/dev-start.sh --bg       server in the background, output in artifacts/logs/server-dev.out
#
# Defaults (override from the environment): HOST=127.0.0.1 PORT=8000 LITELLM_PORT=43429
# ROBOT_MODE=sim CC_MODEL=gpt-6-luna. See scripts/dev-env.sh.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/dev-env.sh"

reload=0 background=0
for arg in "$@"; do
    case $arg in
        --reload) reload=1 ;;
        --bg) background=1 ;;
        -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

cd "$APP_DIR"
mkdir -p "$LOG_DIR"

# 1. LiteLLM gateway
if curl -s --noproxy '*' -o /dev/null -m 2 "http://127.0.0.1:$LITELLM_PORT/health/liveliness"; then
    echo "litellm: already running on :$LITELLM_PORT"
else
    pids=$(port_pids "$LITELLM_PORT")
    [ -z "$pids" ] || { echo "litellm: port :$LITELLM_PORT busy but unhealthy, stopping $pids"; stop_pids $pids; }
    echo "litellm: starting on :$LITELLM_PORT (log: $LITELLM_LOG)"
    setsid nohup "$LITELLM" --config "$LITELLM_CONFIG" --host 127.0.0.1 --port "$LITELLM_PORT" \
        >>"$LITELLM_LOG" 2>&1 </dev/null &
    if ! wait_http "http://127.0.0.1:$LITELLM_PORT/health/liveliness" 90 $!; then
        echo "litellm: did not come up within 90 s, last log lines:" >&2
        tail -n 20 "$LITELLM_LOG" >&2
        exit 1
    fi
    echo "litellm: ready"
fi

# 2. Web server
pids=$(port_pids "$PORT")
[ -z "$pids" ] || { echo "server : stopping previous server on :$PORT (PID $(echo $pids))"; stop_pids $pids; }

export ROBOT_MODE CC_MODEL CC_BASE_URL CC_AUTH_TOKEN PYTHONUNBUFFERED=1
cmd=("$PYTHON" -m uvicorn server:app --host "$HOST" --port "$PORT")
[ "$reload" = 0 ] || cmd+=(--reload)

echo "server : python=$PYTHON mode=$ROBOT_MODE model=$CC_MODEL gateway=$CC_BASE_URL"
if [ "$background" = 1 ]; then
    setsid nohup "${cmd[@]}" >>"$SERVER_LOG" 2>&1 </dev/null &
    if ! wait_http "http://$HOST:$PORT/" 30 $!; then
        echo "server : did not come up within 30 s, last log lines:" >&2
        tail -n 20 "$SERVER_LOG" >&2
        exit 1
    fi
    echo "server : running in background, PID $(echo $(port_pids "$PORT")) (log: $SERVER_LOG)"
    echo "open   : http://$HOST:$PORT/"
else
    echo "open   : http://$HOST:$PORT/"
    exec "${cmd[@]}"
fi
